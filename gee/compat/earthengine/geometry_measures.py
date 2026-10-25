"""Bounded Geometry measures with separate planar, WGS84 and centroid paths."""
from __future__ import annotations

import math
from types import SimpleNamespace

from .geometry_preflight import (
    MAX_GEOMETRY_WORK,
    precharge_geometry_decode,
)
from .geometry_topology import geometry_edge_models
from .geometry_planar_measures import (
    PLANAR_WORK_PER_GEOMETRY,
    PLANAR_WORK_PER_NODE,
    PLANAR_WORK_PER_POSITION,
    PLANAR_WORK_PER_RING,
    planar_components,
    planar_result,
)
from .geometry_values import _attach_geometry_metadata, _normalize_geometry
from .ir import fail
from .spherical_measures import centroid_lon_lat, decode_measure_record
from .geometry_measure_outputs import (
    _CENTROID_COMPUTE_WORK, _CENTROID_OUTPUT_WORK,
    _exact_point_centroid, _make_centroid_point,
)
from . import geometry_measure_cache as cache


GEOMETRY_MEASURE_METHODS = frozenset({
    "Geometry.area", "Geometry.length", "Geometry.perimeter", "Geometry.centroid",
})
GEOMETRY_MEASURE_ARGUMENTS = {
    name: (frozenset({"geometry"}), frozenset({"maxError", "proj"}))
    for name in GEOMETRY_MEASURE_METHODS
}
FEATURE_MEASURE_METHODS = frozenset({
    "Feature.area", "Feature.length", "Feature.perimeter", "Feature.centroid",
})
FEATURE_MEASURE_ARGUMENTS = {
    name: (frozenset({"feature"}), frozenset({"maxError", "proj"}))
    for name in FEATURE_MEASURE_METHODS
}

# The output validator reserves one slot/type visit per native field, six
# numeric conversions/finiteness checks, three nonnegative checks and four
# dimension/empty invariants before entering either native operation.
_MEASURE_RECORD_VALIDATION_WORK = 8 + 8 + 6 + 3 + 4
_ELLIPSOID_RECORD_VALIDATION_WORK = 2 + 2 + 1 + 1
_SCALAR_OUTPUT_WORK = 4


def _charge(translator, amount, label):
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or type(amount) is not int or amount < 0
            or steps < 0 or steps + amount > MAX_GEOMETRY_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _arguments(translator, name, arguments, contract):
    if type(arguments) is not dict:
        fail(f"{name} arguments must be a dictionary")
    required, optional = contract[name]
    translator.allowed(arguments, required | optional)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires arguments: {sorted(missing)}")


def _prepare_geometry(translator, raw, label):
    """Freshly preflight and own input without rejecting cross-part overlap."""
    cost = precharge_geometry_decode(translator, raw)
    geometry = _attach_geometry_metadata(raw, _normalize_geometry(raw))
    _charge(translator, cost.nodes + cost.positions + cost.geometries,
            label + " edge-model/component scan")
    models = tuple(geometry_edge_models(geometry))
    if any(type(model) is not bool for model in models):
        fail(f"{label} has an unresolved geodesic edge model")
    return geometry, cost, models


def _route(translator, name, projection, max_error, models):
    if projection is None:
        if any(model is not True for model in models):
            fail(f"{name} cannot transform planar edges to the default WGS84 great-circle model")
        route = "spherical"
    else:
        if type(projection) is not str or projection != "EPSG:4326":
            fail(f"{name} supports only EPSG:4326; other projections require unsupported reprojection")
        if any(model is not False for model in models):
            fail(f"{name} cannot transform geodesic edges to planar EPSG:4326 coordinates")
        route = "planar"

    # Both admitted routes operate in the input coordinate system and preserve
    # its declared edge model; neither performs reprojection.
    from .error_margin import validate_no_reprojection_margin

    validate_no_reprojection_margin(translator, max_error, name + " maxError")
    return route


