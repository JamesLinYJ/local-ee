"""Exact owned Point outputs and their shared-budget reservations."""
from __future__ import annotations

import math
from types import SimpleNamespace

from .geometry_preflight import MAX_GEOMETRY_WORK, _charge
from .geometry_preflight import measure_geometry as measure_geometry_cost
from .geometry_preflight import precharge_geometry_decode
from .geometry_values import GeometryValue, _attach_geometry_metadata, _normalize_geometry
from .ir import fail

_CENTROID_COMPUTE_WORK = 32


def _centroid_output_work():
    # Charge the ordinary bounded geometry decode and public-mapping pass for
    # the one supported output shape before any native operation can run.
    template = GeometryValue(
        {"type": "Point", "coordinates": [0.0, 0.0]},
        {"crs": "EPSG:4326", "geodesic": True, "evenOdd": True},
    )
    cost = measure_geometry_cost(template)
    return (cost.nodes + cost.positions + 3 * cost.ring_closures
            + cost.nodes + cost.geometries + cost.positions
            + _CENTROID_COMPUTE_WORK)


_CENTROID_OUTPUT_WORK = _centroid_output_work()


def _make_centroid_point(lon, lat, label, output_budget, *,
                         compute_precharged=False, preserve_source_values=False):
    if (not math.isfinite(lon) or not math.isfinite(lat)
            or not -180.0 <= lon <= 180.0 or not -90.0 <= lat <= 90.0):
        fail(f"{label} returned an invalid centroid coordinate")
    raw = GeometryValue(
        {"type": "Point", "coordinates": (
            [lon, lat] if preserve_source_values else [float(lon), float(lat)]
        )},
        {"crs": "EPSG:4326", "geodesic": True, "evenOdd": True},
    )
    cost = precharge_geometry_decode(output_budget, raw)
    point = _attach_geometry_metadata(raw, _normalize_geometry(raw))
    _charge(output_budget, cost.nodes + cost.geometries + cost.positions,
            label + " centroid public geometry copy")
    if not compute_precharged:
        _charge(output_budget, _CENTROID_COMPUTE_WORK, label + " centroid result")
    if output_budget.steps != MAX_GEOMETRY_WORK:
        fail(f"{label} centroid did not consume its complete prepaid output bound")
    return point


def _exact_point_centroid(translator, coordinates, label, *, output_precharged=False):
    """Return an exact owned copy when point identity is provable without math."""
    if not output_precharged:
        _charge(translator, _CENTROID_OUTPUT_WORK,
                label + " exact point centroid output reservation")
    output_budget = SimpleNamespace(
        steps=MAX_GEOMETRY_WORK - _CENTROID_OUTPUT_WORK,
    )
    _charge(output_budget, _CENTROID_COMPUTE_WORK,
            label + " exact point identity result")
    point = _make_centroid_point(
        coordinates[0], coordinates[1], label, output_budget,
        compute_precharged=True, preserve_source_values=True,
    )
    return point


