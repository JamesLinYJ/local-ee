"""Trusted native bridge for independent spherical-polygon clip weights."""
from __future__ import annotations


_PROCESS_ID = "local_ee_clip_coverage"
_BAND_PRESERVING_OPERATIONS = {
    "spatial_extent", "weak_spatial_extent", "temporal_extent",
    "resample_spatial", "process_type",
}


def _one_band(metadata):
    if not metadata.has_band_dimension():
        raise ValueError(f"{_PROCESS_ID} requires an explicitly named band dimension")
    names = metadata.band_names
    if (type(names) not in (list, tuple) or len(names) != 1
            or type(names[0]) is not str or not names[0]):
        raise ValueError(f"{_PROCESS_ID} requires exactly one explicitly selected input band")


def _dry_run_band(cube):
    from openeo_driver.dry_run import DataTrace
    from .ee_cube_admission import validate_cube_trace

    validate_cube_trace(cube, _PROCESS_ID)
    if type(cube._traces) in (list, tuple) and len(cube._traces) == 1:
        trace = cube._traces[0]
        seen = set()
        for _ in range(500):
            if not isinstance(trace, DataTrace):
                break
            if id(trace) in seen:
                raise ValueError(f"{_PROCESS_ID} dry-run trace contains a cycle")
            seen.add(id(trace))
            if trace._operation == "bands":
                names = trace._arguments
                if (type(names) is not list or len(names) != 1
                        or type(names[0]) is not str or not names[0]):
                    raise ValueError(f"{_PROCESS_ID} requires exactly one explicitly selected input band")
                return
            if trace._operation not in _BAND_PRESERVING_OPERATIONS:
                break
            trace = trace.parent
        else:
            raise ValueError(f"{_PROCESS_ID} dry-run trace exceeds 500 operations")
    _one_band(cube.metadata)


def register_clip_coverage_pushdown_boundary():
    """The result v band must never be selected from the source imagery."""
    from openeo_driver.dry_run import PROPAGATION_RULES

    expected = {"bands", "resample", "spatial_extent", "weak_spatial_extent",
                "aggregate_spatial", "filter_spatial"}
    rules = [rule for rule in PROPAGATION_RULES if rule.constraint_key in expected]
    if {rule.constraint_key for rule in rules} != expected:
        raise RuntimeError("Pinned driver lacks required clip coverage pushdown boundaries")
    for rule in rules:
        if _PROCESS_ID not in rule.blockers:
            rule.blockers.append(_PROCESS_ID)


def local_ee_clip_coverage(args, env):
    from openeo_driver.dry_run import DryRunDataCube
    from gee.clip_coverage_spec import decode_clip_coverage_spec
    from .ee_process_adapters import _apply_native, _checked_args, _driver_cube

    args = _checked_args(args, _PROCESS_ID, {"data", "spec"})
    text = args["spec"]
    decode_clip_coverage_spec(text)
    cube = _driver_cube(args, _PROCESS_ID)
    if isinstance(cube, DryRunDataCube):
        _dry_run_band(cube)
    else:
        _one_band(cube.metadata)
    dimension = cube.metadata.band_dimension.name
    metadata = cube.metadata.reduce_dimension(dimension).add_dimension(dimension, "v", type="bands")
    if isinstance(cube, DryRunDataCube):
        register_clip_coverage_pushdown_boundary()
        return cube._process(_PROCESS_ID, {"spec": text}, metadata=metadata)
    return _apply_native(cube, _PROCESS_ID, {"spec": text}, metadata)
