"""Focused trusted RF feature-validation bridge contracts."""
from __future__ import annotations

import json
import types

import pytest
from openeo_driver.dry_run import DataSource, DryRunDataTracer
from openeo_driver.processgraph.registry import ENV_DRY_RUN_TRACER

from engine import ee_process_adapters as adapters
from engine import ee_rf_validation as validation
from engine import ee_rf_validation_runtime as runtime
from engine.ee_json_result import (
    PendingRuntimeTable, PendingRuntimeValue, RuntimeFeatureTable, RuntimeJsonResult,
)
from engine.ee_rf_validation_matrix import (
    PendingRfConfusionMatrix, RuntimeConfusionMatrix,
)
from engine.ee_sampling_result import PendingSampledTable, SampledFeatureTable
from engine.ee_smile_rf import PendingSmileRfModel, TrainedSmileRfModel
from ee_smile_rf_engine_helpers import install_factory, rows_text, spec
from gee.rf_validation_spec import (
    prepare_classify_spec, prepare_feature_rows, prepare_matrix_spec,
    prepare_metric_spec,
)
from gee.sampling_spec import (
    decode_sampling_spec, prepare_sampling_spec, sampling_columns,
)


def _trained_model(monkeypatch):
    spec_text = spec()
    train_calls = install_factory(monkeypatch)
    model = adapters.local_ee_train_smile_rf_rows(
        {"rows": rows_text(spec_text), "spec": spec_text}, env=None,
    )
    assert type(model) is TrainedSmileRfModel
    assert (model.training_row_count, model.class_count) == (2, 2)
    return model, train_calls


def _inline_rows(*, red=16_777_217.0, output_collision=False):
    properties = {
        "truth": 1, "red": red, "nir": 0.5, "note": "preserve me",
    }
    if output_collision:
        properties["prediction"] = 0
    return prepare_feature_rows({"type": "FeatureCollection", "features": [{
        "type": "Feature", "id": "kept-feature-id",
        "geometry": {"type": "Point", "coordinates": [4.25, 5.5]},
        "properties": properties,
    }]})


def _predict_stub(monkeypatch, labels=(1,)):
    calls = []

    def predict(java_model, text):
        value = json.loads(text)
        calls.append((java_model, text, value))
        return json.dumps(
            {"version": 1, "predictions": list(labels)},
            sort_keys=True, separators=(",", ":"),
        )

    monkeypatch.setattr(runtime, "_predict_jvm_rows", predict)
    return calls


def _sampled_table(*, prior_work=0, long_property=0, empty=False):
    long_value = "p" * long_property
    regions = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": f"region-{label}",
         "geometry": {"type": "Point", "coordinates": [label + 1, 2]},
         "properties": {"truth": label, "plot": long_value}}
        for label in (0, 1)
    ]}
    sample_spec = prepare_sampling_spec(
        regions, ["red", "nir"], properties=["truth", "plot"], geometries=True,
    )
    decoded = decode_sampling_spec(sample_spec)
    features = [] if empty else [{
        "type": "Feature", "id": f"f{index}_r0_c0",
        "geometry": {"type": "Point", "coordinates": [index + 1.25, 2.5]},
        "properties": {"truth": index, "plot": long_value,
                       "red": 0.25 + index, "nir": 2.5 + index},
    } for index in (0, 1)]
    table = SampledFeatureTable(
        {"type": "FeatureCollection", "features": features},
        sampling_columns(decoded),
    )
    table.sample_spec = sample_spec
    table.sample_spec_verified = True
    table.sample_operations = ()
    table.sample_operation_work = prior_work
    table.traces = ()
    table.data_tracer = None
    return table


def _classify_spec(*, output="prediction", extra="note"):
    return prepare_classify_spec(output, [
        "system:index", "truth", "red", "nir", extra, output, ".geo",
    ])


