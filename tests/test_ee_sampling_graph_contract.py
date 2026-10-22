"""Process-graph type edges for sampled tables and trained models."""
from __future__ import annotations

import json

import pytest

from ee_sampling_contract_helpers import _valid_sampling_graph
from gee.graph import validate
from gee.sampling_spec import decode_training_spec, encode_spec


@pytest.mark.parametrize("training, message", [
    ({"version": True, "metric": "euclidean", "class_property": "label", "schema": ["red"]}, "version"),
    ({"version": 1, "metric": "euclidean", "class_property": "label", "schema": ["red"], "other": 0}, "fields or version"),
    ({"version": 1, "metric": "chebyshev", "class_property": "label", "schema": ["red"]}, "metric"),
    ({"version": 1, "metric": "euclidean", "class_property": "label", "schema": []}, "Training schema"),
    ({"version": 1, "metric": "euclidean", "class_property": "label", "schema": [f"b{i}" for i in range(9)]}, "Training schema"),
    ({"version": 1, "metric": "euclidean", "class_property": "label", "schema": ["red", "red"]}, "Training schema"),
    ({"version": 1, "metric": "euclidean", "class_property": "bad.name", "schema": ["red"]}, "class_property"),
])
def test_training_spec_requires_canonical_version_metric_and_flat_schema(training, message):
    with pytest.raises(ValueError, match=message):
        decode_training_spec(encode_spec(training))


def test_training_spec_rejects_duplicate_keys_and_noncanonical_json():
    text = encode_spec({
        "version": 1,
        "metric": "euclidean",
        "class_property": "label",
        "schema": ["red"],
    })
    with pytest.raises(ValueError, match="Duplicate specification key"):
        decode_training_spec(text[:-1] + ',"version":1}')
    with pytest.raises(ValueError, match="canonical"):
        decode_training_spec(text + " ")


def test_graph_validator_accepts_sample_train_classify_and_keeps_spec_strings_as_data():
    graph = _valid_sampling_graph()
    original_sample = graph["samples"]["arguments"]["spec"]
    original_training = graph["model"]["arguments"]["spec"]

    assert validate(graph) is None
    assert graph["samples"]["arguments"]["spec"] == original_sample
    assert graph["model"]["arguments"]["spec"] == original_training
    sample_payload = json.loads(original_sample)["regions"]["features"][0]["properties"]["payload"]
    assert sample_payload["process_id"] == "also-data"
    assert json.loads(original_training)["class_property"] == "from_node"


def test_graph_validator_requires_direct_sample_producer_and_audited_model_ref():
    graph = _valid_sampling_graph()
    graph["model"]["arguments"]["data"] = {"from_node": "source"}
    with pytest.raises(ValueError, match="directly from local_ee_sample_regions"):
        validate(graph)

    graph = _valid_sampling_graph()
    graph["classify"]["arguments"]["model"] = {"from_node": "samples"}
    with pytest.raises(ValueError, match="audited sampled-training producer"):
        validate(graph)

    graph = _valid_sampling_graph()
    graph["classify"]["arguments"]["model"] = {"from_node": "source"}
    with pytest.raises(ValueError, match="audited sampled-training producer"):
        validate(graph)


@pytest.mark.parametrize("model_reference", [
    {"from_parameter": "classifier"},
    {"from_node": "model", "metadata": "not-a-reference"},
])
def test_graph_validator_rejects_nonexclusive_dynamic_classifier_model_refs(model_reference):
    graph = _valid_sampling_graph()
    graph["classify"]["arguments"]["model"] = model_reference

    with pytest.raises(ValueError):
        validate(graph)


def test_graph_validator_rejects_sample_table_reused_as_raster_input():
    graph = _valid_sampling_graph()
    graph["sample_again"] = {
        "process_id": "local_ee_sample_regions",
        "arguments": {
            "data": {"from_node": "samples"},
            "spec": graph["samples"]["arguments"]["spec"],
        },
    }

    with pytest.raises(ValueError, match="raster cube, not a feature table or model"):
        validate(graph)


@pytest.mark.parametrize("field, value", [
    ("schema", ["absent"]),
    ("class_property", "absent"),
])
def test_graph_validator_requires_training_fields_in_the_sample_table(field, value):
    graph = _valid_sampling_graph()
    training = json.loads(graph["model"]["arguments"]["spec"])
    training[field] = value
    graph["model"]["arguments"]["spec"] = encode_spec(training)

    with pytest.raises(ValueError, match="Training fields"):
        validate(graph)


@pytest.mark.parametrize("data", [
    {"from_parameter": "data"},
    {"from_node": "source", "band": "red"},
])
def test_graph_validator_keeps_sample_inputs_to_a_single_top_level_reference(data):
    graph = _valid_sampling_graph()
    graph["samples"]["arguments"]["data"] = data

    with pytest.raises(ValueError):
        validate(graph)


def test_graph_validator_rejects_extra_runtime_sampling_arguments():
    graph = _valid_sampling_graph()
    graph["samples"]["arguments"]["tileScale"] = 2

    with pytest.raises(ValueError, match="supported arguments"):
        validate(graph)


def test_graph_validator_rejects_model_as_sample_input():
    graph = _valid_sampling_graph()
    graph["samples"]["arguments"]["data"] = {"from_node": "model"}
    with pytest.raises(ValueError, match="raster cube, not a feature table or model"):
        validate(graph)


def test_graph_validator_requires_sampling_and_training_specs_to_be_json_strings():
    graph = _valid_sampling_graph()
    graph["samples"]["arguments"]["spec"] = json.loads(graph["samples"]["arguments"]["spec"])
    with pytest.raises(ValueError):
        validate(graph)

    graph = _valid_sampling_graph()
    graph["model"]["arguments"]["spec"] = json.loads(graph["model"]["arguments"]["spec"])
    with pytest.raises(ValueError):
        validate(graph)
