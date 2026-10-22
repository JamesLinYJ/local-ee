"""Real DAG validation and catalog freezing for bounded opaque RF models."""
import copy
import json

import pytest

from ee_sampling_contract_helpers import _valid_sampling_graph
from gee.backend import Processes
from gee.graph import collection_loads, materialize, validate
from gee.local_processes import validate_local_process
from gee.sample_table_spec import prepare_sample_limit
from gee.smile_rf_processes import RF_CLASSIFY, RF_ROWS, RF_SAMPLES
from gee.smile_rf_spec import prepare_rf_parameters, prepare_rf_rows, prepare_rf_spec


def rf_spec(schema=("process_id",), class_property="from_node"):
    return prepare_rf_spec(prepare_rf_parameters(7, seed=19), schema, class_property)


def rf_graph(*, sampled=False, operations=0):
    graph = _valid_sampling_graph()
    spec = rf_spec()
    if sampled:
        previous = "samples"
        for index in range(operations):
            key = f"op{index}"
            graph[key] = {"process_id": "local_ee_sample_table_op", "arguments": {
                "data": {"from_node": previous}, "spec": prepare_sample_limit(None)}}
            previous = key
        graph["model"] = {"process_id": RF_SAMPLES, "arguments": {
            "data": {"from_node": previous}, "spec": spec}}
    else:
        graph.pop("samples")
        graph["model"] = {"process_id": RF_ROWS, "arguments": {
            "rows": prepare_rf_rows([[0, [2]], [1, [7]]], json.loads(spec)), "spec": spec}}
    graph["classify"]["process_id"] = RF_CLASSIFY
    return graph


@pytest.mark.parametrize("sampled", [False, True])
def test_real_validator_freezes_catalog_without_interpreting_literal_property_names(sampled):
    graph = rf_graph(sampled=sampled)
    before = copy.deepcopy(graph)
    validate(graph)
    assert collection_loads(graph) == {"synthetic": ("synthetic", None)}
    frozen = materialize(graph, ["synthetic"], "/tmp/rf-frozen-catalog")
    assert frozen["source"]["process_id"] == "load_stac"
    assert frozen["model"] == before["model"]
    if sampled:
        assert frozen["samples"]["arguments"]["spec"] == before["samples"]["arguments"]["spec"]
    assert graph == before


def test_sampled_forest_retains_original_schema_through_sixteen_operations():
    validate(rf_graph(sampled=True, operations=16))
    with pytest.raises(ValueError, match="16 operations"):
        validate(rf_graph(sampled=True, operations=17))


@pytest.mark.parametrize("schema,label", [(["absent"], "from_node"), (["process_id"], "absent")])
def test_sampled_forest_fields_must_exist_before_training(schema, label):
    graph = rf_graph(sampled=True)
    graph["model"]["arguments"]["spec"] = rf_spec(schema, label)
    with pytest.raises(ValueError, match="sample-table columns"):
        validate(graph)


@pytest.mark.parametrize("producer", ["source", "classify", "model"])
def test_sampled_training_refuses_rasters_models_and_cycles(producer):
    graph = rf_graph(sampled=True)
    graph["model"]["arguments"]["data"] = {"from_node": producer}
    with pytest.raises(ValueError, match="sample_regions|cycle|only feed"):
        validate(graph)


@pytest.mark.parametrize("producer", ["source", "samples"])
def test_rf_model_parameter_refuses_other_producer_types(producer):
    graph = rf_graph(sampled=True)
    graph["classify"]["arguments"]["model"] = {"from_node": producer}
    with pytest.raises(ValueError, match="audited Smile"):
        validate(graph)


def test_minimum_distance_and_rf_models_do_not_cross_algorithm_boundaries():
    graph = _valid_sampling_graph()
    graph["classify"]["process_id"] = RF_CLASSIFY
    with pytest.raises(ValueError, match="audited Smile"):
        validate(graph)
    graph = rf_graph(sampled=True)
    graph["classify"]["process_id"] = "local_ee_minimum_distance"
    with pytest.raises(ValueError, match="audited sampled-training|only feed"):
        validate(graph)


@pytest.mark.parametrize("producer", ["samples", "model"])
def test_rf_prediction_requires_raster_not_sample_table_or_model(producer):
    graph = rf_graph(sampled=True)
    graph["classify"]["arguments"]["data"] = {"from_node": producer}
    with pytest.raises(ValueError, match="raster cube|only feed"):
        validate(graph)


