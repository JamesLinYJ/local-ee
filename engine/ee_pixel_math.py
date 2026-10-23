"""Trusted Python boundary for closed, actual-tile Earth Engine math operations."""
from __future__ import annotations


def _pixel_math_metadata(metadata, arity):
    if not metadata.has_band_dimension():
        raise ValueError("local_ee_pixel_math requires an explicitly named input band dimension")
    names = metadata.band_names
    expected_names = ("x",) if arity == 1 else ("x", "y")
    if (type(names) not in (list, tuple)
            or any(type(name) is not str for name in names)
            or tuple(names) != expected_names):
        joined = ", ".join(expected_names)
        raise ValueError(f"local_ee_pixel_math requires ordered input band(s): {joined}")
    dimension = metadata.band_dimension.name
    return metadata.reduce_dimension(dimension).add_dimension(dimension, "v", type="bands")


def local_ee_pixel_math(args, env):
    """Apply a fixed Float32 math operation or carry its output schema in dry-run."""
    from openeo_driver.dry_run import DryRunDataCube
    from .ee_process_adapters import _apply_native, _checked_args, _driver_cube
    from gee.pixel_math_contract import pixel_math_arity, validate_pixel_math_operation

    args = _checked_args(args, "local_ee_pixel_math", {"data", "operation"})
    operation = validate_pixel_math_operation(args["operation"])
    arity = pixel_math_arity(operation)
    cube = _driver_cube(args, "local_ee_pixel_math")
    metadata = _pixel_math_metadata(cube.metadata, arity)
    if isinstance(cube, DryRunDataCube):
        return cube._process_metadata(metadata)
    return _apply_native(cube, "local_ee_pixel_math", {"operation": operation}, metadata)
