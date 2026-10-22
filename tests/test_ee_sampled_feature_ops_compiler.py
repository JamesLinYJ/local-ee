"""Lazy sampled-table filters/limits and fixed-grid training compiler paths."""
import json
from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from gee.sampling_spec import decode_sampling_spec
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
GEOMETRY = {
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
        "cube:dimensions": {"bands": {"values": ["red", "nir", "extra"]}},
    }]
    items = {"sentinel-2-l2a": [
        {"id": "training-scene", "bbox": [0, 0, 2, 2], "geometry": GEOMETRY,
         "properties": {"system:index": "training-scene", "role": "training"}},
        {"id": "target-scene", "bbox": [0, 0, 2, 2], "geometry": GEOMETRY,
         "properties": {"system:index": "target-scene", "role": "target"}},
    ]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def sample(ee):
    regions = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([0.5, 0.5]), {"label": 1, "quality": 0.8}),
        ee.Feature(ee.Geometry.Point([1.5, 1.5]), {"label": 2, "quality": 0.2}),
    ])
    return ee.Image("training-scene").select(["red", "nir"]).sampleRegions(
        collection=regions, properties=["label", "quality"], geometries=True,
        scale=10, projection=ee.Projection("EPSG:32610"),
    )


def process_nodes(result, process_id):
    return [(key, node) for key, node in result["process_graph"].items()
            if node["process_id"] == process_id]


def test_filter_expression_also_matches_inline_features_with_existing_null_rules(ee):
    features = ee.FeatureCollection([
        ee.Feature(None, {"label": "keep", "score": 3}),
        ee.Feature(None, {"label": "small", "score": 1}),
        ee.Feature(None, {"label": "missing"}),
        ee.Feature(None, {"label": "drop", "score": 3}),
        ee.Feature(None, {"label": "null", "score": None}),
    ])
    selected = features.filter(
        ee.Filter.expression("score >= 2 && label != 'drop'"),
    )
    result = compile_expression(encode(ee, selected), [], {})["value"]
    assert [feature["properties"]["label"] for feature in result["features"]] == ["keep"]


def test_sample_filter_precheck_allows_wire_containers_beyond_semantic_depth(ee, local):
    accepted = ee.Filter.gt("quality", 0)
    for _ in range(15):
        accepted = ee.Filter.Not(accepted)
    result = compile_expression(
        encode(ee, sample(ee).filter(accepted)), local[0], local[1],
    )
    assert result["kind"] == "sample_table"
    assert len(process_nodes(result, "local_ee_sample_table_op")) == 1
    validate(result["process_graph"])

    rejected = ee.Filter.gt("quality", 0)
    for _ in range(17):
        rejected = ee.Filter.Not(rejected)
    with pytest.raises(UnsupportedEEError, match="Sample predicates exceed"):
        compile_expression(
            encode(ee, sample(ee).filter(rejected)), local[0], local[1],
        )


def test_sampled_filter_expression_and_limit_lower_to_ordered_lazy_nodes(ee, local):
    expression = ee.Filter.expression("quality >= 0.5 && label != 0")
    selected = sample(ee).filter(expression).limit(1)
    result = compile_expression(encode(ee, selected), local[0], local[1])

    assert result["kind"] == "sample_table"
    assert "features" not in result and "rows" not in result
    assert result["bands"] == ["system:index", "label", "quality", "red", "nir", ".geo"]
    spec = decode_sampling_spec(result["sample_spec"])
    assert spec["grid"] == {"scale": 10, "crs": "EPSG:32610"}
    assert spec["bands"] == ["red", "nir"]
    assert spec["properties"] == ["label", "quality"]

    sampler_id, sampler = process_nodes(result, "local_ee_sample_regions")[0]
    operations = process_nodes(result, "local_ee_sample_table_op")
    assert len(operations) == 2
    filter_id, filter_node = operations[0]
    limit_id, limit_node = operations[1]
    assert sampler["arguments"]["spec"] == result["sample_spec"]
    assert filter_node["arguments"]["data"] == {"from_node": sampler_id}
    assert limit_node["arguments"]["data"] == {"from_node": filter_id}
    filter_spec = json.loads(filter_node["arguments"]["spec"])
    limit_spec = json.loads(limit_node["arguments"]["spec"])
    assert filter_spec == {
        "version": 1,
        "operation": "filter",
        "predicate": {
            "name": "and",
            "arguments": {"filters": [
                {"name": "not", "arguments": {"filter": {
                    "name": "lessThan", "arguments": {
                        "leftField": "quality", "rightValue": 0.5,
                    },
                }}},
                {"name": "not", "arguments": {"filter": {
                    "name": "equals", "arguments": {
                        "leftField": "label", "rightValue": 0,
                    },
                }}},
            ]},
        },
    }
    assert limit_spec == {"version": 1, "operation": "limit", "count": 1}
    assert result["process_graph"][next(reversed(result["process_graph"]))]["result"] is True
    validate(result["process_graph"])


