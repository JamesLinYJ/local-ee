"""Public DAG type checks for SDK-generated Image.unmix graphs."""
from copy import deepcopy
from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from gee.rf_explanation_spec import prepare_explanation_spec
from gee.smile_rf_spec import decode_rf_spec
from gee.spectral_unmix_spec import prepare_spectral_unmix_spec
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
ENDMEMBERS = [[0.8, 0.2, 0.1], [0.1, 0.7, 0.3], [0.05, 0.15, 0.9]]
SPEC = prepare_spectral_unmix_spec(ENDMEMBERS, sumToOne=True, nonNegative=True)
REGION = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
}


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield guard
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


@pytest.fixture
def local():
    catalog = [{
        "id": "sentinel-2-l2a",
        "cube:dimensions": {"bands": {"values": ["blue", "green", "red"]}},
    }]
    items = {"sentinel-2-l2a": [
        {
            "id": "scene-a", "bbox": [0, 0, 2, 2], "geometry": REGION,
            "properties": {"system:index": "scene-a", "system:time_start": 1_000},
        },
        {
            "id": "training-scene", "bbox": [0, 0, 2, 2], "geometry": REGION,
            "properties": {"system:index": "training-scene", "kind": "training"},
        },
        {
            "id": "target-scene", "bbox": [0, 0, 2, 2], "geometry": REGION,
            "properties": {"system:index": "target-scene", "kind": "target"},
        },
    ]}
    return catalog, items


def _encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def _compile_sdk(ee, value, local):
    return compile_expression(_encode(ee, value), local[0], local[1])


def _sdk_unmix_graph(ee, local):
    image = ee.ImageCollection("sentinel-2-l2a").first().select(["blue", "green", "red"])
    return _compile_sdk(ee, image.unmix(ENDMEMBERS, True, True), local)["process_graph"]


def _sdk_sampled_rf_prediction_graph(ee, local):
    regions = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([0.5, 0.5]), {"label": 0}),
        ee.Feature(ee.Geometry.Point([1.5, 1.5]), {"label": 1}),
    ])
    training_image = ee.Image("training-scene").select(["blue", "green", "red"]).unmix(ENDMEMBERS)
    samples = training_image.sampleRegions(
        collection=regions, properties=["label"], geometries=False,
        scale=10, projection=ee.Projection("EPSG:32610"),
    )
    classifier = ee.Classifier.smileRandomForest(
        numberOfTrees=7, variablesPerSplit=1, minLeafPopulation=1,
        bagFraction=0.75, maxNodes=9, seed=-17,
    ).setOutputMode("CLASSIFICATION").train(
        features=samples, classProperty="label",
        inputProperties=["unmix_0", "unmix_1", "unmix_2"],
    )
    target = ee.Image("target-scene").select(["blue", "green", "red"]).unmix(
        ENDMEMBERS,
    ).classify(classifier, outputName="class")
    return _compile_sdk(ee, target, local)["process_graph"]


def _nodes(graph, process_id):
    return [(key, node) for key, node in graph.items()
            if node.get("process_id") == process_id]


def _referenced_nodes(value):
    if type(value) is dict:
        if set(value) == {"from_node"}:
            yield value["from_node"]
            return
        if set(value) == {"process_graph"}:
            return
        for child in value.values():
            yield from _referenced_nodes(child)
    elif type(value) is list:
        for child in value:
            yield from _referenced_nodes(child)


def _has_ancestor_process(graph, start, process_id):
    pending, visited = [start], set()
    while pending:
        current = pending.pop()
        if current in visited or current not in graph:
            continue
        visited.add(current)
        if graph[current].get("process_id") == process_id:
            return True
        pending.extend(_referenced_nodes(graph[current].get("arguments", {})))
    return False


def _move_result_to(graph, key):
    for node in graph.values():
        node.pop("result", None)
    graph[key]["result"] = True


def test_sdk_generated_unmix_raster_graph_passes_the_public_validator(ee, local):
    graph = _sdk_unmix_graph(ee, local)

    validate(graph)

    producers = _nodes(graph, "local_ee_unmix")
    assert len(producers) == 1
    assert set(producers[0][1]["arguments"]) == {"data", "spec"}


