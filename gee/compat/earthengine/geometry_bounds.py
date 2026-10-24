"""Bounded EPSG:4326 bounds for finite geometries and inline Features."""
from __future__ import annotations

import math
from types import SimpleNamespace

from .geometry_preflight import MAX_GEOMETRY_WORK, measure_geometry
from .geometry_topology import geometry_edge_models
from .geometry_values import decode_geometry_bounded
from .ir import fail


GEOMETRY_BOUNDS_ARGUMENTS = {
    "Geometry.bounds": (frozenset({"geometry"}), frozenset({"maxError", "proj"})),
    "Feature.bounds": (frozenset({"feature"}), frozenset({"maxError", "proj"})),
}
_BOUNDS_OUTPUT_WORK = 32
_ENVELOPE_RECORD_WORK = 8 + 3
# Exact structural charge for the sole supported output shape: one planar
# Polygon, one closed ring, and five 2D positions. The raw decoder pass counts
# 27 nodes, 5 positions, one geometry, and one ring closure. Its GeometryValue
# sidecar adds 34 nodes (CRS, geodesic, and evenOdd metadata), so the public
# mapping pass counts 61 nodes, 5 positions, and one geometry. Thus the normal
# output path charges 32 + (27 + 5 + 3*1) + (61 + 5 + 1) + 2*1 = 136.
_RECTANGLE_OUTPUT_WORK = (
    _BOUNDS_OUTPUT_WORK
    + (27 + 5 + 3 * 1)
    + (61 + 5 + 1)
    + 2 * 1
)


def _charge(translator, amount, label):
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or amount < 0 or amount > MAX_GEOMETRY_WORK
            or steps + amount > MAX_GEOMETRY_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _validate_arguments(translator, name, arguments):
    if type(arguments) is not dict:
        fail(f"{name} arguments must be a dictionary")
    required, optional = GEOMETRY_BOUNDS_ARGUMENTS[name]
    translator.allowed(arguments, required | optional)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires arguments: {sorted(missing)}")

    projection = arguments.get("proj")
    if projection is not None and (type(projection) is not str
                                   or projection != "EPSG:4326"):
        fail(f"{name} supports only EPSG:4326; other projections require unsupported reprojection")
    from .error_margin import validate_no_reprojection_margin

    validate_no_reprojection_margin(
        translator, arguments.get("maxError"), name + " maxError",
    )


def _coordinate_bounds(geometry):
    """Return exact extrema over the owned two-dimensional input positions."""
    extrema = [None, None, None, None]

    def visit(value):
        kind = value["type"]
        if kind == "GeometryCollection":
            for child in value["geometries"]:
                visit(child)
            return

        def positions(raw):
            if (type(raw) in (list, tuple) and len(raw) == 2
                    and type(raw[0]) in (int, float)
                    and type(raw[1]) in (int, float)):
                yield raw
                return
            if type(raw) in (list, tuple):
                for child in raw:
                    yield from positions(child)

        for point in positions(value["coordinates"]):
            longitude, latitude = point
            extrema[0] = longitude if extrema[0] is None else min(extrema[0], longitude)
            extrema[1] = latitude if extrema[1] is None else min(extrema[1], latitude)
            extrema[2] = longitude if extrema[2] is None else max(extrema[2], longitude)
            extrema[3] = latitude if extrema[3] is None else max(extrema[3], latitude)

    visit(geometry)
    if extrema[0] is None:
        return None
    return tuple(extrema)


def _validate_envelope(translator, value):
    from .spherical_envelope import Envelope

    # The record has eight ABI values (version, three flags, and four
    # coordinates); validating its three boolean flags is additional work.
    # Reserve this on the bounded prepaid view before inspecting the record.
    _charge(translator, _ENVELOPE_RECORD_WORK,
            "Spherical Geometry.bounds envelope record validation")

    if type(value) is not Envelope:
        fail("Spherical Geometry.bounds returned a malformed envelope")
    if any(type(getattr(value, name)) is not bool
           for name in ("empty", "full_longitude", "wrapped")):
        fail("Spherical Geometry.bounds returned malformed envelope flags")
    numbers = (value.west, value.south, value.east, value.north)
    if any(type(number) is not float or not math.isfinite(number) for number in numbers):
        fail("Spherical Geometry.bounds returned malformed envelope coordinates")
    if value.empty:
        if (value.full_longitude or value.wrapped
                or any(number != 0.0 for number in numbers)):
            fail("Spherical Geometry.bounds returned a malformed empty envelope")
        fail("Geometry.bounds cannot encode empty bounds as public GeoJSON")
    if value.full_longitude and value.wrapped:
        fail("Spherical Geometry.bounds returned conflicting longitude envelope flags")
    if (not -180.0 <= value.west <= 180.0
            or not -180.0 <= value.east <= 180.0
            or not -90.0 <= value.south <= value.north <= 90.0):
        fail("Spherical Geometry.bounds returned out-of-range envelope coordinates")
    if value.full_longitude:
        if value.west != -180.0 or value.east != 180.0:
            fail("Spherical Geometry.bounds returned malformed full-longitude bounds")
    else:
        if value.west == -180.0 and value.east == 180.0:
            fail("Spherical Geometry.bounds returned full longitude without its flag")
        if value.south == -90.0 or value.north == 90.0:
            fail("Spherical Geometry.bounds returned a pole-touching envelope without full longitude")
        if value.wrapped != (value.west > value.east):
            fail("Spherical Geometry.bounds returned inconsistent wrapped bounds")
    if value.wrapped:
        fail("Geometry.bounds wrapped-longitude public GeoJSON encoding is unverified")
    west, east = (-180.0, 180.0) if value.full_longitude else (value.west, value.east)
    if east <= west or value.north <= value.south:
        fail("Geometry.bounds empty or degenerate public GeoJSON encoding is unverified")
    return west, value.south, east, value.north


