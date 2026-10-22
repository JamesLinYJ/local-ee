"""Compiler contracts for dynamic sampling, training and raster classification."""
from pathlib import Path
import json

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.sampling_spec import decode_training_spec
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
}
ROI = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
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
        "cube:dimensions": {"bands": {"values": ["red", "nir", "extra"]}},
    }]
    items = {"sentinel-2-l2a": [
        {
            "id": "training-scene", "bbox": [0, 0, 2, 2], "geometry": GEOMETRY,
            "properties": {"system:index": "training-scene", "kind": "training"},
        },
        {
            "id": "target-a", "bbox": [0, 0, 2, 2], "geometry": GEOMETRY,
            "properties": {"system:index": "target-a", "kind": "target"},
        },
        {
            "id": "target-b", "bbox": [0, 0, 2, 2], "geometry": GEOMETRY,
            "properties": {"system:index": "target-b", "kind": "target"},
        },
    ]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def sampled(ee):
    regions = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([0.5, 0.5]), {"label": 2}),
        ee.Feature(ee.Geometry.Point([1.5, 1.5]), {"label": 7}),
    ])
    return ee.Image("training-scene").sampleRegions(
        collection=regions, properties=["label"], geometries=False,
        scale=10, projection=ee.Projection("EPSG:32610"),
    )


def model(ee):
    return ee.Classifier.minimumDistance(metric="manhattan").train(
        features=sampled(ee), classProperty="label",
        inputProperties=["nir", "red"],
    )


def process_nodes(result, process_id):
    return [(node_id, node) for node_id, node in result["process_graph"].items()
            if node["process_id"] == process_id]


def test_sample_table_training_and_map_classification_share_one_real_runtime_chain(ee, local):
    classifier = model(ee)
    target = ee.ImageCollection("sentinel-2-l2a").filter(
        ee.Filter.eq("kind", "target"),
    ).map(lambda image: image.select(["extra", "nir", "red"]).classify(
        classifier, outputName="landcover",
    ))
    result = compile_expression(
        encode(ee, target), local[0], local[1],
        options={"region": ROI, "scale": 2, "crs": "EPSG:3857"},
    )

    assert result["kind"] == "collection"
    assert result["bands"] == ["landcover"]
    assert set(result["source_item_ids"]) == {"training-scene", "target-a", "target-b"}
    graph = result["process_graph"]
    samplers = process_nodes(result, "local_ee_sample_regions")
    trainers = process_nodes(result, "local_ee_train_minimum_distance")
    classifiers = process_nodes(result, "local_ee_minimum_distance")
    assert len(samplers) == len(trainers) == len(classifiers) == 1

    sampler_id, sampler = samplers[0]
    trainer_id, trainer = trainers[0]
    _, classify = classifiers[0]
    assert trainer["arguments"]["data"] == {"from_node": sampler_id}
    assert sampler["arguments"]["spec"]
    training = decode_training_spec(trainer["arguments"]["spec"])
    assert training == {
        "version": 1, "metric": "manhattan", "class_property": "label",
        "schema": ["nir", "red"],
    }
    assert classify["arguments"]["model"] == {"from_node": trainer_id}
    assert sampler_id != trainer_id

    loads = [node["arguments"] for node in graph.values()
             if node["process_id"] == "load_collection"]
    by_ids = {tuple(load["_gee_item_ids"]): load for load in loads}
    assert by_ids[("training-scene",)]["bands"] == ["red", "nir", "extra"]
    assert by_ids[("training-scene",)]["spatial_extent"] == {
        "west": 0, "south": 0, "east": 2, "north": 2,
    }
    assert by_ids[("target-a", "target-b")]["bands"] == ["red", "nir"]
    assert by_ids[("target-a", "target-b")]["spatial_extent"] == {
        "west": 0, "south": 0, "east": 1, "north": 1,
    }

    resamples = [node["arguments"] for node in graph.values()
                 if node["process_id"] == "resample_spatial"]
    assert any(node.get("resolution") == 10 and node.get("projection") == 32610
               for node in resamples)
    assert any(node.get("resolution") == 2 and node.get("projection") == 3857
               for node in resamples)
    assert graph[next(reversed(graph))]["result"] is True


def test_dynamic_schema_is_metadata_only_and_unsupported_model_consumers_reject(ee, local):
    classifier = model(ee)
    assert compile_expression(encode(ee, classifier.schema()), local[0], local[1])["value"] == [
        "nir", "red",
    ]

    for value in (
        classifier,
        classifier.confusionMatrix(),
        sampled(ee).classify(classifier),
        sampled(ee).size(),
    ):
        with pytest.raises(UnsupportedEEError):
            compile_expression(encode(ee, value), local[0], local[1])


def test_dynamic_model_has_no_static_truthiness_or_compile_time_pixels(ee, local):
    classifier = model(ee)
    with pytest.raises(UnsupportedEEError, match="static scalar/list/dictionary"):
        compile_expression(encode(ee, ee.Algorithms.If(classifier, 1, 0)), local[0], local[1])

    result = compile_expression(
        encode(ee, ee.Image("target-a").classify(classifier)), local[0], local[1],
    )
    assert "features" not in result and "value" not in result
    _, node = process_nodes(result, "local_ee_minimum_distance")[0]
    assert set(node["arguments"]["model"]) == {"from_node"}
