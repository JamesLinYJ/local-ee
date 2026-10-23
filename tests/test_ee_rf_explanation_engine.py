"""Trusted native bridge and JSON-only result boundary for RF explanations."""
from __future__ import annotations

import json

import pytest
from openeo_driver.dry_run import DataSource, DryRunDataTracer
from openeo_driver.processgraph.registry import ENV_DRY_RUN_TRACER

from engine import ee_process_adapters as adapters
from engine.ee_explanation_result import PendingRFExplanationResult, RuntimeRFExplanationResult
from engine.ee_json_result import PendingRuntimeValue, RuntimeJsonResult
from engine.ee_rf_explanation import local_ee_smile_rf_explain
from engine.ee_smile_rf import PendingSmileRfModel, _trained_model
from ee_smile_rf_engine_helpers import jvm_model as _jvm_model, spec as _spec
from gee.rf_explanation_spec import prepare_explanation_spec


def _projection(schema=("signal", "constant"), trees=3, view="explanation", keys=None):
    return prepare_explanation_spec(schema, trees, view=view, keys=keys)


def _native(importance=(1.5, 0.0), trees=3, error=0.0):
    return json.dumps({"version": 1, "importance": list(importance),
                       "number_of_trees": trees, "out_of_bag_error": error})


def _model(monkeypatch, schema=("signal", "constant"), trees=3):
    from ee_smile_rf_engine_helpers import install_factory

    install_factory(monkeypatch)
    text = _spec(schema=schema, number_of_trees=trees)
    return _trained_model(schema, "landcover", text, _jvm_model(),
                          training_row_count=8, class_count=2)


def test_actual_model_explanation_calls_only_trusted_jvm_model_and_returns_owned_json(monkeypatch):
    import engine.ee_rf_explanation as bridge

    model = _model(monkeypatch)
    calls = []
    monkeypatch.setattr(bridge, "_explain_jvm", lambda java_model: calls.append(java_model) or _native())
    spec = _projection()

    result = adapters.local_ee_smile_rf_explain({"model": model, "spec": spec}, env=None)

    assert type(result) is RuntimeRFExplanationResult
    assert result.explanation_spec == spec
    assert json.loads(result.create_flask_response().get_data(as_text=True)) == {
        "importance": {"signal": 1.5, "constant": 0.0},
        "numberOfTrees": 3, "outOfBagErrorEstimate": 0.0,
    }
    assert calls == [model._java_model]


def test_model_projection_schema_and_tree_count_must_match_before_jvm(monkeypatch):
    import engine.ee_rf_explanation as bridge

    model = _model(monkeypatch)
    calls = []
    monkeypatch.setattr(bridge, "_explain_jvm", lambda java_model: calls.append(java_model) or _native())
    with pytest.raises(ValueError, match="schema or tree count"):
        adapters.local_ee_smile_rf_explain(
            {"model": model, "spec": _projection(trees=2)}, env=None,
        )
    with pytest.raises(ValueError, match="exactly"):
        adapters.local_ee_smile_rf_explain(
            {"model": model, "spec": _projection(), "extra": True}, env=None,
        )
    assert calls == []


def test_actual_model_requires_validated_training_metadata_before_jvm(monkeypatch):
    import engine.ee_rf_explanation as bridge

    from ee_smile_rf_engine_helpers import install_factory

    install_factory(monkeypatch)
    model = _trained_model(
        ("signal", "constant"), "landcover",
        _spec(schema=("signal", "constant"), number_of_trees=3), _jvm_model(),
    )
    calls = []
    monkeypatch.setattr(bridge, "_explain_jvm", lambda java_model: calls.append(java_model) or _native())
    with pytest.raises(ValueError, match="validated training-row/class metadata"):
        adapters.local_ee_smile_rf_explain(
            {"model": model, "spec": _projection()}, env=None,
        )
    assert calls == []


