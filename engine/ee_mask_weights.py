"""Trusted bridge for bounded native fractional-mask weight projections."""
from __future__ import annotations


_PROCESS_ID = "local_ee_mask_weights"
_BAND_PRESERVING_TRACE_OPERATIONS = {
    "spatial_extent", "weak_spatial_extent", "temporal_extent",
    "resample_spatial", "process_type",
}


def _input_band_count(spec):
    from gee.mask_weights_spec import MASK_WEIGHT_ARITIES

    return MASK_WEIGHT_ARITIES[spec["op"]]


def _output_metadata(metadata):
    if not metadata.has_band_dimension():
        raise ValueError(f"{_PROCESS_ID} requires an explicitly named input band dimension")
    dimension = metadata.band_dimension.name
    return metadata.reduce_dimension(dimension).add_dimension(dimension, "v", type="bands")


def _validate_input_bands(metadata, expected_count):
    if not metadata.has_band_dimension():
        raise ValueError(f"{_PROCESS_ID} requires an explicitly named input band dimension")
    names = metadata.band_names
    if (type(names) not in (list, tuple) or len(names) != expected_count
            or any(type(name) is not str or not name for name in names)):
        raise ValueError(
            f"{_PROCESS_ID} requires exactly {expected_count} explicitly named ordered input bands"
        )


def _validate_dry_run_input_bands(cube, expected_count):
    from openeo_driver.dry_run import DataTrace
    from .ee_cube_admission import validate_cube_trace

    validate_cube_trace(cube, _PROCESS_ID)
    if type(cube._traces) in (list, tuple) and len(cube._traces) == 1:
        trace = cube._traces[0]
        seen = set()
        for _ in range(500):
            if not isinstance(trace, DataTrace):
                break
            identity = id(trace)
            if identity in seen:
                raise ValueError(f"{_PROCESS_ID} dry-run band trace contains a cycle")
            seen.add(identity)
            if trace._operation == "bands":
                bands = trace._arguments
                if (type(bands) is not list or len(bands) != expected_count
                        or any(type(name) is not str or not name for name in bands)):
                    raise ValueError(
                        f"{_PROCESS_ID} requires exactly {expected_count} explicitly selected input bands"
                    )
                return
            if trace._operation not in _BAND_PRESERVING_TRACE_OPERATIONS:
                break
            trace = trace.parent
        else:
            raise ValueError(f"{_PROCESS_ID} dry-run band trace exceeds 500 operations")
    _validate_input_bands(cube.metadata, expected_count)


def register_mask_weights_pushdown_boundary():
    """Keep output v selectors from becoming selectors on the source operands."""
    from openeo_driver.dry_run import PROPAGATION_RULES

    rules = [rule for rule in PROPAGATION_RULES if rule.constraint_key == "bands"]
    if len(rules) != 1:
        raise RuntimeError("Pinned driver lacks the unique band pushdown rule")
    if _PROCESS_ID not in rules[0].blockers:
        rules[0].blockers.append(_PROCESS_ID)


def local_ee_mask_weights(args, env):
    """Return the singleton `v` schema or dispatch the exact native projection."""
    from openeo_driver.dry_run import DryRunDataCube
    from .ee_process_adapters import _apply_native, _checked_args, _driver_cube
    from gee.mask_weights_spec import decode_mask_weights_spec

    args = _checked_args(args, _PROCESS_ID, {"data", "spec"})
    cube = _driver_cube(args, _PROCESS_ID)
    text = args["spec"]
    if type(text) is not str:
        raise ValueError(f"{_PROCESS_ID} spec must be canonical JSON text")
    spec = decode_mask_weights_spec(text)
    expected_count = _input_band_count(spec)
    if isinstance(cube, DryRunDataCube):
        _validate_dry_run_input_bands(cube, expected_count)
    else:
        _validate_input_bands(cube.metadata, expected_count)
    metadata = _output_metadata(cube.metadata)
    if isinstance(cube, DryRunDataCube):
        register_mask_weights_pushdown_boundary()
        return cube._process(_PROCESS_ID, {"spec": text}, metadata=metadata)
    return _apply_native(cube, _PROCESS_ID, {"spec": text}, metadata)
