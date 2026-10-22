"""Typed DAG producers, opaque model/matrix consumers and narrow JSON sinks."""
import copy

import pytest

from gee.graph import validate
from gee.rf_validation_processes import (
    CLASSIFY_ROWS, CLASSIFY_SAMPLES, CONFUSION_VALUE, ERROR_MATRIX, RF_CONFUSION,
)
from gee.rf_validation_spec import (
    prepare_classify_spec, prepare_feature_rows, prepare_matrix_spec,
    prepare_metric_spec,
)
from gee.smile_rf_spec import decode_rf_spec, prepare_rf_parameters, prepare_rf_rows, prepare_rf_spec


def program(result="value"):
    spec = prepare_rf_spec(prepare_rf_parameters(3), ["x"], "truth")
    rows = prepare_rf_rows([[0, [0]], [1, [10]]], decode_rf_spec(spec))
    data = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": None, "properties": {"x": 1, "truth": 0},
    }]}
    nodes = {
        "model": {"process_id": "local_ee_train_smile_rf_rows", "arguments": {"rows": rows, "spec": spec}},
        "table": {"process_id": CLASSIFY_ROWS, "arguments": {
            "rows": prepare_feature_rows(data), "model": {"from_node": "model"},
            "spec": prepare_classify_spec("prediction", ["system:index", "x", "truth", "prediction", ".geo"])}},
        "matrix": {"process_id": ERROR_MATRIX, "arguments": {
            "data": {"from_node": "table"}, "spec": prepare_matrix_spec("truth", "prediction", [0, 1])}},
        "training": {"process_id": RF_CONFUSION, "arguments": {"model": {"from_node": "model"}}},
        "value": {"process_id": CONFUSION_VALUE, "arguments": {
            "data": {"from_node": "matrix"}, "spec": prepare_metric_spec("accuracy")}},
    }
    nodes[result]["result"] = True
    return nodes


def test_runtime_value_table_and_training_matrix_graphs_validate():
    for result in ("value", "table"):
        validate(program(result))
    nodes = program()
    nodes["value"]["arguments"]["data"] = {"from_node": "training"}
    validate(nodes)
    nodes["value"].pop("result")
    nodes["sink"] = {"process_id": "save_result", "arguments": {
        "data": {"from_node": "value"}, "format": "JSON"}, "result": True}
    validate(nodes)


@pytest.mark.parametrize("source,format", [("table", "JSON"), ("table", "CSV"), ("value", "JSON")])
def test_only_typed_results_support_direct_export(source, format):
    nodes = program(source)
    nodes[source].pop("result")
    nodes["sink"] = {"process_id": "save_result", "arguments": {
        "data": {"from_node": source}, "format": format}, "result": True}
    validate(nodes)


@pytest.mark.parametrize("source,format", [
    ("model", "JSON"), ("matrix", "JSON"), ("training", "JSON"),
    ("table", "GTiff"), ("value", "CSV"),
])
def test_opaque_or_wrong_result_format_rejected(source, format):
    nodes = program()
    nodes["value"].pop("result")
    nodes["sink"] = {"process_id": "save_result", "arguments": {
        "data": {"from_node": source}, "format": format}, "result": True}
    with pytest.raises(ValueError):
        validate(nodes)


@pytest.mark.parametrize("source", ["model", "matrix", "training", "table", "value"])
@pytest.mark.parametrize("nested", [False, True])
def test_typed_values_cannot_escape_into_generic_arithmetic(source, nested):
    nodes = program()
    nodes["value"].pop("result")
    ref = {"from_node": source}
    nodes["escape"] = {"process_id": "add", "arguments": {
        "x": [ref] if nested else ref, "y": 1}, "result": True}
    with pytest.raises(ValueError):
        validate(nodes)


def test_model_role_and_real_schema_columns_cannot_be_forged():
    nodes = program()
    nodes["table"]["arguments"]["model"] = {"from_node": "matrix"}
    with pytest.raises(ValueError):
        validate(nodes)
    nodes = program()
    nodes["matrix"]["arguments"]["spec"] = prepare_matrix_spec("missing", "prediction")
    with pytest.raises(ValueError):
        validate(nodes)
    nodes = program()
    nodes["table"]["arguments"]["spec"] = prepare_classify_spec(
        "prediction", ["system:index", "truth", "prediction", ".geo"])
    with pytest.raises(ValueError):
        validate(nodes)


def test_generic_json_output_stays_unavailable_and_matrix_cannot_be_direct_result():
    nodes = {"value": {"process_id": "add", "arguments": {"x": 1, "y": 2}},
             "sink": {"process_id": "save_result", "arguments": {
                 "data": {"from_node": "value"}, "format": "JSON"}, "result": True}}
    with pytest.raises(ValueError):
        validate(nodes)
    with pytest.raises(ValueError):
        validate(program("matrix"))


def test_canonical_feature_strings_are_opaque_and_callback_scope_is_independent():
    nodes = program()
    data = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": None,
        "properties": {"x": 1, "truth": 0, "from_node": "model", "process_id": "data"},
    }]}
    nodes["table"]["arguments"]["rows"] = prepare_feature_rows(data)
    nodes["table"]["arguments"]["spec"] = prepare_classify_spec("prediction", [
        "system:index", "x", "truth", "from_node", "process_id", "prediction", ".geo"])
    nodes["load"] = {"process_id": "load_collection", "arguments": {"id": "local"}}
    nodes["callback"] = {"process_id": "apply", "arguments": {
        "data": {"from_node": "load"}, "process": {"process_graph": {
            "model": {"process_id": "add", "arguments": {"x": 1, "y": 2}},
            "sum": {"process_id": "add", "arguments": {"x": {"from_node": "model"}, "y": 1}, "result": True},
        }}}}
    validate(nodes)
