"""Pinned-signature geometry constructor normalization."""
from __future__ import annotations

import math

from .ir import fail


_CRS = frozenset({"crs"})
_EDGE = frozenset({"crs", "geodesic", "maxError"})
_POLYGON = frozenset({"crs", "geodesic", "maxError", "evenOdd"})
GEOMETRY_CONSTRUCTOR_ARGUMENTS = {
    "GeometryConstructors.BBox": (frozenset({"west", "south", "east", "north"}), frozenset()),
    "GeometryConstructors.LineString": (frozenset({"coordinates"}), _EDGE),
    "GeometryConstructors.LinearRing": (frozenset({"coordinates"}), _EDGE),
    "GeometryConstructors.MultiGeometry": (frozenset({"geometries"}), _EDGE),
    "GeometryConstructors.MultiLineString": (frozenset({"coordinates"}), _EDGE),
    "GeometryConstructors.MultiPoint": (frozenset({"coordinates"}), _CRS),
    "GeometryConstructors.MultiPolygon": (frozenset({"coordinates"}), _POLYGON),
    "GeometryConstructors.Point": (frozenset({"coordinates"}), _CRS),
    "GeometryConstructors.Polygon": (frozenset({"coordinates"}), _POLYGON),
    "GeometryConstructors.Rectangle": (
        frozenset({"coordinates"}), frozenset({"crs", "geodesic", "evenOdd"})),
}


def _check_arguments(translator, operation, arguments):
    name = f"GeometryConstructors.{operation}"
    signature = GEOMETRY_CONSTRUCTOR_ARGUMENTS.get(name)
    if signature is None:
        fail(f"Unsupported geometry constructor: {operation}")
    required, optional = signature
    translator.allowed(arguments, required | optional)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires arguments: {sorted(missing)}")
    if "maxError" in arguments and arguments["maxError"] is not None:
        fail("Geometry constructor maxError reprojection is unsupported")


def _finite_number(value, label):
    if type(value) not in (int, float):
        fail(f"Geometry BBox {label} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        fail(f"Geometry BBox {label} must be a finite number")
    return value


def _bbox(translator, arguments):
    west = _finite_number(arguments["west"], "west")
    south = _finite_number(arguments["south"], "south")
    east = _finite_number(arguments["east"], "east")
    north = _finite_number(arguments["north"], "north")
    if east - west >= 360:
        west, east = -180, 180
    else:
        west = _canonicalize_longitude(west)
        east = _canonicalize_longitude(east)
        if east < west:
            east += 360
        if east > 180:
            fail("Geometry BBox dateline wrapping is not supported by local geometry construction")
    if south > 90 or north < -90:
        fail("Geometry BBox bounds lie entirely beyond a pole")
    south = max(south, -90)
    north = min(north, 90)
    if north < south:
        fail("Geometry BBox north must be greater than or equal to south")
    geojson = {"type": "Polygon", "geodesic": False, "coordinates": [[
        [west, north], [west, south], [east, south], [east, north],
    ]]}
    from .geometry_values import decode_geometry_bounded

    return decode_geometry_bounded(translator, geojson)


def _canonicalize_longitude(value):
    """Match the pinned SDK's finite-longitude canonicalization."""
    value = value % 360
    return value - 360 if value > 180 else value


def construct_geometry_value(translator, operation, arguments):
    """Apply official constructor signatures and preserve accepted metadata."""
    _check_arguments(translator, operation, arguments)
    if operation == "BBox":
        return _bbox(translator, arguments)

    if operation == "MultiGeometry":
        value = {"type": "GeometryCollection", "geometries": arguments["geometries"]}
    else:
        coordinates = arguments["coordinates"]
        if operation == "Rectangle":
            if isinstance(coordinates, (list, tuple)) and len(coordinates) == 4:
                west, south, east, north = coordinates
            elif (isinstance(coordinates, (list, tuple)) and len(coordinates) == 2
                  and all(isinstance(point, (list, tuple)) and len(point) == 2
                          for point in coordinates)):
                (west, south), (east, north) = coordinates
            else:
                fail("Rectangle requires two positions or four coordinates")
            coordinates = [[[west, south], [east, south], [east, north], [west, north], [west, south]]]
            operation = "Polygon"
        value = {"type": operation, "coordinates": coordinates}

    for key in ("crs", "geodesic", "evenOdd"):
        if key in arguments:
            value[key] = arguments[key]
    from .geometry_values import decode_geometry_bounded

    result = decode_geometry_bounded(translator, value)
    if operation == "LinearRing":
        ring = result["coordinates"]
        if ring[0] != ring[-1]:
            ring.append(ring[0].copy())
    return result
