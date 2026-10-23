"""Trusted bridge for bounded actual pixel matrix algorithms."""
from __future__ import annotations

from gee.matrix_values_spec import (
    PROCESS_ID, decode_matrix_values_spec, matrix_input_bands, matrix_output_cells,
)


def local_ee_matrix_values(args, env):
    from openeo_driver.dry_run import DryRunDataCube
    from .ee_cube_admission import validate_cube_trace
    from .ee_process_adapters import _apply_native, _checked_args, _driver_cube

    args = _checked_args(args, PROCESS_ID, {"data", "spec"})
    cube = _driver_cube(args, PROCESS_ID)
    spec = decode_matrix_values_spec(args["spec"])
    if not cube.metadata.has_band_dimension():
        raise ValueError(f"{PROCESS_ID} requires an explicitly named band dimension")
    expected = [f"band{index}" for index in range(matrix_input_bands(spec))]
    if isinstance(cube, DryRunDataCube):
        # The pinned driver keeps stale input labels through rename/merge.
        # Only the traced structure and actual output schema are asserted now.
        validate_cube_trace(cube, PROCESS_ID)
    elif (type(cube.metadata.band_names) not in (list, tuple)
          or tuple(cube.metadata.band_names) != tuple(expected)):
        raise ValueError(f"{PROCESS_ID} requires ordered input bands: {', '.join(expected)}")

    dimension = cube.metadata.band_dimension.name
    names = [f"matrix{index}" for index in range(matrix_output_cells(spec))]
    metadata = cube.metadata.reduce_dimension(dimension).add_dimension(
        dimension, names[0], type="bands",
    )
    for name in names[1:]:
        metadata = metadata.append_band(name)
    if isinstance(cube, DryRunDataCube):
        return cube._process_metadata(metadata)
    return _apply_native(cube, PROCESS_ID, {"spec": args["spec"]}, metadata)