def _spherical_centroid(translator, geometry, cost, label, summary):
    from .spherical_preflight import native_work
    from .spherical_native import run_measures

    # `native_work` performs its own complete structural count. Reserve that
    # traversal before computing its quadratic W0 value.
    _charge(translator, cost.nodes + cost.positions + cost.geometries,
            label + " S2 native work-count scan")
    closed_positions = cost.positions + cost.ring_closures
    native_charge = 1 + cost.nodes + 4 * closed_positions + native_work(geometry)
    output_work = _MEASURE_RECORD_VALIDATION_WORK + _CENTROID_OUTPUT_WORK
    _charge(translator, native_charge, label + " S2 centroid operation")
    _charge(translator, output_work, label + " native record and centroid output reservation")
    raw = run_measures(geometry)
    output_budget = SimpleNamespace(steps=MAX_GEOMETRY_WORK - output_work)
    _charge(output_budget, _MEASURE_RECORD_VALIDATION_WORK,
            label + " S2 record validation")
    record = decode_measure_record(raw)
    _charge(output_budget, _CENTROID_COMPUTE_WORK, label + " centroid coordinate computation")
    dimension, dimension_positions, dimension_components = summary
    if (record.dimension != dimension or dimension_positions <= 0
            or dimension_components <= 0):
        fail(f"{label} native and validated centroid dimensions disagree")
    longitude, latitude = centroid_lon_lat(
        record,
        dimension_positions=dimension_positions,
        dimension_components=dimension_components,
    )
    point = _make_centroid_point(
        longitude, latitude, label, output_budget, compute_precharged=True,
    )
    if output_budget.steps != MAX_GEOMETRY_WORK:
        fail(f"{label} centroid exceeded its complete prepaid output bound")
    return point


def _ellipsoid_metric(translator, geometry, method, cost, label):
    from .ellipsoid_preflight import metric_native_work
    from .spherical_native import run_ellipsoid_measure

    output_work = _ELLIPSOID_RECORD_VALIDATION_WORK + _SCALAR_OUTPUT_WORK
    # metric_native_work performs one base-shape walk and one selected-edge
    # walk; reserve both independently of the earlier model/dimension scan.
    count_scan_work = 2 * (cost.nodes + cost.positions + cost.geometries)
    _charge(translator, count_scan_work,
            label + " WGS84 native work-count scans")
    native_work = metric_native_work(geometry, method)
    _charge(translator, native_work, label + " WGS84 native measure operation")
    _charge(translator, output_work, label + " fixed native result reservation")
    raw = run_ellipsoid_measure(geometry, method)
    output_budget = SimpleNamespace(steps=MAX_GEOMETRY_WORK - output_work)
    _charge(output_budget, _ELLIPSOID_RECORD_VALIDATION_WORK,
            label + " WGS84 result validation")
    if (type(raw) not in (tuple, list) or len(raw) != 2
            or type(raw[0]) not in (float, int) or raw[0] != 1.0
            or type(raw[1]) not in (float, int)):
        fail(f"{label} returned a malformed WGS84 measure record")
    try:
        value = float(raw[1])
    except (OverflowError, TypeError, ValueError):
        fail(f"{label} returned an invalid WGS84 measure")
    if not math.isfinite(value) or value < 0:
        fail(f"{label} returned a non-finite or negative WGS84 measure")
    _charge(output_budget, _SCALAR_OUTPUT_WORK, label + " scalar result")
    if output_budget.steps != MAX_GEOMETRY_WORK:
        fail(f"{label} did not consume its complete prepaid result bound")
    return value


def _evaluate(translator, name, method, raw, *, projection=None, max_error=None,
              allow_null=False):
    if raw is None and allow_null:
        route = _route(translator, name, projection, max_error, ())
        if method == "centroid":
            fail(f"{name} has no highest-dimension component")
        _charge(translator, _SCALAR_OUTPUT_WORK, name + " empty scalar result")
        return 0.0

    ticket = cache.lookup(translator, raw, create=True)
    models = ticket.entry.models if ticket else None
    route = None
    if models is not None:
        route = _route(translator, name, projection, max_error, models)
        saved = cache.cached_result(translator, ticket, route, method)
        if saved is not cache.ABSENT:
            value, native = saved
            _charge(translator, _CENTROID_OUTPUT_WORK if method == "centroid"
                    else _SCALAR_OUTPUT_WORK, name + " cached result output reservation")
            if native:
                from .spherical_native import _load

                _load()
            if method == "centroid":
                return _exact_point_centroid(translator, value, name, output_precharged=True)
            return value
    prepared = cache.restore_component(translator, ticket) if ticket else None
    if prepared is None:
        prepared = _prepare_geometry(translator, raw, name)
    if route is None:
        route = _route(translator, name, projection, max_error, prepared[2])
    ticket = cache.reserve_result(translator, ticket)
    native = [False]
    result = _evaluate_prepared(translator, name, method, prepared, route, native)
    cache.store_result(translator, ticket, route, method, result, prepared[2], native[0])
    return result


