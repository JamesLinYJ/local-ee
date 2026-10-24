"""Bounded planar geometry decoding for official legacy SDK serialization."""
from __future__ import annotations

import math

from .geometry_preflight import (
    GEOMETRY_TYPES,
    measure_geometry,
    precharge_geometry_decode,
)
from .ir import fail


_MAX_COORDINATES = 10000


class GeometryValue(dict):
    """Owned normalized GeoJSON plus accepted constructor metadata."""

    def __init__(self, mapping, metadata=None, *, validated=False):
        super().__init__(mapping)
        self.geometry_metadata = dict(metadata or {})
        self._geometry_validated = validated is True


def _crs(value):
    # ee.Geometry.encode emits a named GeoJSON CRS, whereas constructors emit
    # an evaluated Projection. Never use set membership on an untrusted dict.
    if isinstance(value, dict):
        properties = value.get("properties")
        if (set(value) != {"type", "properties"} or value.get("type") != "name"
                or not isinstance(properties, dict) or set(properties) != {"name"}
                or not isinstance(properties["name"], str)):
            fail("Geometry CRS must be an EPSG:4326 string or named GeoJSON CRS")
        value = properties["name"]
    if value is not None and value != "EPSG:4326":
        fail("Only EPSG:4326 input GeoJSON geometries are supported")
    return value


def _geometry_metadata(value):
    stored = getattr(value, "geometry_metadata", {})
    if type(stored) is not dict:
        fail("Geometry constructor metadata is malformed")
    metadata = dict(stored)
    if set(metadata) - {"crs", "geodesic", "evenOdd"}:
        fail("Geometry constructor metadata is malformed")
    metadata.update({key: value[key] for key in ("crs", "geodesic", "evenOdd")
                     if key in value})
    if "crs" in metadata:
        metadata["crs"] = _crs(metadata["crs"])
    for key in ("geodesic", "evenOdd"):
        if key in metadata and type(metadata[key]) is not bool:
            fail(f"Geometry {key} must be a boolean")
    if metadata.get("geodesic") is True:
        fail("Geodesic geometries require spherical geometry support")
    if metadata.get("evenOdd") is False:
        fail("Geometry evenOdd=false left-inside interiors are unsupported")
    return metadata


def _normalize_geometry(value):
    """Validate supported options and return an independently owned mapping."""
    budget = [0]

    def point(coordinates):
        if (not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2
                or any(not _finite_coordinate(number) for number in coordinates)):
            fail("Geometry coordinates must be finite two-dimensional positions")
        x, y = coordinates
        if not -180 <= x <= 180 or not -90 <= y <= 90:
            fail("EPSG:4326 geometry coordinates exceed longitude/latitude bounds")
        budget[0] += 1
        if budget[0] > _MAX_COORDINATES:
            fail("Geometry exceeds 10000 coordinate positions")
        return [x, y]

    def coordinates(raw, depth, *, polygon=False):
        if depth == 0:
            return point(raw)
        if not isinstance(raw, (list, tuple)) or not raw:
            fail("Geometry coordinate arrays must be nonempty")
        result = [coordinates(child, depth - 1) for child in raw]
        if polygon:
            for ring in result:
                if len(ring) < 3:
                    fail("Polygon rings require at least three positions")
                if ring[0] != ring[-1]:
                    ring.append(ring[0].copy())
        return result

    def decode(raw, depth=0):
        if depth > 16:
            fail("Geometry collection nesting exceeds 16 levels")
        if (not isinstance(raw, dict) or type(raw.get("type")) is not str
                or raw["type"] not in GEOMETRY_TYPES):
            fail("Expected a supported GeoJSON geometry")
        kind = raw["type"]
        field = "geometries" if kind == "GeometryCollection" else "coordinates"
        unknown = set(raw) - {"type", field, "crs", "geodesic", "evenOdd"}
        if unknown:
            fail(f"Unsupported GeoJSON geometry fields: {sorted(unknown)}")
        _geometry_metadata(raw)
        if kind == "GeometryCollection":
            children = raw.get(field)
            if not isinstance(children, (list, tuple)) or len(children) > 1000:
                fail("GeometryCollection requires at most 1000 inline geometries")
            output = {"type": kind, field: [decode(child, depth + 1) for child in children]}
        else:
            nesting = {"Point": 0, "MultiPoint": 1, "LineString": 1,
                       "LinearRing": 1, "MultiLineString": 2, "Polygon": 2,
                       "MultiPolygon": 3}[kind]
            raw_coordinates = raw.get(field)
            empty_multi = (
                kind in {"MultiPoint", "MultiLineString", "MultiPolygon"}
                and isinstance(raw_coordinates, (list, tuple))
                and len(raw_coordinates) == 0
            )
            if empty_multi:
                normalized = []
            else:
                if kind == "MultiPolygon" and (
                        not isinstance(raw_coordinates, (list, tuple)) or not raw_coordinates):
                    fail("MultiPolygon coordinates must be nonempty")
                if kind == "MultiPolygon":
                    normalized = [coordinates(poly, 2, polygon=True)
                                  for poly in raw_coordinates]
                else:
                    normalized = coordinates(raw_coordinates, nesting,
                                             polygon=kind == "Polygon")
            output = {"type": kind, field: normalized}
        return output

    result = decode(value)
    from shapely.errors import GEOSException
    from shapely.geometry import shape
    try:
        geometry = shape(result)
    except (TypeError, ValueError, GEOSException) as error:
        fail(f"Invalid planar GeoJSON geometry: {error}")
    if not geometry.is_valid:
        fail("Invalid planar GeoJSON geometry topology")
    return result


def decode_geometry(value):
    """Normalize without a compiler budget for legacy non-translator callers."""
    measure_geometry(value)
    return _normalize_geometry(value)


def decode_geometry_value(value):
    """Normalize and own a geometry while retaining sidecar options."""
    measure_geometry(value)
    return _attach_geometry_metadata(value, _normalize_geometry(value))


def decode_geometry_bounded(translator, value):
    """Precharge one bounded decode, then validate and create owned GeoJSON."""
    precharge_geometry_decode(translator, value)
    normalized = _normalize_geometry(value)

    return _attach_geometry_metadata(value, normalized)


def _attach_geometry_metadata(raw, normalized):
    if raw["type"] == "GeometryCollection":
        for index, child in enumerate(raw["geometries"]):
            normalized["geometries"][index] = _attach_geometry_metadata(
                child, normalized["geometries"][index]
            )
    return GeometryValue(normalized, _geometry_metadata(raw), validated=True)


def own_geometry_bounded(translator, value):
    """Return an owned finite geometry after a fresh bounded validation.

    GeometryValue inherits mutable dict/list behavior, so its prior validation
    marker is informational and cannot authorize later contents.
    """
    return decode_geometry_bounded(translator, value)


def _finite_coordinate(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def construct_geometry(translator, operation, arguments):
    """Resolve a constructor without discarding supported geometry options."""
    from .geometry_constructors import construct_geometry_value

    return construct_geometry_value(translator, operation, arguments)