@pytest.mark.parametrize("spec", ["{}", SPEC + " "])
def test_public_validator_rejects_invalid_or_noncanonical_unmix_spec(ee, local, spec):
    graph = _sdk_unmix_graph(ee, local)
    producer = _nodes(graph, "local_ee_unmix")[0][1]
    producer["arguments"]["spec"] = spec

    with pytest.raises(ValueError):
        validate(graph)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_public_validator_requires_exact_unmix_arguments(ee, local, mutation):
    graph = _sdk_unmix_graph(ee, local)
    arguments = _nodes(graph, "local_ee_unmix")[0][1]["arguments"]
    if mutation == "missing":
        arguments.pop("spec")
    else:
        arguments["unexpected"] = True

    with pytest.raises(ValueError):
        validate(graph)


def test_public_validator_rejects_sdk_unmix_nested_in_a_callback(ee, local):
    callback_graph = _sdk_unmix_graph(ee, local)
    graph = {
        "input": {"process_id": "load_collection", "arguments": {"id": "sentinel-2-l2a"}},
        "mapped": {"process_id": "apply", "arguments": {
            "data": {"from_node": "input"},
            "process": {"process_graph": callback_graph},
        }, "result": True},
    }

    with pytest.raises(ValueError, match="top-level cube references"):
        validate(graph)


@pytest.mark.parametrize("reference", [
    {"from_node": "missing-node"},
    {"from_node": "scene-a", "band": "blue"},
    {"from_node": 7},
])
def test_public_validator_rejects_malformed_unmix_data_references(ee, local, reference):
    graph = _sdk_unmix_graph(ee, local)
    producer = _nodes(graph, "local_ee_unmix")[0][1]
    producer["arguments"]["data"] = reference

    with pytest.raises(ValueError):
        validate(graph)


def test_sdk_unmix_output_flows_through_audited_sampling_and_rf_prediction(ee, local):
    graph = _sdk_sampled_rf_prediction_graph(ee, local)

    validate(graph)

    sampler_id, sampler = _nodes(graph, "local_ee_sample_regions")[0]
    trainer_id, trainer = _nodes(graph, "local_ee_train_smile_rf_samples")[0]
    _, prediction = _nodes(graph, "local_ee_smile_rf")[0]
    assert _has_ancestor_process(
        graph, sampler["arguments"]["data"]["from_node"], "local_ee_unmix",
    )
    assert _has_ancestor_process(
        graph, prediction["arguments"]["data"]["from_node"], "local_ee_unmix",
    )
    assert trainer["arguments"]["data"]["from_node"] == sampler_id
    assert prediction["arguments"]["model"] == {"from_node": trainer_id}


@pytest.mark.parametrize("source_kind", ["feature-table", "rf-model", "rf-explanation"])
def test_unmix_rejects_audited_feature_model_and_explanation_sources(ee, local, source_kind):
    graph = deepcopy(_sdk_sampled_rf_prediction_graph(ee, local))
    sampler_id = _nodes(graph, "local_ee_sample_regions")[0][0]
    trainer_id, trainer = _nodes(graph, "local_ee_train_smile_rf_samples")[0]
    if source_kind == "feature-table":
        source_id = sampler_id
    elif source_kind == "rf-model":
        source_id = trainer_id
    else:
        model_spec = decode_rf_spec(trainer["arguments"]["spec"])
        graph["explanation"] = {"process_id": "local_ee_smile_rf_explain", "arguments": {
            "model": {"from_node": trainer_id},
            "spec": prepare_explanation_spec(
                model_spec["schema"], model_spec["number_of_trees"],
            ),
        }}
        source_id = "explanation"

    graph["bad_unmix"] = {"process_id": "local_ee_unmix", "arguments": {
        "data": {"from_node": source_id}, "spec": SPEC,
    }}
    _move_result_to(graph, "bad_unmix")

    with pytest.raises(ValueError):
        validate(graph)
