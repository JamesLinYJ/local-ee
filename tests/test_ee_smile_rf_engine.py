"""Trusted Smile RF bridge contracts; Java-object stubs are not JVM evidence."""
from __future__ import annotations

import json

import pytest
from openeo_driver.datacube import DriverDataCube
from openeo_driver.dry_run import DataSource, DryRunDataTracer
from openeo_driver.processgraph.registry import ENV_DRY_RUN_TRACER

from engine import ee_process_adapters as adapters
from engine.ee_sampling_result import PendingSampledTable
from engine.ee_smile_rf import (
    PendingSmileRfModel,
    TrainedSmileRfModel,
    _trained_model,
)
from ee_smile_rf_engine_helpers import (
    JavaObjectStub,
    dry_cube as _dry_cube,
    install_factory as _install_factory,
    jvm_model as _jvm_model,
    metadata as _metadata,
    rows_text as _rows_text,
    sample_table as _sample_table,
    spec as _spec,
)


def test_static_rows_train_with_exact_canonical_strings_and_trusted_proxy(monkeypatch):
    spec_text = _spec()
    rows_text = _rows_text(spec_text)
    calls = _install_factory(monkeypatch)

    model = adapters.local_ee_train_smile_rf_rows(
        {"rows": rows_text, "spec": spec_text}, env=None,
    )

    assert type(model) is TrainedSmileRfModel
    assert model.schema == ("red", "nir")
    assert model.class_property == "landcover"
    assert model.spec == spec_text
    assert type(model._java_model) is JavaObjectStub
    assert calls == [(spec_text, rows_text)]


def test_static_rows_dry_run_validates_but_never_calls_factory(monkeypatch):
    spec_text = _spec()
    rows_text = _rows_text(spec_text)
    tracer = DryRunDataTracer()
    calls = _install_factory(monkeypatch)

    model = adapters.local_ee_train_smile_rf_rows(
        {"rows": rows_text, "spec": spec_text},
        {ENV_DRY_RUN_TRACER: tracer},
    )

    assert type(model) is PendingSmileRfModel
    assert model.schema == ("red", "nir")
    assert model.class_property == "landcover"
    assert model.spec == spec_text
    assert model.data_tracer is tracer
    assert model.traces == ()
    assert not hasattr(model, "rows")
    assert not hasattr(model, "centers")
    assert calls == []


def test_actual_samples_normalize_integer_float_labels_and_train_exact_matrix(monkeypatch):
    spec_text = _spec()
    calls = _install_factory(monkeypatch)

    model = adapters.local_ee_train_smile_rf_samples(
        {"data": _sample_table(), "spec": spec_text}, env=None,
    )

    assert type(model) is TrainedSmileRfModel
    assert len(calls) == 1
    assert calls[0][0] == spec_text
    assert json.loads(calls[0][1]) == {
        "version": 1,
        "rows": [[0, [0.25, 2]], [1, [1.25, 3]]],
    }


def test_pending_sample_training_and_prediction_preserve_schema_trace_and_tracer(monkeypatch):
    tracer = DryRunDataTracer()
    training_trace = tracer.add_trace(DataSource("load_collection", {"id": "train"}))
    pending_table = PendingSampledTable(
        columns=("system:index", "landcover", "red", "nir", ".geo"),
        sample_spec="{}", traces=(training_trace,), data_tracer=tracer,
    )
    spec_text = _spec()
    calls = _install_factory(monkeypatch)

    model = adapters.local_ee_train_smile_rf_samples(
        {"data": pending_table, "spec": spec_text},
        {ENV_DRY_RUN_TRACER: tracer},
    )
    cube = _dry_cube(tracer=tracer)
    result = adapters.local_ee_smile_rf({"data": cube, "model": model}, env=None)

    assert type(model) is PendingSmileRfModel
    assert result.metadata.band_names == ["v"]
    assert result.metadata.dimension_names() == cube.metadata.dimension_names()
    assert result.metadata.spatial_dimensions == cube.metadata.spatial_dimensions
    assert result.metadata.temporal_dimension.extent == cube.metadata.temporal_dimension.extent
    assert result._data_tracer is tracer
    assert training_trace in result._traces
    assert cube._traces[0] in result._traces
    assert calls == []


def test_pending_sample_requires_same_dry_run_tracer(monkeypatch):
    sample_tracer, other_tracer = DryRunDataTracer(), DryRunDataTracer()
    source = sample_tracer.add_trace(DataSource("load_collection", {"id": "train"}))
    table = PendingSampledTable(
        ("system:index", "landcover", "red", "nir", ".geo"),
        "{}", (source,), sample_tracer,
    )
    with pytest.raises(ValueError, match="original dry-run tracer"):
        adapters.local_ee_train_smile_rf_samples(
            {"data": table, "spec": _spec()}, {ENV_DRY_RUN_TRACER: other_tracer},
        )
    assert source in table.traces