def test_inline_classification_uses_real_model_boundary_and_preserves_feature_shape(monkeypatch):
    model, _ = _trained_model(monkeypatch)
    calls = _predict_stub(monkeypatch)
    rows = _inline_rows()
    headers = ["system:index", "truth", "red", "nir", "note", "prediction", ".geo"]

    result = validation.local_ee_smile_rf_classify_rows({
        "rows": rows, "spec": _classify_spec(), "model": model,
    }, env=None)

    assert type(result) is RuntimeFeatureTable
    assert result.columns == headers
    feature = result.data["features"][0]
    assert feature["id"] == "kept-feature-id"
    assert feature["geometry"] == {"type": "Point", "coordinates": [4.25, 5.5]}
    assert feature["properties"] == {
        "truth": 1, "red": 16_777_217.0, "nir": 0.5,
        "note": "preserve me", "prediction": 1,
    }
    assert calls[0][0] is model._java_model
    assert calls[0][2]["rows"] == [[16_777_217.0, 0.5]]
    assert calls[0][1] == json.dumps(
        {"version": 1, "rows": [[16_777_217.0, 0.5]]},
        sort_keys=True, separators=(",", ":"),
    )
    result.format = "CSV"
    assert result.create_flask_response().get_data(as_text=True).splitlines()[0] == ",".join(headers)


def test_sample_classification_rechecks_a_near_cap_prior_in_a_fresh_sample_budget(monkeypatch):
    model, _ = _trained_model(monkeypatch)
    calls = _predict_stub(monkeypatch, labels=(0, 1))
    # The verified origin text is several KB, while prior table operations are
    # already just below their independent 50k limit. Rechecking must be
    # charged to the RF operation's 150k budget, not that completed limit.
    table = _sampled_table(prior_work=49_900, long_property=1_800)
    assert len(table.sample_spec.encode("utf-8")) > 1_000
    classify = prepare_classify_spec("prediction", [
        "system:index", "truth", "plot", "red", "nir", "prediction", ".geo",
    ])

    result = validation.local_ee_smile_rf_classify_samples({
        "data": table, "spec": classify, "model": model,
    }, env=None)

    assert type(result) is RuntimeFeatureTable
    assert result.columns == [
        "system:index", "truth", "plot", "red", "nir", "prediction", ".geo",
    ]
    assert [f["properties"]["prediction"] for f in result.data["features"]] == [0, 1]
    assert result.data["features"][0]["properties"]["plot"] == "p" * 1_800
    assert len(calls) == 1


@pytest.mark.parametrize("value", [None, True, 2**53 + 1])
def test_inline_classification_rejects_invalid_numeric_domain_before_jvm(monkeypatch, value):
    model, _ = _trained_model(monkeypatch)
    calls = _predict_stub(monkeypatch)
    with pytest.raises(ValueError, match="numeric|classifier property"):
        validation.local_ee_smile_rf_classify_rows({
            "rows": _inline_rows(red=value), "spec": _classify_spec(), "model": model,
        }, env=None)
    assert calls == []


def test_inline_classification_rejects_existing_prediction_property_before_jvm(monkeypatch):
    model, _ = _trained_model(monkeypatch)
    calls = _predict_stub(monkeypatch)
    with pytest.raises(ValueError, match="already exists"):
        validation.local_ee_smile_rf_classify_rows({
            "rows": _inline_rows(output_collision=True),
            "spec": _classify_spec(), "model": model,
        }, env=None)
    assert calls == []


def test_classified_table_error_matrix_and_static_metrics_share_existing_math(monkeypatch):
    model, _ = _trained_model(monkeypatch)
    _predict_stub(monkeypatch, labels=(1,))
    classified = validation.local_ee_smile_rf_classify_rows({
        "rows": _inline_rows(red=1.25), "spec": _classify_spec(), "model": model,
    }, env=None)
    matrix = validation.local_ee_error_matrix({
        "data": classified,
        "spec": prepare_matrix_spec("truth", "prediction", [0, 1]),
    }, env=None)
    value = validation.local_ee_confusion_value({
        "data": matrix, "spec": prepare_metric_spec("accuracy"),
    }, env=None)
    assert type(matrix) is RuntimeConfusionMatrix
    assert type(value) is RuntimeJsonResult
    assert value.create_flask_response().get_json() == 1.0


@pytest.mark.parametrize("actual", [None, True, 1.5, 2**53 + 1])
def test_runtime_error_matrix_rejects_null_boolean_fractional_and_inexact_labels(actual):
    table = RuntimeFeatureTable({"type": "FeatureCollection", "features": [{
        "type": "Feature", "id": "one", "geometry": None,
        "properties": {"truth": actual, "classification": 0},
    }]}, ["system:index", "truth", "classification", ".geo"])
    with pytest.raises(ValueError, match="labels|null"):
        validation.local_ee_error_matrix({
            "data": table,
            "spec": prepare_matrix_spec("truth", "classification", [0, 1]),
        }, env=None)


