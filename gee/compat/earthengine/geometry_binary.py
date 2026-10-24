"""Bounded planar implementations of the pinned Geometry binary algorithms.

These operations require an explicit EPSG:4326 projection and explicit planar
edges. Shapely's OGC ``contains`` policy excludes a point lying only on the
container boundary; this is a local policy, not a claim of GEE parity.
"""
from __future__ import annotations

from types import SimpleNamespace

from shapely.errors import GEOSException
from shapely.geometry import mapping, shape

from .geometry_preflight import (
    MAX_GEOMETRY_CHILDREN,
    MAX_GEOMETRY_DEPTH,
    MAX_GEOMETRY_WORK,
    measure_geometry,
)
from .geometry_binary_plan import reserve_geometry_binary
from .geometry_values import decode_geometry_bounded
from .ir import fail


_BINARY = ("contains", "containedIn", "intersects", "disjoint", "intersection",
           "union", "difference", "symmetricDifference")
GEOMETRY_BINARY_FUNCTIONS = frozenset(f"Geometry.{name}" for name in _BINARY)
GEOMETRY_BINARY_ARGUMENTS = {
    name: (frozenset({"left", "right"}), frozenset({"maxError", "proj"}))
    for name in GEOMETRY_BINARY_FUNCTIONS
}
_PREDICATES = frozenset({"Geometry.contains", "Geometry.containedIn",
                         "Geometry.intersects", "Geometry.disjoint"})
_OPERATIONS = {
    "Geometry.intersection": "intersection",
    "Geometry.union": "union",
    "Geometry.difference": "difference",
    "Geometry.symmetricDifference": "symmetric_difference",
}


def _line_segments(line):
    return max(0, len(line) - 1)


def _stats(geometry, *, name=None):
    """Count positions, line segments, atomic components, and dimensions."""
    kind = geometry["type"]
    if kind == "GeometryCollection":
        children = [_stats(child, name=name) for child in geometry["geometries"]]
        return {
            "positions": sum(item["positions"] for item in children),
            "segments": sum(item["segments"] for item in children),
            "rings": sum(item["rings"] for item in children),
            "components": sum(item["components"] for item in children),
            "dimensions": frozenset().union(*(item["dimensions"] for item in children)),
        }
    coordinates = geometry["coordinates"]
    if kind == "Point":
        return {"positions": 1, "segments": 0, "rings": 0, "components": 1,
                "dimensions": frozenset({0})}
    if kind == "MultiPoint":
        return {"positions": len(coordinates), "segments": 0, "rings": 0,
                "components": len(coordinates), "dimensions": frozenset({0})}
    if kind in {"LineString", "LinearRing"}:
        # Assume an extra closing coordinate/edge without comparing mutable
        # coordinate leaves before the decoder validates their numeric types.
        positions = len(coordinates) + int(kind == "LinearRing")
        segments = len(coordinates) if kind == "LinearRing" else _line_segments(coordinates)
        stats = {"positions": positions, "segments": max(0, segments), "rings": 0,
                "components": int(bool(coordinates)), "dimensions": frozenset({1})}
        _check_edge_flag(geometry, kind, stats, name)
        return stats
    if kind == "MultiLineString":
        positions = sum(map(len, coordinates))
        segments = sum(_line_segments(line) for line in coordinates)
        stats = {"positions": positions, "segments": segments, "rings": 0,
                "components": len(coordinates), "dimensions": frozenset({1})}
        _check_edge_flag(geometry, kind, stats, name)
        return stats
    rings = coordinates if kind == "Polygon" else [ring for polygon in coordinates for ring in polygon]
    # Every ring may need the decoder's closure insertion; the extra slot is
    # intentionally reserved even when the mutable input is already closed.
    positions = sum(len(ring) + 1 for ring in rings)
    segments = sum(len(ring) for ring in rings)
    if kind == "Polygon":
        components = int(bool(coordinates))
        rings = len(coordinates)
    else:
        components = len(coordinates)
        rings = sum(len(polygon) for polygon in coordinates)
    stats = {"positions": positions,
            "segments": segments,
            "rings": rings,
            "components": components, "dimensions": frozenset({2})}
    _check_edge_flag(geometry, kind, stats, name)
    return stats


def _check_edge_flag(geometry, kind, stats, name):
    """Require every nonempty edge-bearing component to declare planar edges."""
    if name is None or kind in {"Point", "MultiPoint"} or stats["segments"] == 0:
        return
    metadata = getattr(geometry, "geometry_metadata", {})
    geodesic = metadata.get("geodesic", geometry.get("geodesic"))
    if geodesic is True:
        fail(f"{name} does not support spherical geometry edges")
    if geodesic is not False:
        fail(f"{name} requires explicit geodesic=false for every component with edges")