def _rectangle(translator, bounds, label):
    if bounds is None:
        fail(f"{label} empty public GeoJSON encoding is unverified")
    west, south, east, north = bounds
    if east <= west or north <= south:
        fail(f"{label} degenerate public GeoJSON encoding is unverified")

    _charge(translator, _BOUNDS_OUTPUT_WORK, label + " rectangle output")
    from .geometry_public import public_geometry_mapping

    # Bounds are coordinate-aligned in EPSG:4326. The new rectangle has
    # explicitly planar edges, regardless of the input edge model.
    geometry = decode_geometry_bounded(translator, {
        "type": "Polygon",
        "coordinates": [[
            [west, south], [east, south], [east, north],
            [west, north], [west, south],
        ]],
        "geodesic": False,
    })
    cost = measure_geometry(geometry)
    _charge(translator, cost.nodes + cost.geometries + cost.positions,
            label + " public geometry mapping")
    _charge(translator, 2 * cost.geometries, label + " public geometry flags")
    return public_geometry_mapping(geometry)


def _bounds_output_work(*, include_envelope):
    """Return the proved fixed charge without constructing any output."""
    return _RECTANGLE_OUTPUT_WORK + (
        _ENVELOPE_RECORD_WORK if include_envelope else 0
    )


def _precharge_bounds_output(translator, label, *, include_envelope):
    work = _bounds_output_work(include_envelope=include_envelope)
    _charge(translator, work, label + " complete output reservation")
    return work


def _render_prepaid_bounds(bounds, label, work, *, envelope=None):
    """Render against only the work already reserved on the parent budget."""
    output_budget = SimpleNamespace(steps=MAX_GEOMETRY_WORK - work)
    if envelope is not None:
        bounds = _validate_envelope(output_budget, envelope)
    result = _rectangle(output_budget, bounds, label)
    if output_budget.steps != MAX_GEOMETRY_WORK:
        fail(f"{label} output did not consume its complete prepaid work bound")
    return result


def _bounds_geometry(translator, raw_geometry, label):
    geometry = decode_geometry_bounded(translator, raw_geometry)
    cost = measure_geometry(geometry)
    _charge(translator, cost.nodes + cost.positions,
            label + " model and coordinate scan")

    models = tuple(geometry_edge_models(geometry))
    if any(type(model) is not bool for model in models):
        fail(f"{label} has an unresolved geometry edge model")
    if models and any(model is not models[0] for model in models[1:]):
        fail(f"{label} mixed geodesic edge models require unsupported reprojection")

    if models and models[0] is True:
        from .spherical_preflight import native_work
        from . import spherical_native

        closed_positions = cost.positions + cost.ring_closures
        work = 1 + cost.nodes + 4 * closed_positions + native_work(geometry)
        _charge(translator, work, label + " S2 bounds")
        output_work = _precharge_bounds_output(
            translator, label, include_envelope=True,
        )
        envelope = spherical_native.run("bounds", geometry)
        return _render_prepaid_bounds(
            None, label, output_work, envelope=envelope,
        )

    bounds = _coordinate_bounds(geometry)
    if bounds is None or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
        return _rectangle(translator, bounds, label)
    output_work = _precharge_bounds_output(
        translator, label, include_envelope=False,
    )
    return _render_prepaid_bounds(bounds, label, output_work)


def invoke_geometry_bounds(translator, name, arguments):
    """Evaluate Geometry.bounds and Feature.bounds with bounded ownership."""
    if name not in GEOMETRY_BOUNDS_ARGUMENTS:
        fail(f"Unsupported geometry bounds operation: {name}")
    _validate_arguments(translator, name, arguments)
    if name == "Geometry.bounds":
        return _bounds_geometry(translator, arguments["geometry"], name)

    from .feature_structure import _feature, _identity
    from .owned_metadata_values import owned_metadata_copy

    feature = _feature(translator, arguments["feature"], name)
    identity = _identity(feature)
    geometry = feature.get("geometry")
    if geometry is None:
        fail("Feature.bounds requires non-null geometry")
    properties = owned_metadata_copy(
        translator, feature["properties"], name + " properties",
    )
    bounded = _bounds_geometry(translator, geometry, name)
    result = {"type": "Feature", "geometry": bounded, "properties": properties}
    if "id" in feature:
        result["id"] = feature["id"]
    elif identity is not None and "system:index" not in properties:
        result["id"] = identity
    return result