def test_dynamic_training_consumes_filtered_table_and_keeps_its_own_grid(ee, local):
    classifier = ee.Classifier.minimumDistance(metric="manhattan").train(
        features=sample(ee).filter(
            ee.Filter.expression("quality >= 0.5 && label != 0"),
        ).limit(1),
        classProperty="label", inputProperties=["nir", "red"],
    )
    target = ee.ImageCollection("sentinel-2-l2a").filter(
        ee.Filter.eq("role", "target"),
    ).map(lambda image: image.select(["extra", "nir", "red"]).classify(
        classifier, outputName="class",
    ))
    result = compile_expression(
        encode(ee, target), local[0], local[1],
        options={"region": GEOMETRY, "scale": 2, "crs": "EPSG:3857"},
    )

    assert result["kind"] == "collection"
    assert result["bands"] == ["class"]
    assert set(result["source_item_ids"]) == {"training-scene", "target-scene"}
    samplers = process_nodes(result, "local_ee_sample_regions")
    operations = process_nodes(result, "local_ee_sample_table_op")
    trainers = process_nodes(result, "local_ee_train_minimum_distance")
    assert len(samplers) == len(trainers) == 1
    assert len(operations) == 2
    sampler_id, sampler = samplers[0]
    filter_id, filter_node = operations[0]
    operation_id, operation = operations[1]
    trainer_id, trainer = trainers[0]
    assert filter_node["arguments"]["data"] == {"from_node": sampler_id}
    assert json.loads(filter_node["arguments"]["spec"])["operation"] == "filter"
    assert operation["arguments"]["data"] == {"from_node": filter_id}
    assert trainer["arguments"]["data"] == {"from_node": operation_id}
    assert json.loads(operation["arguments"]["spec"])["operation"] == "limit"
    sample_spec = decode_sampling_spec(sampler["arguments"]["spec"])
    assert sample_spec["grid"] == {"scale": 10, "crs": "EPSG:32610"}
    loads = [node["arguments"] for node in result["process_graph"].values()
             if node["process_id"] == "load_collection"]
    assert any(load["_gee_item_ids"] == ["training-scene"]
               and load.get("spatial_extent") == {"west": 0, "south": 0, "east": 2, "north": 2}
               for load in loads)
    assert any(load["_gee_item_ids"] == ["target-scene"]
               and load.get("spatial_extent") == {"west": 0, "south": 0, "east": 2, "north": 2}
               for load in loads)
    resamples = [node["arguments"] for node in result["process_graph"].values()
                 if node["process_id"] == "resample_spatial"]
    assert any(node.get("resolution") == 10 and node.get("projection") == 32610
               for node in resamples)
    assert any(node.get("resolution") == 2 and node.get("projection") == 3857
               for node in resamples)
    assert result["process_graph"][next(reversed(result["process_graph"]))]["result"] is True
    validate(result["process_graph"])


@pytest.mark.parametrize("value", [
    "sort", "float_limit", "bad_ascending", "unsupported_filter", "seventeen_ops",
])
def test_sampled_operations_reject_sort_invalid_parameters_and_excess_depth(ee, local, value):
    features = sample(ee)
    if value == "sort":
        features = features.limit(1, prop="quality")
    elif value == "float_limit":
        features = features.limit(1.0)
    elif value == "bad_ascending":
        features = features.limit(1, ascending=1)
    elif value == "unsupported_filter":
        features = features.filter(ee.Filter.calendarRange(1, 2))
    else:
        for _ in range(17):
            features = features.limit(1)
    with pytest.raises(UnsupportedEEError):
        compile_expression(encode(ee, features), local[0], local[1])
