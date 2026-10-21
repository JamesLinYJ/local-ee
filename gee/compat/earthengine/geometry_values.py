"""Bounded planar geometry decoding for official legacy SDK serialization."""
from __future__ import annotations

import math

from .ir import fail


GEOMETRY_TYPES = frozenset({
    "Point", "MultiPoint", "LineString", "MultiLineString",
    "Polygon", "MultiPolygon", "GeometryCollection",
})
_MAX_COORDINATES = 10000


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


def decode_geometry(value):
    """Normalize supported options and validate before handing data to GEOS.

    Legacy geometry descriptions without an edge flag retain the compiler's
    existing local planar policy. Explicit spherical edges and left-inside
    interiors need a different geometry engine and are rejected.
    """
    budget = [0]

    def point(coordinates):
        if (not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2
                or any(type(number) not in (int, float) or not math.isfinite(number)
                       for number in coordinates)):
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
        if not isinstance(raw, dict) or raw.get("type") not in GEOMETRY_TYPES:
            fail("Expected a supported GeoJSON geometry")
        kind = raw["type"]
        field = "geometries" if kind == "GeometryCollection" else "coordinates"
        unknown = set(raw) - {"type", field, "crs", "geodesic", "evenOdd"}
        if unknown:
            fail(f"Unsupported GeoJSON geometry fields: {sorted(unknown)}")
        _crs(raw.get("crs"))
        if "geodesic" in raw and type(raw["geodesic"]) is not bool:
            fail("Geometry geodesic must be a boolean")
        if raw.get("geodesic") is True:
            fail("Geodesic geometries require spherical geometry support")
        if "evenOdd" in raw and type(raw["evenOdd"]) is not bool:
            fail("Geometry evenOdd must be a boolean")
        if raw.get("evenOdd") is False:
            fail("Geometry evenOdd=false left-inside interiors are unsupported")
        if kind == "GeometryCollection":
            children = raw.get(field)
            if not isinstance(children, list) or len(children) > 1000:
                fail("GeometryCollection requires at most 1000 inline geometries")
            output = {"type": kind, field: [decode(child, depth + 1) for child in children]}
        else:
            nesting = {"Point": 0, "MultiPoint": 1, "LineString": 1,
                       "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}[kind]
            raw_coordinates = raw.get(field)
            if kind == "MultiPolygon":
                if not isinstance(raw_coordinates, (list, tuple)) or not raw_coordinates:
                    fail("MultiPolygon coordinates must be nonempty")
                normalized = [coordinates(poly, 2, polygon=True) for poly in raw_coordinates]
            else:
                normalized = coordinates(raw_coordinates, nesting, polygon=kind == "Polygon")
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


def construct_geometry(translator, operation, arguments):
    """Resolve a constructor without dropping edge, interior or CRS options."""
    translator.allowed(arguments, {"coordinates", "crs", "geodesic", "evenOdd", "maxError"})
    if arguments.get("maxError") is not None:
        fail("Geometry constructor maxError reprojection is unsupported")
    if operation not in GEOMETRY_TYPES - {"GeometryCollection"} | {"Rectangle"}:
        fail(f"Unsupported geometry constructor: {operation}")
    coordinates = arguments.get("coordinates")
    if operation == "Rectangle":
        if isinstance(coordinates, (list, tuple)) and len(coordinates) == 4:
            west, south, east, north = coordinates
        elif (isinstance(coordinates, (list, tuple)) and len(coordinates) == 2
              and all(isinstance(point, (list, tuple)) and len(point) == 2 for point in coordinates)):
            (west, south), (east, north) = coordinates
        else:
            fail("Rectangle requires two positions or four coordinates")
        coordinates = [[[west, south], [east, south], [east, north], [west, north], [west, south]]]
        operation = "Polygon"
    options = {key: arguments[key] for key in ("crs", "geodesic", "evenOdd") if key in arguments}
    return decode_geometry({"type": operation, "coordinates": coordinates, **options})