def test_known_empty_runtime_table_accepts_explicit_order_but_not_inferred_order():
    empty = RuntimeFeatureTable(
        {"type": "FeatureCollection", "features": []},
        ["system:index", "prediction", ".geo"],
    )
    matrix = validation.local_ee_error_matrix({
        "data": empty,
        "spec": prepare_matrix_spec("truth", "classification", [0, 1]),
    }, env=None)
    result = validation.local_ee_confusion_value({
        "data": matrix, "spec": prepare_metric_spec("array"),
    }, env=None)
    assert result.create_flask_response().get_json() == [[0, 0], [0, 0]]
    with pytest.raises(ValueError, match="explicit order"):
        validation.local_ee_error_matrix({
            "data": empty,
            "spec": prepare_matrix_spec("truth", "classification"),
        }, env=None)


def test_empty_sample_classification_keeps_declared_schema_and_yields_explicit_zero_matrix(monkeypatch):
    model, _ = _trained_model(monkeypatch)
    calls = _predict_stub(monkeypatch, labels=())
    table = _sampled_table(empty=True)
    classify = prepare_classify_spec("prediction", [
        "system:index", "truth", "plot", "red", "nir", "prediction", ".geo",
    ])
    classified = validation.local_ee_smile_rf_classify_samples({
        "data": table, "spec": classify, "model": model,
    }, env=None)
    matrix = validation.local_ee_error_matrix({
        "data": classified,
        "spec": prepare_matrix_spec("truth", "prediction", [0, 1]),
    }, env=None)
    value = validation.local_ee_confusion_value({
        "data": matrix, "spec": prepare_metric_spec("array"),
    }, env=None)
    assert classified.row_count == 0
    assert classified.columns == [
        "system:index", "truth", "plot", "red", "nir", "prediction", ".geo",
    ]
    assert len(calls) == 1 and calls[0][2]["rows"] == []
    assert value.create_flask_response().get_json() == [[0, 0], [0, 0]]


def test_native_training_resubstitution_matrix_is_revalidated_and_accessed(monkeypatch):
    model, _ = _trained_model(monkeypatch)
    calls = []

    def confusion(java_model):
        calls.append(java_model)
        return '{"matrix":[[1,0],[0,1]],"order":[0,1],"version":1}'

    monkeypatch.setattr(validation, "_confusion_jvm", confusion)
    matrix = validation.local_ee_smile_rf_confusion({"model": model}, env=None)
    result = validation.local_ee_confusion_value({
        "data": matrix, "spec": prepare_metric_spec("accuracy"),
    }, env=None)
    assert calls == [model._java_model]
    assert result.create_flask_response().get_json() == 1.0

    for bad in (
        '{"matrix":[[1,0],[0,0]],"order":[0,1],"version":1}',
        '{"matrix":[[1,0],[0,1]],"order":[1,0],"version":1}',
    ):
        monkeypatch.setattr(validation, "_confusion_jvm", lambda _java, text=bad: text)
        with pytest.raises(ValueError):
            validation.local_ee_smile_rf_confusion({"model": model}, env=None)


