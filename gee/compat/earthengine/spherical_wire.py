"""Closed, bounded numeric wire for the repository-owned S2 C ABI.

This is an internal native protocol, never an Earth Engine serialization.
There is deliberately no guessed GeoJSON encoding for the full sphere.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .geometry_preflight import MAX_GEOMETRY_CHILDREN, MAX_GEOMETRY_COORDINATES
from .ir import fail


MAX_WIRE_DOUBLES = 65_536


@dataclass(frozen=True)
class FullSphere:
    """Boundaryless spherical region; public EE encoding is unverified."""


FULL_SPHERE = FullSphere()


def encode_geometry(geometry):
    """Encode an already admitted geometry without losing edge/interior rules."""
    records = []
    positions = 0
    active = set()

    def record(kind, even_odd, parts):
        nonlocal positions
        if len(records) >= MAX_GEOMETRY_CHILDREN:
            fail("S2 input exceeds 1000 atomic geometries")
        count = sum(map(len, parts))
        positions += count
        if positions > MAX_GEOMETRY_COORDINATES:
            fail("S2 input exceeds 10000 coordinate positions")
        item = [kind, int(even_odd), len(parts)]
        for part in parts:
            item.append(len(part))
            for point in part:
                if (type(point) not in (list, tuple) or len(point) != 2
                        or any(type(x) not in (int, float) for x in point)):
                    fail("S2 positions must contain two finite numbers")
                try:
                    valid = all(math.isfinite(x) for x in point)
                except OverflowError:
                    valid = False
                if not valid or not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90:
                    fail("S2 positions must be finite WGS84 longitude/latitude")
                item.extend(point)
        records.append(item)

    def visit(value, depth, inherited_geodesic=None, inherited_even_odd=None):
        if isinstance(value, FullSphere):
            record(2, False, [[]])
            return
        if depth > 16 or not isinstance(value, dict) or id(value) in active:
            fail("S2 geometry nesting exceeds its finite tree boundary")
        active.add(id(value))
        try:
            kind = value.get("type")
            metadata = getattr(value, "geometry_metadata", {})
            geodesic = value.get("geodesic", inherited_geodesic)
            even_odd = value.get("evenOdd", inherited_even_odd)
            if geodesic is None:
                geodesic = metadata.get("geodesic", True)
            if even_odd is None:
                even_odd = metadata.get("evenOdd", True)
            if type(geodesic) is not bool or type(even_odd) is not bool:
                fail("S2 geometry flags must be boolean")
            if kind == "GeometryCollection":
                # An absent collection flag does not overwrite individual
                # child sidecars. Explicit parent flags supply defaults only.
                child_geodesic = value.get("geodesic", metadata.get("geodesic", inherited_geodesic))
                child_even_odd = value.get("evenOdd", metadata.get("evenOdd", inherited_even_odd))
                for child in value["geometries"]:
                    visit(child, depth + 1, child_geodesic, child_even_odd)
                return
            coordinates = value["coordinates"]
            if kind == "Point":
                record(0, False, [[coordinates]])
            elif kind == "MultiPoint":
                if coordinates:
                    record(0, False, [coordinates])
            else:
                if not geodesic:
                    fail("Spherical operations on planar edges require bounded reprojection")
                if kind in {"LineString", "LinearRing"}:
                    record(1, False, [coordinates])
                elif kind == "MultiLineString":
                    for line in coordinates:
                        record(1, False, [line])
                elif kind == "Polygon":
                    record(2, even_odd, coordinates)
                elif kind == "MultiPolygon":
                    for polygon in coordinates:
                        record(2, even_odd, polygon)
                else:
                    fail("Unsupported S2 geometry type")
        finally:
            active.remove(id(value))

    visit(geometry, 0)
    wire = [1, len(records)]
    for item in records:
        if len(wire) + len(item) > MAX_WIRE_DOUBLES:
            fail("S2 numeric input exceeds 65536 values")
        wire.extend(item)
    return wire


def decode_geometry(wire, *, output_positions, output_children):
    """Decode native output under the reservation made before the operation."""
    from .geometry_values import GeometryValue

    cursor = 0
    positions = 0
    children = []

    def number():
        nonlocal cursor
        if cursor >= len(wire) or not math.isfinite(wire[cursor]):
            fail("S2 returned a malformed numeric output")
        value = wire[cursor]
        cursor += 1
        return value

    def count(limit):
        value = number()
        if value != int(value) or not 0 <= value <= limit:
            fail("S2 output exceeded its admitted count")
        return int(value)

    if count(1) != 1:
        fail("S2 returned an unsupported wire version")
    size = count(min(output_children, MAX_GEOMETRY_CHILDREN))
    for _ in range(size):
        kind, even_odd = count(2), count(1)
        part_count = count(MAX_GEOMETRY_COORDINATES)
        parts = []
        for _ in range(part_count):
            length = count(MAX_GEOMETRY_COORDINATES)
            positions += length
            if positions > min(output_positions, MAX_GEOMETRY_COORDINATES):
                fail("S2 output exceeded its precharged coordinate bound")
            part = []
            for _ in range(length):
                longitude, latitude = number(), number()
                if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
                    fail("S2 returned an invalid longitude/latitude")
                part.append([longitude, latitude])
            parts.append(part)
        if kind in {0, 1} and part_count != 1:
            fail("S2 returned malformed point/line parts")
        if kind == 2 and parts == [[]]:
            if even_odd or size != 1 or cursor != len(wire):
                fail("S2 returned an invalid full-sphere encoding")
            return FULL_SPHERE
        if kind == 0:
            points = parts[0]
            if not points:
                fail("S2 returned an empty point record")
            value = {"type": "Point" if len(points) == 1 else "MultiPoint",
                     "coordinates": points[0] if len(points) == 1 else points}
        elif kind == 1:
            if len(parts[0]) < 2:
                fail("S2 returned a malformed polyline")
            value = {"type": "LineString", "coordinates": parts[0]}
        else:
            if not parts or any(len(ring) < 4 or ring[0] != ring[-1] for ring in parts):
                fail("S2 returned malformed polygon rings")
            value = {"type": "Polygon", "coordinates": parts}
        # The pinned SDK Point/MultiPoint constructors accept neither flag;
        # line constructors accept geodesic but no evenOdd argument. Keep
        # effective metadata private unless that geometry kind supports it.
        if kind in {1, 2}:
            value["geodesic"] = True
        if kind == 2:
            value["evenOdd"] = bool(even_odd)
        children.append(GeometryValue(value, {
            "crs": "EPSG:4326", "geodesic": True,
            "evenOdd": bool(even_odd) if kind == 2 else True,
        }, validated=True))
    if cursor != len(wire):
        fail("S2 returned trailing numeric output")
    if len(children) == 1:
        return children[0]
    return GeometryValue({"type": "GeometryCollection", "geometries": children,
                          "geodesic": True},
                         {"crs": "EPSG:4326", "geodesic": True, "evenOdd": True},
                         validated=True)
