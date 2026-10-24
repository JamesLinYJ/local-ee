"""GEE's omitted/null projection route, backed by actual local S2 operations."""
from __future__ import annotations

from .geometry_binary_plan import reserve_geometry_binary
from .geometry_preflight import MAX_GEOMETRY_WORK, measure_geometry
from .geometry_values import decode_geometry_bounded
from .ir import fail
from .spherical_preflight import native_work
from .spherical_wire import FullSphere


def _stats(value):
    from .geometry_binary import _stats as geometry_stats

    if isinstance(value, FullSphere):
        return {"positions": 0, "segments": 0, "rings": 0, "components": 1,
                "dimensions": frozenset({2})}
    return geometry_stats(value)


def _own(translator, geometry):
    return geometry if isinstance(geometry, FullSphere) else decode_geometry_bounded(translator, geometry)


def invoke_spherical_binary(translator, name, arguments):
    """Keep spherical defaults separate from the explicitly projected branch.

    Non-null margins and planar-edge transformations remain explicit gaps.
    No projection or edge flag is silently rewritten to admit a request.
    """
    from .geometry_binary import _charge
    from .spherical_native import run

    if arguments.get("proj") is not None:
        fail("Spherical geometry operations require an omitted/null projection")
    if arguments.get("maxError") is not None:
        fail("Spherical geometry maxError transformations are not implemented")
    # Freshly validate and detach mutable geometry trees. Their constructor
    # metadata, including effective defaults, is kept by the ordinary decoder.
    left, right = (_own(translator, arguments[key]) for key in ("left", "right"))
    left_stats, right_stats = _stats(left), _stats(right)
    work, output_work, positions, children = reserve_geometry_binary(name, left_stats, right_stats)
    # Normalizing a mixed region can require successive component unions.
    # Reserve their repeated scans before packing or entering the native ABI.
    _charge(translator, work + output_work + native_work(left, right),
            name + " spherical operation")
    method = name.removeprefix("Geometry.")
    result = run(method, left, right, output_positions=positions,
                 output_children=max(1, children))
    if method in {"contains", "containedIn", "intersects", "disjoint"}:
        return result
    if isinstance(result, FullSphere):
        return result
    # Output mapping is already charged at its conservative worst-case bound.
    # Recheck counts without invoking GEOS, copying again, or refunding work.
    cost = measure_geometry(result)
    if cost.positions > positions or cost.nodes + cost.positions > output_work:
        fail("S2 geometry output exceeded its precharged work/position bound")
    if translator.steps > MAX_GEOMETRY_WORK:
        fail("S2 geometry operation exceeded the shared compilation budget")
    return result