def test_dry_run_preserves_training_trace_and_same_tracer_without_values(monkeypatch):
    import engine.ee_rf_explanation as bridge

    tracer = DryRunDataTracer()
    training = tracer.add_trace(DataSource("load_collection", {"id": "training"}))
    trainer_spec = _spec(schema=("signal", "constant"), number_of_trees=3)
    model = PendingSmileRfModel(
        ("signal", "constant"), "landcover", (training,), tracer, trainer_spec,
    )
    calls = []
    monkeypatch.setattr(bridge, "_explain_jvm", lambda *_: calls.append(True))

    result = adapters.local_ee_smile_rf_explain(
        {"model": model, "spec": _projection()}, {ENV_DRY_RUN_TRACER: tracer},
    )

    assert type(result) is PendingRFExplanationResult
    assert isinstance(result, PendingRuntimeValue)
    assert result.explanation_spec == _projection()
    assert result.traces == (training,)
    assert result.data_tracer is tracer
    assert not hasattr(result, "value")
    assert calls == []


def test_pending_model_rejects_another_dry_run_tracer():
    source_tracer, other_tracer = DryRunDataTracer(), DryRunDataTracer()
    model = PendingSmileRfModel(
        ("signal", "constant"), "landcover", (), source_tracer,
        _spec(schema=("signal", "constant"), number_of_trees=3),
    )
    with pytest.raises(ValueError, match="does not belong to this dry run"):
        local_ee_smile_rf_explain(
            {"model": model, "spec": _projection()},
            {ENV_DRY_RUN_TRACER: other_tracer},
        )


@pytest.mark.parametrize("model", [{"schema": ["signal", "constant"]}, b"model", "model.json"])
def test_explanation_rejects_models_without_the_exact_factory_token(model):
    with pytest.raises(ValueError, match="direct trusted Smile RF trainer model"):
        local_ee_smile_rf_explain({"model": model, "spec": _projection()}, env=None)


def test_native_forgery_or_unbounded_response_never_becomes_public_value(monkeypatch):
    import engine.ee_rf_explanation as bridge

    model = _model(monkeypatch)
    for response in (
        '{"version":1,"importance":[0,0],"number_of_trees":2,"out_of_bag_error":0.0}',
        '{"version":1,"importance":[0,0],"importance":[0,0],"number_of_trees":3,"out_of_bag_error":0.0}',
        "x" * 4097,
    ):
        monkeypatch.setattr(bridge, "_explain_jvm", lambda _model, response=response: response)
        with pytest.raises(ValueError):
            adapters.local_ee_smile_rf_explain(
                {"model": model, "spec": _projection()}, env=None,
            )


def test_rf_explanation_does_not_relax_numeric_matrix_json_boundary():
    with pytest.raises(ValueError, match="finite numeric value"):
        RuntimeJsonResult({"importance": {"signal": 1.5}, "numberOfTrees": 3,
                           "outOfBagErrorEstimate": 0.0})


def test_handler_is_registered_in_both_source_controlled_registries(monkeypatch):
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
        assert registry.get_function("local_ee_smile_rf_explain") is adapters.local_ee_smile_rf_explain


def test_precharge_precedes_spec_parsing_and_jvm_call(monkeypatch):
    import engine.ee_rf_explanation as bridge
    import gee.rf_explanation_spec as spec_module
    import gee.smile_rf_spec as trainer_module

    model = _model(monkeypatch)
    projection_text = _projection()
    events = []
    original_precharge = bridge._precharge
    original_projection_decode = spec_module.decode_explanation_spec
    original_trainer_decode = trainer_module.decode_rf_spec

    def precharge(*args):
        result = original_precharge(*args)
        events.append("precharge")
        return result

    def projection_decode(*args):
        assert "precharge" in events
        events.append("projection")
        return original_projection_decode(*args)

    def trainer_decode(*args):
        assert "precharge" in events
        events.append("trainer")
        return original_trainer_decode(*args)

    def explain(java_model):
        assert "precharge" in events
        events.append("jvm")
        return _native()

    monkeypatch.setattr(bridge, "_precharge", precharge)
    monkeypatch.setattr(spec_module, "decode_explanation_spec", projection_decode)
    monkeypatch.setattr(trainer_module, "decode_rf_spec", trainer_decode)
    monkeypatch.setattr(bridge, "_explain_jvm", explain)

    adapters.local_ee_smile_rf_explain(
        {"model": model, "spec": projection_text}, env=None,
    )

    assert events.index("precharge") < events.index("projection")
    assert events.index("precharge") < events.index("trainer")
    assert events.index("precharge") < events.index("jvm")
