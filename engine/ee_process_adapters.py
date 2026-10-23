"""Trusted Python bridge for dimension-changing local EE GeoTrellis processes."""
from __future__ import annotations

from typing import Any

# These reducers are a small fixed engine contract. The classifier additionally
# reuses the pure audited model validator in the sandbox-readable gee package.
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


def local_ee_minimum_distance(args, env):
    """Validate the exact model and preserve spatial/temporal cube metadata."""
    from openeo_driver.dry_run import DryRunDataCube
    from gee.compat.earthengine.classifier_model import model_validation_work, validate_model
    from .ee_sampling_result import PendingMinimumDistanceModel

    args = _checked_args(args, "local_ee_minimum_distance", {"data", "model"})
    cube = _driver_cube(args, "local_ee_minimum_distance")
    model = args["model"]
    if isinstance(model, PendingMinimumDistanceModel):
        if not isinstance(cube, DryRunDataCube):
            raise ValueError("A pending classifier model cannot be used for actual execution")
        if not cube.metadata.has_band_dimension() or cube.metadata.band_names != list(model.schema):
            raise ValueError("Classifier input cube bands must match pending model schema names and order")
        if model.data_tracer is not None and model.data_tracer is not cube._data_tracer:
            raise ValueError("Pending classifier training traces do not belong to this dry run")
        metadata = _reduce_bands_metadata(cube.metadata)
        traces = list(cube._traces)
        for trace in model.traces:
            if all(trace is not existing for existing in traces):
                traces.append(trace)
        return DryRunDataCube(traces=traces, data_tracer=cube._data_tracer, metadata=metadata)
    if model_validation_work(model) > 50_000:
        raise ValueError("Raster classifier model exceeds the 50000-step work budget")
    validate_model(model)
    if not cube.metadata.has_band_dimension() or cube.metadata.band_names != model["schema"]:
        raise ValueError("Classifier input cube bands must match model schema names and order")
    metadata = _reduce_bands_metadata(cube.metadata)
    if isinstance(cube, DryRunDataCube):
        return cube._process_metadata(metadata)
    return _apply_native(cube, "local_ee_minimum_distance", {"model": model}, metadata)


def local_ee_sample_regions(args, env):
    from .ee_sampling import local_ee_sample_regions as handler
    from .ee_sampling_result import PendingSampledTable, SampledFeatureTable

    table = handler(args, env)
    if type(table) is SampledFeatureTable:
        cube = args["data"]
        table.sample_spec = args["spec"]
        table.sample_spec_verified = True
        table.traces = tuple(getattr(cube, "_traces", ()))
        table.data_tracer = getattr(cube, "_data_tracer", None)
        table.sample_operations = ()
        table.sample_operation_work = 0
    elif type(table) is PendingSampledTable:
        table.sample_spec_verified = True
        table.sample_operations = ()
        table.sample_operation_work = 0
    else:
        raise ValueError("SampleRegions returned an unsupported sampled table type")
    return table


def local_ee_train_minimum_distance(args, env):
    from .ee_sampling import local_ee_train_minimum_distance as handler

    return handler(args, env)


def local_ee_remap(args, env):
    from .ee_remap import local_ee_remap as handler

    return handler(args, env)


def local_ee_sample_table_op(args, env):
    from .ee_sample_table_ops import local_ee_sample_table_op as handler

    return handler(args, env)


def local_ee_runtime_table_op(args, env):
    from .ee_runtime_table_ops import local_ee_runtime_table_op as handler

    return handler(args, env)


def local_ee_train_smile_rf_rows(args, env):
    from .ee_smile_rf_training import local_ee_train_smile_rf_rows as handler

    return handler(args, env)


def local_ee_train_smile_rf_samples(args, env):
    from .ee_smile_rf_training import local_ee_train_smile_rf_samples as handler

    return handler(args, env)


def local_ee_smile_rf_classify_rows(args, env):
    from .ee_rf_validation import local_ee_smile_rf_classify_rows as handler
    return handler(args, env)


def local_ee_smile_rf_classify_samples(args, env):
    from .ee_rf_validation import local_ee_smile_rf_classify_samples as handler
    return handler(args, env)


def local_ee_smile_rf_confusion(args, env):
    from .ee_rf_validation import local_ee_smile_rf_confusion as handler
    return handler(args, env)


def local_ee_error_matrix(args, env):
    from .ee_rf_validation import local_ee_error_matrix as handler
    return handler(args, env)


def local_ee_confusion_value(args, env):
    from .ee_rf_validation import local_ee_confusion_value as handler
    return handler(args, env)


def local_ee_smile_rf(args, env):
    from .ee_smile_rf import local_ee_smile_rf as handler

    return handler(args, env)


_HANDLERS = {
    "local_ee_drop_single_time": local_ee_drop_single_time,
    "local_ee_reduce_bands": local_ee_reduce_bands,
    "local_ee_minimum_distance": local_ee_minimum_distance,
    "local_ee_sample_regions": local_ee_sample_regions,
    "local_ee_train_minimum_distance": local_ee_train_minimum_distance,
    "local_ee_remap": local_ee_remap,
    "local_ee_sample_table_op": local_ee_sample_table_op,
    "local_ee_runtime_table_op": local_ee_runtime_table_op,
    "local_ee_train_smile_rf_rows": local_ee_train_smile_rf_rows,
    "local_ee_train_smile_rf_samples": local_ee_train_smile_rf_samples,
    "local_ee_smile_rf_classify_rows": local_ee_smile_rf_classify_rows,
    "local_ee_smile_rf_classify_samples": local_ee_smile_rf_classify_samples,
    "local_ee_smile_rf_confusion": local_ee_smile_rf_confusion,
    "local_ee_error_matrix": local_ee_error_matrix,
    "local_ee_confusion_value": local_ee_confusion_value,
    "local_ee_smile_rf": local_ee_smile_rf,
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