@pytest.mark.parametrize("value", [{"schema": ["red", "nir"]}, b"model", "path/to/model"])
def test_predictor_rejects_untrusted_dictionary_bytes_and_paths(value):
    with pytest.raises(ValueError, match="exact trusted trained model"):
        adapters.local_ee_smile_rf({"data": _dry_cube(), "model": value}, env=None)


def test_pending_models_are_dry_run_only_and_require_matching_cube_schema():
    tracer = DryRunDataTracer()
    pending = PendingSmileRfModel(("red", "nir"), "landcover", (), tracer, _spec())
    with pytest.raises(ValueError, match="cannot be used for actual execution"):
        adapters.local_ee_smile_rf(
            {"data": DriverDataCube(metadata=_metadata()), "model": pending}, env=None,
        )
    with pytest.raises(ValueError, match="schema names and order"):
        adapters.local_ee_smile_rf(
            {"data": _dry_cube(tracer=tracer, names=("nir", "red")), "model": pending}, env=None,
        )
    with pytest.raises(ValueError, match="belong to this dry run"):
        adapters.local_ee_smile_rf(
            {"data": _dry_cube(), "model": pending}, env=None,
        )


def test_actual_predictor_forwards_only_java_model_and_reduces_to_v(monkeypatch):
    spec_text = _spec()
    _install_factory(monkeypatch)
    java_model = _jvm_model()
    model = _trained_model(("red", "nir"), "landcover", spec_text, java_model)
    cube = DriverDataCube(metadata=_metadata())
    calls = []
    monkeypatch.setattr(adapters, "_apply_native", lambda *args, **kwargs: calls.append((args, kwargs)) or "native")

    result = adapters.local_ee_smile_rf({"data": cube, "model": model}, env=None)

    args, kwargs = calls[0]
    assert result == "native"
    assert args[:2] == (cube, "local_ee_smile_rf")
    assert args[2] == {"model": java_model}
    assert args[3].band_names == ["v"]
    assert args[3].spatial_dimensions == cube.metadata.spatial_dimensions
    assert not kwargs


def test_actual_model_constructor_cannot_be_used_without_factory_token():
    with pytest.raises(TypeError, match="only be created by the trusted JVM factory"):
        TrainedSmileRfModel(("red",), "label", _spec(("red",)), _jvm_model())


def test_factory_failure_is_explicit_and_never_falls_back(monkeypatch):
    _install_factory(monkeypatch, error=RuntimeError("missing pinned class"))
    with pytest.raises(RuntimeError, match="JVM factory is unavailable or failed"):
        adapters.local_ee_train_smile_rf_rows(
            {"rows": _rows_text(), "spec": _spec()}, env=None,
        )


def test_factory_must_return_a_java_object_not_a_model_payload(monkeypatch):
    _install_factory(monkeypatch, result={"model": "not trusted"})
    with pytest.raises(RuntimeError, match="did not return a JVM model object"):
        adapters.local_ee_train_smile_rf_rows(
            {"rows": _rows_text(), "spec": _spec()}, env=None,
        )


def test_model_wrapper_requires_py4j_instead_of_recognizing_a_python_stub(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "py4j", None)
    monkeypatch.setitem(sys.modules, "py4j.java_gateway", None)
    with pytest.raises(RuntimeError, match="Py4J is required"):
        _trained_model(("red",), "landcover", _spec(("red",)), object())


def test_rf_handlers_are_registered_in_both_source_controlled_registries(monkeypatch):
    class Registry:
        def __init__(self):
            self.handlers = {}

        def contains(self, name):
            return name in self.handlers

        def get_function(self, name):
            return self.handlers[name]

        def add_hidden(self, handler):
            self.handlers[handler.__name__] = handler

    import openeo_driver.processgraph.registry as registries

    first, second = Registry(), Registry()
    monkeypatch.setattr(registries, "process_registry_100", first)
    monkeypatch.setattr(registries, "process_registry_2xx", second)
    adapters.register_local_ee_processes()
    for registry in (first, second):
        assert registry.get_function("local_ee_train_smile_rf_rows") is adapters.local_ee_train_smile_rf_rows
        assert registry.get_function("local_ee_train_smile_rf_samples") is adapters.local_ee_train_smile_rf_samples
        assert registry.get_function("local_ee_smile_rf") is adapters.local_ee_smile_rf