def test_pending_classification_confusion_and_metric_keep_traces_without_predictions(monkeypatch):
    tracer = DryRunDataTracer()
    trace = tracer.add_trace(DataSource("load_collection", {"id": "training"}))
    spec_text = spec()
    factory_calls = install_factory(monkeypatch)
    model = PendingSmileRfModel(
        ("red", "nir"), "landcover", (trace,), tracer, spec_text,
    )
    predict_calls = _predict_stub(monkeypatch)
    matrix_calls = []
    monkeypatch.setattr(validation, "_confusion_jvm", lambda *_: matrix_calls.append(True))
    table = validation.local_ee_smile_rf_classify_rows({
        "rows": _inline_rows(), "spec": _classify_spec(), "model": model,
    }, {ENV_DRY_RUN_TRACER: tracer})
    matrix = validation.local_ee_smile_rf_confusion(
        {"model": model}, {ENV_DRY_RUN_TRACER: tracer},
    )
    evaluated = validation.local_ee_error_matrix({
        "data": table,
        "spec": prepare_matrix_spec("truth", "prediction", [0, 1]),
    }, {ENV_DRY_RUN_TRACER: tracer})
    value = validation.local_ee_confusion_value({
        "data": evaluated, "spec": prepare_metric_spec("accuracy"),
    }, {ENV_DRY_RUN_TRACER: tracer})

    assert type(table) is PendingRuntimeTable
    assert table.columns == tuple(_classify_spec_columns())
    assert type(matrix) is PendingRfConfusionMatrix
    assert table.traces == evaluated.traces == value.traces == (trace,)
    assert type(value) is PendingRuntimeValue and value.traces == (trace,)
    assert table.data_tracer is matrix.data_tracer is value.data_tracer is tracer
    assert not hasattr(table, "data") and not hasattr(matrix, "matrix") and not hasattr(value, "value")
    assert factory_calls == [] and predict_calls == [] and matrix_calls == []

    with pytest.raises(ValueError, match="Unsupported runtime ConfusionMatrix"):
        validation.local_ee_confusion_value({"data": matrix, "spec": "{}"}, {
            ENV_DRY_RUN_TRACER: tracer,
        })


def _classify_spec_columns():
    return ["system:index", "truth", "red", "nir", "note", "prediction", ".geo"]


def test_upstream_save_result_keeps_pending_runtime_value_and_never_writes(tmp_path, monkeypatch):
    from openeo_driver.processgraph.evaluator import convert_node
    from openeo_driver.processgraph.process_implementations.io import save_result
    from openeo_driver.processgraph.registry import ENV_SAVE_RESULT
    from openeo_driver.processes import ProcessRegistry
    from openeo_driver.utils import EvalEnv

    from gee.sampling_spec import sampling_columns

    sample_spec = prepare_sampling_spec({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]},
         "properties": {"truth": label}}
        for label in (0, 1)
    ]}, ["red", "nir"], properties=["truth"])
    tracer = DryRunDataTracer()
    source = tracer.add_trace(DataSource("load_collection", {"id": "train"}))
    pending_table = PendingSampledTable(
        tuple(sampling_columns(decode_sampling_spec(sample_spec))), sample_spec,
        traces=(source,), data_tracer=tracer,
    )
    pending_table.sample_spec_verified = True
    pending_table.sample_operations = ()
    pending_table.sample_operation_work = 0
    training_spec = spec(class_property="truth")
    factory_calls = install_factory(monkeypatch)
    registry = ProcessRegistry(argument_names=["args", "env"])
    for handler in (
        adapters.local_ee_train_smile_rf_samples,
        validation.local_ee_smile_rf_confusion,
        validation.local_ee_confusion_value,
        save_result,
    ):
        registry.add_hidden(handler)
    backend = types.SimpleNamespace(
        processing=types.SimpleNamespace(get_process_registry=lambda api_version: registry),
        summarize_exception=lambda _error: None,
    )
    saved_results = []
    env = EvalEnv({
        "backend_implementation": backend,
        "version": "1.2.0", "openeo_api_version": "1.2.0", "node_caching": False,
        ENV_DRY_RUN_TRACER: tracer, ENV_SAVE_RESULT: saved_results,
    })
    model_node = {"process_id": "local_ee_train_smile_rf_samples", "arguments": {
        "data": pending_table, "spec": training_spec,
    }}
    matrix_node = {"process_id": "local_ee_smile_rf_confusion", "arguments": {
        "model": model_node,
    }}
    value_node = {"process_id": "local_ee_confusion_value", "arguments": {
        "data": matrix_node, "spec": prepare_metric_spec("accuracy"),
    }}
    graph = {"process_id": "save_result", "arguments": {
        "data": value_node, "format": "JSON",
    }}

    result = convert_node(graph, env=env)

    assert type(result) is PendingRuntimeValue
    assert saved_results == [result]
    assert result.traces == (source,)
    assert result.data_tracer is tracer
    assert factory_calls == []
    assert tracer.get_source_constraints()[0][0].process_id == "load_collection"
    with pytest.raises(ValueError, match="cannot be written"):
        result.write_assets(tmp_path)
    with pytest.raises(ValueError, match="cannot be serialized"):
        result.create_flask_response()
    assert list(tmp_path.iterdir()) == []