def _evaluate_prepared(translator, name, method, prepared, route, native):
    geometry, cost, models = prepared
    centroid_summary = None
    if method == "centroid":
        _charge(translator, cost.nodes + cost.positions + cost.geometries,
                name + " centroid highest-dimension component scan")
        centroid_summary = _highest_component_counts(geometry)
        if route == "spherical" and centroid_summary[0] < 0:
            fail(f"{name} has no highest-dimension component")
        if geometry["type"] == "Point":
            return _exact_point_centroid(
                translator, geometry["coordinates"], name,
            )
        if geometry["type"] == "MultiPoint":
            coordinates = geometry["coordinates"]
            _charge(translator, cost.positions,
                    name + " exact multipoint identity proof scan")
            if coordinates and all(point == coordinates[0] for point in coordinates[1:]):
                return _exact_point_centroid(translator, coordinates[0], name)

    planar_extra = (
        cost.nodes * PLANAR_WORK_PER_NODE
        + cost.positions * PLANAR_WORK_PER_POSITION
        + cost.geometries * PLANAR_WORK_PER_GEOMETRY
        + cost.ring_closures * PLANAR_WORK_PER_RING
    )
    output_work = _CENTROID_OUTPUT_WORK if method == "centroid" else _SCALAR_OUTPUT_WORK

    if route == "spherical":
        if not models:
            if method == "centroid":
                # Point-only geometries still use the S2 weighted centroid.
                native[0] = True
                return _spherical_centroid(
                    translator, geometry, cost, name, centroid_summary,
                )
            _charge(translator, output_work, name + " empty-measure result")
            return 0.0
        if method == "centroid":
            native[0] = True
            return _spherical_centroid(
                translator, geometry, cost, name, centroid_summary,
            )
        native[0] = True
        return _ellipsoid_metric(translator, geometry, method, cost, name)

    _charge(translator, planar_extra + output_work,
            name + " planar component and output reservation")
    components = planar_components(geometry, name)
    value = planar_result(components, method, name)
    if method != "centroid":
        return value
    longitude, latitude = value
    output_budget = SimpleNamespace(steps=MAX_GEOMETRY_WORK - _CENTROID_OUTPUT_WORK)
    _charge(output_budget, _CENTROID_COMPUTE_WORK,
            name + " centroid coordinate computation")
    point = _make_centroid_point(
        longitude, latitude, name, output_budget, compute_precharged=True,
    )
    if output_budget.steps != MAX_GEOMETRY_WORK:
        fail(f"{name} centroid exceeded its complete prepaid output bound")
    return point


def _highest_component_counts(value):
    """Count positions and native component records by active dimension."""
    counts = [[0, 0] for _ in range(3)]
    kind = value["type"]
    if kind == "GeometryCollection":
        for child in value["geometries"]:
            child_dimension, child_positions, child_components = _highest_component_counts(child)
            if child_dimension >= 0:
                counts[child_dimension][0] += child_positions
                counts[child_dimension][1] += child_components
    elif kind == "Point":
        counts[0][0] += 1
        counts[0][1] += 1
    elif kind == "MultiPoint" and value["coordinates"]:
        counts[0][0] += len(value["coordinates"])
        counts[0][1] += 1
    elif kind in {"LineString", "LinearRing"} and len(value["coordinates"]) >= 2:
        counts[1][0] += len(value["coordinates"])
        counts[1][1] += 1
    elif kind == "MultiLineString":
        for line in value["coordinates"]:
            if len(line) >= 2:
                counts[1][0] += len(line)
                counts[1][1] += 1
    elif kind == "Polygon" and value["coordinates"]:
        counts[2][0] += sum(len(ring) for ring in value["coordinates"])
        counts[2][1] += 1
    elif kind == "MultiPolygon":
        for polygon in value["coordinates"]:
            if polygon:
                counts[2][0] += sum(len(ring) for ring in polygon)
                counts[2][1] += 1
    dimension = max((index for index, (_, components) in enumerate(counts)
                     if components), default=-1)
    if dimension < 0:
        return -1, 0, 0
    return dimension, counts[dimension][0], counts[dimension][1]


def invoke_geometry_measures(translator, name, arguments):
    """Evaluate one Geometry area/length/perimeter/centroid operation."""
    if name not in GEOMETRY_MEASURE_METHODS:
        fail(f"Unsupported Geometry measure operation: {name}")
    _arguments(translator, name, arguments, GEOMETRY_MEASURE_ARGUMENTS)
    method = name.removeprefix("Geometry.")
    return _evaluate(
        translator, name, method, arguments["geometry"],
        projection=arguments.get("proj"), max_error=arguments.get("maxError"),
    )
