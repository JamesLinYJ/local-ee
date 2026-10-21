"""Trusted Python bridge for dimension-changing local EE GeoTrellis processes."""
from __future__ import annotations

from typing import Any

# The isolated engine reads only its trusted source directory, not the API's
# package root. Keep this small wire contract in sync through the parity test.
EE_BAND_REDUCERS = frozenset({"mean", "median", "min", "max", "sum", "count", "first", "last", "sd"})


def _drop_single_time_metadata(metadata):
    """Remove the temporal dimension while retaining spatial and band metadata."""
    if not metadata.has_temporal_dimension():
        raise ValueError("local_ee_drop_single_time requires a temporal dimension")
    return metadata.reduce_dimension(metadata.temporal_dimension.name)


def _reduce_bands_metadata(metadata):
    """Return one `v` band without disturbing the other cube dimensions."""
    if not metadata.has_band_dimension():
        raise ValueError("local_ee_reduce_bands requires a band dimension")
    dimension = metadata.band_dimension.name
    return metadata.reduce_dimension(dimension).add_dimension(dimension, "v", type="bands")


def _checked_args(args, process_id: str, required: set[str]):
    from openeo_driver.processes import ProcessArgs

    args = ProcessArgs.cast(args, process_id=process_id)
    if set(args) != required:
        raise ValueError(f"{process_id} accepts exactly {sorted(required)}")
    return args


def _driver_cube(args, process_id: str):
    from openeo_driver.datacube import DriverDataCube

    cube = args.get_required("data", expected_type=DriverDataCube)
    return cube


def _apply_native(cube, process_id: str, arguments: dict[str, Any], metadata, *, target_type=None):
    """Apply an SPI process to every pyramid level and set its Python metadata."""
    import geopyspark as gps
    from openeogeotrellis.utils import get_jvm

    if target_type is not None and target_type != gps.LayerType.SPATIAL:
        raise ValueError("Only spatial output is supported by this EE bridge")
    spi = get_jvm().org.openeo.geotrelliscommon.CubeProcessRegistry
    return cube._apply_to_levels_geotrellis_rdd(
        lambda wrapped_cube, level: spi.invoke(wrapped_cube, process_id, arguments),
        metadata=metadata,
        target_type=target_type,
    )


def local_ee_drop_single_time(args, env):
    """Drop the sole time key and return a spatial cube with its bands preserved."""
    from openeo_driver.dry_run import DryRunDataCube

    args = _checked_args(args, "local_ee_drop_single_time", {"data"})
    cube = _driver_cube(args, "local_ee_drop_single_time")
    metadata = _drop_single_time_metadata(cube.metadata)
    if isinstance(cube, DryRunDataCube):
        return cube._process_metadata(metadata)
    import geopyspark as gps

    return _apply_native(
        cube,
        "local_ee_drop_single_time",
        {},
        metadata,
        target_type=gps.LayerType.SPATIAL,
    )


def local_ee_reduce_bands(args, env):
    """Reduce bands in source order and expose the result as the singleton `v` band."""
    from openeo_driver.dry_run import DryRunDataCube

    args = _checked_args(args, "local_ee_reduce_bands", {"data", "reducer"})
    cube = _driver_cube(args, "local_ee_reduce_bands")
    reducer = args["reducer"]
    if type(reducer) is not str or reducer not in EE_BAND_REDUCERS:
        raise ValueError("local_ee_reduce_bands requires a supported reducer name")
    metadata = _reduce_bands_metadata(cube.metadata)
    if isinstance(cube, DryRunDataCube):
        return cube._process_metadata(metadata)
    return _apply_native(
        cube,
        "local_ee_reduce_bands",
        {"reducer": reducer},
        metadata,
    )


_HANDLERS = {
    "local_ee_drop_single_time": local_ee_drop_single_time,
    "local_ee_reduce_bands": local_ee_reduce_bands,
}


def register_local_ee_processes() -> None:
    """Install only these source-controlled handlers in both openEO registries."""
    from openeo_driver.processgraph.registry import process_registry_100, process_registry_2xx

    for registry in (process_registry_100, process_registry_2xx):
        for process_id, handler in _HANDLERS.items():
            if registry.contains(process_id):
                if registry.get_function(process_id) is not handler:
                    raise RuntimeError(f"Refusing to replace an existing {process_id} handler")
                continue
            registry.add_hidden(handler)