def _geojson(geometry, child_budget, depth=0):
    """Map GEOS output to finite GeoJSON, replacing empties without NaN."""
    if depth > MAX_GEOMETRY_DEPTH:
        fail("Geometry binary result nesting exceeds 16 levels")
    if geometry.is_empty:
        value = {"type": "GeometryCollection", "geometries": []}
        return _planar_geojson(value)
    kind = geometry.geom_type
    if kind == "GeometryCollection":
        children = []
        for child in geometry.geoms:
            if child.is_empty:
                continue
            if child_budget[0] < 1:
                fail("Geometry binary result exceeded its precharged child bound")
            child_budget[0] -= 1
            children.append(_geojson(child, child_budget, depth + 1))
        value = {"type": "GeometryCollection", "geometries": children}
    elif kind == "MultiPoint":
        value = {"type": kind, "coordinates": [list(point.coords[0])
                                                for point in geometry.geoms if not point.is_empty]}
    elif kind == "MultiLineString":
        value = {"type": kind, "coordinates": [list(line.coords)
                                                for line in geometry.geoms if not line.is_empty]}
    elif kind == "MultiPolygon":
        value = {"type": kind, "coordinates": [mapping(polygon)["coordinates"]
                                                for polygon in geometry.geoms if not polygon.is_empty]}
    else:
        value = dict(mapping(geometry))
    return _planar_geojson(value)


def _planar_geojson(value):
    """Attach SDK-valid CRS and explicit planar-edge flags to owned output."""
    value["crs"] = {"type": "name", "properties": {"name": "EPSG:4326"}}
    value["geodesic"] = False
    return value


def _charge(translator, amount, label):
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or amount < 0 or amount > MAX_GEOMETRY_WORK
            or steps + amount > MAX_GEOMETRY_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _decode_work(cost):
    return cost.nodes + cost.positions + 3 * cost.ring_closures


def _collection_child_count(geometry):
    if geometry["type"] != "GeometryCollection":
        return 0
    children = geometry["geometries"]
    return len(children) + sum(_collection_child_count(child) for child in children)


def _expose_planar_flag(geometry):
    """Keep geodesic=false in public GeoJSON while retaining sidecar metadata."""
    geometry["geodesic"] = False
    if geometry["type"] == "GeometryCollection":
        for child in geometry["geometries"]:
            _expose_planar_flag(child)
    return geometry


def invoke_geometry_binary(translator, name, arguments):
    """Evaluate one exact-signature binary geometry operation with bounded work."""
    if name not in GEOMETRY_BINARY_ARGUMENTS:
        fail(f"Unsupported geometry binary operation: {name}")
    required, optional = GEOMETRY_BINARY_ARGUMENTS[name]
    translator.allowed(arguments, required | optional)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires arguments: {sorted(missing)}")
    if "maxError" in arguments and arguments["maxError"] is not None:
        fail("Geometry binary maxError reprojection is unsupported")
    if type(arguments.get("proj")) is not str or arguments["proj"] != "EPSG:4326":
        fail("Geometry binary operations require explicit proj='EPSG:4326'; omitted/null proj is spherical")

    # Measure and reserve both input decodes plus the binary pair/output bound
    # before any GEOS construction or operation. The first structural count is
    # bounded by measure_geometry; every subsequent scan is charged below.
    raw_left, raw_right = arguments["left"], arguments["right"]
    left_cost, right_cost = measure_geometry(raw_left), measure_geometry(raw_right)
    scan_work = 2 * (left_cost.nodes + left_cost.positions
                     + right_cost.nodes + right_cost.positions)
    _charge(translator, scan_work, "Geometry binary input scan")
    left_stats, right_stats = _stats(raw_left, name=name), _stats(raw_right, name=name)
    operation_work, output_work, output_limit, child_limit = reserve_geometry_binary(
        name, left_stats, right_stats,
    )
    left_decode, right_decode = _decode_work(left_cost), _decode_work(right_cost)
    start = translator.steps
    reservation = left_decode + right_decode + operation_work + output_work
    if start + reservation > MAX_GEOMETRY_WORK:
        fail(f"{name} exceeds the shared 50000-step compilation work budget")
    translator.steps = start + reservation
    translator.steps -= left_decode
    left = decode_geometry_bounded(translator, raw_left)
    translator.steps -= right_decode
    right = decode_geometry_bounded(translator, raw_right)
    try:
        left_shape, right_shape = shape(left), shape(right)
        if name == "Geometry.contains":
            result = left_shape.contains(right_shape)
        elif name == "Geometry.containedIn":
            result = right_shape.contains(left_shape)
        elif name == "Geometry.intersects":
            result = left_shape.intersects(right_shape)
        elif name == "Geometry.disjoint":
            result = left_shape.disjoint(right_shape)
        else:
            result = getattr(left_shape, _OPERATIONS[name])(right_shape)
    except (GEOSException, TypeError, ValueError) as error:
        fail(f"{name} planar operation failed: {error}")

    if name in _PREDICATES:
        return bool(result)
    value = _geojson(result, [child_limit])
    measured = measure_geometry(value)
    actual_decode_work = _decode_work(measured)
    if (measured.positions > output_limit or actual_decode_work > output_work
            or _collection_child_count(value) > min(child_limit, MAX_GEOMETRY_CHILDREN)):
        fail("Geometry binary result exceeded its precharged output bound")
    # The parent budget keeps the full output reservation. The temporary view
    # lets the ordinary decoder perform its own exact precharge against the
    # already-admitted allowance without charging that allowance twice.
    output_base = start + left_decode + right_decode + operation_work
    result_budget = SimpleNamespace(steps=output_base)
    decoded = decode_geometry_bounded(result_budget, value)
    return _expose_planar_flag(decoded)
