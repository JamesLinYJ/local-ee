"""Trusted bridge for the bounded integer-value raster process."""
from __future__ import annotations


_PROCESS_ID = "local_ee_integer_values"
_MAX_TRACE_NODES = 500
_MAX_TRACE_ROOTS = 500


def _band_count(spec):
    bands = {
        operand["band"]
        for operand in spec["operands"]
        if set(operand) == {"band"}
    }
    maximum = 3 if spec["op"] in {"select", "where_select"} else 2
    if not 1 <= len(bands) <= maximum or bands != set(range(len(bands))):
        raise ValueError(
            f"{_PROCESS_ID} requires one to {maximum} contiguous ordered operand bands"
        )
    return len(bands)


def _expected_band_names(count):
    return [f"band{index}" for index in range(count)]


def _validate_actual_band_metadata(metadata, expected):
    if not metadata.has_band_dimension():
        raise ValueError(f"{_PROCESS_ID} requires an explicitly named input band dimension")
    names = metadata.band_names
    if (type(names) not in (list, tuple)
            or tuple(names) != tuple(expected)):
        joined = ", ".join(expected)
        raise ValueError(f"{_PROCESS_ID} requires ordered input bands: {joined}")


def _validate_dry_run_trace_structure(cube):
    from .ee_cube_admission import validate_cube_trace

    validate_cube_trace(cube, _PROCESS_ID, max_nodes=_MAX_TRACE_NODES,
                        max_roots=_MAX_TRACE_ROOTS)


def _output_metadata(metadata):
    if not metadata.has_band_dimension():
        raise ValueError(f"{_PROCESS_ID} requires an explicitly named input band dimension")
    dimension = metadata.band_dimension.name
    return metadata.reduce_dimension(dimension).add_dimension(dimension, "v", type="bands")


def local_ee_integer_values(args, env):
    """Return pending output schema or apply the fixed actual-tile SPI.

    Dry-run validates the canonical specification and trace structure, but it
    does not validate input band count/order because the pinned driver loses
    that information across rename and merge operations. Actual cubes require
    exact compiler labels before the native SPI is called.
    """
    from openeo_driver.dry_run import DryRunDataCube
    from .ee_process_adapters import _apply_native, _checked_args, _driver_cube
    from gee.integer_values_spec import decode_integer_values_spec

    args = _checked_args(args, _PROCESS_ID, {"data", "spec"})
    cube = _driver_cube(args, _PROCESS_ID)
    spec = decode_integer_values_spec(args["spec"])
    if isinstance(cube, DryRunDataCube):
        if not cube.metadata.has_band_dimension():
            raise ValueError(f"{_PROCESS_ID} requires a band dimension")
        _band_count(spec)
        _validate_dry_run_trace_structure(cube)
    else:
        expected = _expected_band_names(_band_count(spec))
        _validate_actual_band_metadata(cube.metadata, expected)

    metadata = _output_metadata(cube.metadata)
    if isinstance(cube, DryRunDataCube):
        return cube._process_metadata(metadata)
    return _apply_native(cube, _PROCESS_ID, {"spec": args["spec"]}, metadata)