@pytest.mark.parametrize("consumer", ["local_ee_to_double", "save_result"])
def test_opaque_model_cannot_reach_other_consumers_or_output_serializers(consumer):
    graph = rf_graph()
    graph["bad"] = {"process_id": consumer, "arguments": {"data": {"from_node": "model"}}}
    if consumer == "save_result":
        graph["bad"]["arguments"]["format"] = "GTiff"
    with pytest.raises(ValueError, match="only feed"):
        validate(graph)
    graph = rf_graph()
    graph["classify"].pop("result")
    graph["model"]["result"] = True
    with pytest.raises(ValueError, match="only feed"):
        validate(graph)


@pytest.mark.parametrize("name", [RF_ROWS, RF_SAMPLES, RF_CLASSIFY])
def test_protocol_requires_exact_top_level_arguments_and_a_real_registered_spec(name):
    graph = rf_graph(sampled=name == RF_SAMPLES)
    arguments = graph["classify" if name == RF_CLASSIFY else "model"]["arguments"]
    validate_local_process(name, arguments, 0, node_context=graph)
    for changed in [{**arguments, "extra": True}, {key: value for key, value in arguments.items() if key != "spec" and key != "model"}]:
        with pytest.raises(ValueError):
            validate_local_process(name, changed, 0, node_context=graph)
    with pytest.raises(ValueError):
        validate_local_process(name, arguments, 1, node_context=graph)
    spec = Processes().get_process_registry("1.2.0").get_spec(name)
    assert spec["experimental"] is True
    assert "Google" in spec["description"] and "unverified" in spec["description"]
    assert {p["name"] for p in spec["parameters"]} == set(arguments)


@pytest.mark.parametrize("bad", ["/tmp/forest.ser", "https://example.invalid/model", {}, {"from_parameter": "model"}, {"from_node": 1}])
def test_no_external_or_user_serialized_models_in_public_protocol(bad):
    graph = rf_graph()
    graph["classify"]["arguments"]["model"] = bad
    with pytest.raises(ValueError):
        validate(graph)


def test_protocol_rejects_raw_java_bytes_before_the_graph_json_boundary():
    graph = rf_graph()
    arguments = {**graph["classify"]["arguments"], "model": b"java bytes"}
    with pytest.raises(ValueError, match="canonical top-level"):
        validate_local_process(RF_CLASSIFY, arguments, 0, node_context=graph)


@pytest.mark.parametrize("wrapped", [
    {"wrapped": {"from_node": "model"}},
    [{"from_node": "model"}],
    {"wrapped": [0, {"deeper": {"from_node": "model"}}]},
])
def test_opaque_models_cannot_hide_in_nested_generic_process_arguments(wrapped):
    graph = rf_graph()
    graph["bad"] = {"process_id": "save_result", "arguments": {"data": wrapped, "format": "GTiff"}}
    with pytest.raises(ValueError, match="only feed"):
        validate(graph)


def test_callback_references_belong_to_the_callback_even_when_root_model_id_matches():
    graph = rf_graph()
    graph["apply"] = {"process_id": "apply", "arguments": {
        "data": {"from_node": "source"},
        "process": {"process_graph": {
            "model": {"process_id": "add", "arguments": {"x": {"from_parameter": "x"}, "y": 1}},
            "out": {"process_id": "multiply", "arguments": {"x": {"from_node": "model"}, "y": 2}, "result": True},
        }},
    }}
    validate(graph)


@pytest.mark.parametrize("process,arguments", [
    ("aggregate_spatial", {"data": {"from_node": "source"}, "geometries": {"type": "FeatureCollection", "features": []},
                           "reducer": {"process_graph": {"mean": {"process_id": "mean", "arguments": {"data": {"from_parameter": "data"}}, "result": True}}}}),
    ("add", {"x": 1, "y": 2}),
    ("mean", {"data": [1, 2]}),
    ("array_create", {"data": [1, 2]}),
])
def test_vector_and_scalar_process_returns_cannot_be_queued_as_rf_rasters(process, arguments):
    graph = rf_graph()
    graph["wrong_type"] = {"process_id": process, "arguments": arguments}
    graph["classify"]["arguments"]["data"] = {"from_node": "wrong_type"}
    with pytest.raises(ValueError, match="audited raster cube"):
        validate(graph)
    assert Processes().validate(graph)  # public process validation also reports the error
