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
    """Bound and cycle-check traces without inferring dry-run input bands.

    The pinned driver leaves selected and renamed band metadata stale and
    represents merged cubes with separate traces. Dry-run therefore proves
    only the output schema and retains the dependency graph; ordered input
    labels are checked when an actual cube reaches this bridge. Each invocation
    is limited to 500 roots and 500 distinct trace nodes, including sources.
    """
    from openeo_driver.dry_run import DataSource, DataTrace

    traces = cube._traces
    if type(traces) not in (list, tuple):
        raise ValueError(f"{_PROCESS_ID} requires a valid dry-run trace list")
    if len(traces) > _MAX_TRACE_ROOTS:
        raise ValueError(
            f"{_PROCESS_ID} dry-run trace exceeds {_MAX_TRACE_ROOTS} source branches"
        )

    counted = set()
    completed = set()
    for root in traces:
        if root is None:
            raise ValueError(f"{_PROCESS_ID} dry-run trace does not reach a data source")
        trace = root
        path = set()
        while True:
            if isinstance(trace, DataSource):
                identity = id(trace)
                if identity not in counted:
                    counted.add(identity)
                    if len(counted) > _MAX_TRACE_NODES:
                        raise ValueError(
                            f"{_PROCESS_ID} dry-run trace exceeds {_MAX_TRACE_NODES} nodes"
                        )
                completed.add(identity)
                completed.update(path)
                break
            if not isinstance(trace, DataTrace):
                if trace is None:
                    raise ValueError(
                        f"{_PROCESS_ID} dry-run trace does not reach a data source"
                    )
                raise ValueError(f"{_PROCESS_ID} dry-run trace contains an unknown node")
            identity = id(trace)
            if identity in path:
                raise ValueError(f"{_PROCESS_ID} dry-run trace contains a cycle")
            if identity in completed:
                completed.update(path)
                break
            path.add(identity)
            if identity not in counted:
                counted.add(identity)
                if len(counted) > _MAX_TRACE_NODES:
                    raise ValueError(
                        f"{_PROCESS_ID} dry-run trace exceeds {_MAX_TRACE_NODES} nodes"
                    )
            trace = trace.parent


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
