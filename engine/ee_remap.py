"""Trusted bridge for the bounded one-band Earth Engine remap process."""
from __future__ import annotations


def _remapped_metadata(metadata):
    if not metadata.has_band_dimension():
        raise ValueError("local_ee_remap requires an explicitly named source band")
    bands = metadata.band_names
    if (type(bands) not in (list, tuple) or len(bands) != 1
            or type(bands[0]) is not str or not bands[0]):
        raise ValueError("local_ee_remap requires exactly one named source band")
    dimension = metadata.band_dimension.name
    return metadata.reduce_dimension(dimension).add_dimension(dimension, "v", type="bands")


def local_ee_remap(args, env):
    """Apply the native precision-preserving remap or carry its dry-run schema."""
    from openeo_driver.dry_run import DryRunDataCube
    from .ee_process_adapters import _apply_native, _checked_args, _driver_cube
    from gee.remap_spec import decode_remap_spec

    args = _checked_args(args, "local_ee_remap", {"data", "spec"})
    cube = _driver_cube(args, "local_ee_remap")
    text = args["spec"]
    if type(text) is not str:
        raise ValueError("local_ee_remap spec must be canonical JSON text")
    # The shared decoder enforces the exact fields, canonical representation,
    # numeric domain and the 0..256 mapping bound before anything reaches SPI.
    decode_remap_spec(text)
    metadata = _remapped_metadata(cube.metadata)
    if isinstance(cube, DryRunDataCube):
        return cube._process_metadata(metadata)
    # The native provider emits a single Float64 `v` band with NaN NoData.
    # Do not downcast or alter time, properties, footprint, or grid metadata.
    return _apply_native(cube, "local_ee_remap", {"spec": text}, metadata)
