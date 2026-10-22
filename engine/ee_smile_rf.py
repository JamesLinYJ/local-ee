"""Typed bridge and prediction path for trusted Smile 1.5.3 classifiers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PendingSmileRfModel:
    """Dry-run classifier schema; it deliberately contains no rows or centers."""

    schema: tuple[str, ...]
    class_property: str
    traces: tuple[Any, ...]
    data_tracer: Any = field(default=None, compare=False, repr=False)
    spec: str = ""


_MODEL_TOKEN = object()


@dataclass(frozen=True, slots=True)
class TrainedSmileRfModel:
    """Exact trusted result of the pinned JVM factory, never a wire payload."""

    schema: tuple[str, ...]
    class_property: str
    spec: str
    _java_model: Any = field(repr=False, compare=False)
    _token: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _MODEL_TOKEN:
            raise TypeError("Trained Smile models can only be created by the trusted JVM factory")
        object.__setattr__(self, "schema", tuple(self.schema))


def _trained_model(schema, class_property, spec, java_model) -> TrainedSmileRfModel:
    """Wrap only a model object returned directly by the trusted Java factory."""
    try:
        from py4j.java_gateway import JavaObject
    except ImportError as exc:
        raise RuntimeError("Py4J is required to verify the pinned Smile RF JVM model") from exc
    if not isinstance(java_model, JavaObject):
        raise RuntimeError("Pinned Smile RF factory did not return a JVM model object")
    return TrainedSmileRfModel(schema, class_property, spec, java_model, _MODEL_TOKEN)


def _train_jvm_model(spec_text: str, rows_text: str):
    """Call the installed factory; never deserialize or download model data."""
    try:
        from openeogeotrellis.utils import get_jvm

        factory = get_jvm().local.ee.smile.LocalEeSmileRfFactory
        model = factory.train(spec_text, rows_text)
    except Exception as exc:
        raise RuntimeError(
            "Pinned Smile random-forest JVM factory is unavailable or failed"
        ) from exc
    return model


def _model_metadata(cube, schema):
    metadata = cube.metadata
    if not metadata.has_band_dimension() or metadata.band_names != list(schema):
        raise ValueError("Smile RF input cube bands must match model schema names and order")
    from .ee_process_adapters import _reduce_bands_metadata

    return _reduce_bands_metadata(metadata)


def local_ee_smile_rf(args, env):
    """Predict with an opaque trusted forest or carry a pending dry-run schema."""
    from openeo_driver.dry_run import DryRunDataCube
    from .ee_process_adapters import _apply_native, _checked_args, _driver_cube

    args = _checked_args(args, "local_ee_smile_rf", {"data", "model"})
    cube = _driver_cube(args, "local_ee_smile_rf")
    model = args["model"]
    if type(model) is PendingSmileRfModel:
        if not isinstance(cube, DryRunDataCube):
            raise ValueError("A pending Smile RF model cannot be used for actual execution")
        metadata = _model_metadata(cube, model.schema)
        if model.data_tracer is not cube._data_tracer:
            raise ValueError("Pending Smile RF training traces do not belong to this dry run")
        traces = list(cube._traces)
        for trace in model.traces:
            if all(trace is not existing for existing in traces):
                traces.append(trace)
        return DryRunDataCube(
            traces=traces, data_tracer=cube._data_tracer, metadata=metadata,
        )
    if type(model) is not TrainedSmileRfModel or model._token is not _MODEL_TOKEN:
        raise ValueError("Smile RF prediction requires an exact trusted trained model")

    metadata = _model_metadata(cube, model.schema)
    if isinstance(cube, DryRunDataCube):
        return cube._process_metadata(metadata)
    return _apply_native(
        cube,
        "local_ee_smile_rf",
        {"model": model._java_model},
        metadata,
    )
