"""Official Python SDK compiler checks for post-RF table operations."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.compat.earthengine.classified_feature_ops import (
    invoke_classified_feature_operation,
)
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.runtime_feature_ir import RFClassifiedFeatureTable
from gee.rf_validation_spec import decode_classify_spec
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
EXTENT = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
}


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
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
        "cube:dimensions": {"bands": {"values": ["red", "nir"]}},
    }]
    items = {"sentinel-2-l2a": [{
        "id": "query-scene", "bbox": [0, 0, 2, 2], "geometry": EXTENT,
        "properties": {"system:index": "query-scene"},
    }]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_value(ee, value, local=([], {})):
    return compile_expression(encode(ee, value), local[0], local[1])


def rf(ee):
    return ee.Classifier.smileRandomForest(
        numberOfTrees=5, variablesPerSplit=1, minLeafPopulation=1,
        bagFraction=0.8, maxNodes=8, seed=13,
    )


def training_features(ee):
    return ee.FeatureCollection([
        ee.Feature(None, {"actual": 0, "red": 0.1, "nir": 0.2}),
        ee.Feature(None, {"actual": 0, "red": 0.2, "nir": 0.3}),
        ee.Feature(None, {"actual": 1, "red": 0.7, "nir": 0.8}),
        ee.Feature(None, {"actual": 1, "red": 0.8, "nir": 0.9}),
    ])


def trained(ee, features=None):
    return rf(ee).train(
        features=training_features(ee) if features is None else features,
        classProperty="actual", inputProperties=["nir", "red"],
    )


def query(ee):
    return ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([1, 1]), {
            "actual": 1, "nir": 0.75, "red": 0.65,
        }),
        ee.Feature(None, {"actual": 0, "nir": 0.25, "red": 0.15}),
    ])


def process_nodes(result, process_id):
    return [(key, node) for key, node in result["process_graph"].items()
            if node["process_id"] == process_id]


def test_official_sdk_lowers_filter_limit_random_column_after_rf_classification(ee):
    classifier = trained(ee)
    classified = query(ee).classify(classifier, "predicted")
    expression = (
        classified.randomColumn("split", seed=13, rowKeys=["system:index"])
        .filter(ee.Filter.gte("split", 0.25))
        .limit(1)
    )

    result = compile_value(ee, expression)
    assert result["kind"] == "runtime_table"
    assert result["bands"] == [
        "system:index", "actual", "nir", "red", "predicted", "split", ".geo",
    ]
    classify_id, classify_node = process_nodes(
        result, "local_ee_smile_rf_classify_rows",
    )[0]
    operations = process_nodes(result, "local_ee_runtime_table_op")
    assert len(operations) == 3
    expected = [
        {"operation": "random_column", "column_name": "split"},
        {"operation": "filter"},
        {"operation": "limit", "count": 1},
    ]
    prior_id = classify_id
    for (node_id, node), fields in zip(operations, expected):
        assert node["arguments"]["data"] == {"from_node": prior_id}
        spec = json.loads(node["arguments"]["spec"])
        assert all(spec.get(key) == value for key, value in fields.items())
        prior_id = node_id
    assert result["process_graph"][prior_id]["result"] is True

    # The classify declaration remains the original schema. Post operations
    # live only on the ordered local table-op nodes.
    base_spec = decode_classify_spec(classify_node["arguments"]["spec"])
    assert base_spec["columns"] == [
        "system:index", "actual", "nir", "red", "predicted", ".geo",
    ]


def test_random_column_schema_is_sequential_and_classification_fields_are_preserved(ee):
    translator = Translator([], {}, {})
    classified = query(ee).classify(trained(ee), "predicted")
    table = translator.evaluate(encode(ee, classified))
    assert isinstance(table, RFClassifiedFeatureTable)
    base = (table.spec, table.source, table.classifier, table.rows,
            table.row_count, table.columns)

    first = invoke_classified_feature_operation(translator, "Collection.randomColumn", {
        "collection": table, "columnName": "split", "seed": 9,
    })
    second = invoke_classified_feature_operation(translator, "Collection.randomColumn", {
        "collection": first, "columnName": "split2", "rowKeys": ["split"],
    })
    assert first.operations == (first.operations[0],)
    assert second.columns[-3:] == ("split", "split2", ".geo")
    assert (second.spec, second.source, second.classifier, second.rows,
            second.row_count) == base[:5]
    assert table.operations == ()
    assert table.columns == base[-1]

    with pytest.raises(UnsupportedEEError, match="rowKeys must exist"):
        invoke_classified_feature_operation(translator, "Collection.randomColumn", {
            "collection": table, "columnName": "bad", "rowKeys": ["missing"],
        })
    with pytest.raises(UnsupportedEEError, match="invalid arguments"):
        invoke_classified_feature_operation(translator, "Collection.randomColumn", {
            "collection": table, "columnName": "x" * 257,
        })


def test_classified_operations_reject_sort_map_and_unsupported_filters(ee):
    classifier = trained(ee)
    classified = query(ee).classify(classifier, "predicted")
    with pytest.raises(UnsupportedEEError, match="does not support sorting"):
        compile_value(ee, classified.limit(1, prop="actual"))
    with pytest.raises(UnsupportedEEError, match="does not support sorting"):
        compile_value(ee, classified.sort("actual"))
    with pytest.raises(UnsupportedEEError, match="map, sort, merge"):
        compile_value(ee, classified.map(lambda feature: feature))
    with pytest.raises(UnsupportedEEError, match="Unsupported classified FeatureCollection filter"):
        compile_value(ee, classified.filter(ee.Filter.calendarRange(1, 2)))


def test_sample_and_post_classification_operation_count_is_one_sixteen_step_chain(ee, local):
    regions = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([0.5, 0.5]), {"actual": 0}),
        ee.Feature(ee.Geometry.Point([1.5, 1.5]), {"actual": 1}),
    ])
    sampled = ee.Image("query-scene").select(["red", "nir"]).sampleRegions(
        collection=regions, properties=["actual"], geometries=False,
        scale=10, projection=ee.Projection("EPSG:32610"),
    )
    classifier = trained(ee)
    fifteen = sampled
    for _ in range(15):
        fifteen = fifteen.limit(2)
    result = compile_value(
        ee, fifteen.classify(classifier, "predicted").limit(2), local,
    )
    assert result["kind"] == "runtime_table"
    assert len(process_nodes(result, "local_ee_sample_table_op")) == 15
    assert len(process_nodes(result, "local_ee_runtime_table_op")) == 1

    sixteen = sampled
    for _ in range(16):
        sixteen = sixteen.limit(2)
    with pytest.raises(UnsupportedEEError, match="16 combined sample and table operations"):
        compile_value(ee, sixteen.classify(classifier, "predicted").limit(2), local)


def test_post_limit_zero_keeps_empty_matrix_rules_and_schema_checks(ee):
    classifier = trained(ee)
    classified = query(ee).classify(classifier, "predicted").limit(0)
    with pytest.raises(UnsupportedEEError, match="explicit order for an empty"):
        compile_value(ee, classified.errorMatrix("actual", "predicted").accuracy())

    result = compile_value(
        ee, classified.errorMatrix("actual", "predicted", [0, 1]).accuracy(),
    )
    operations = process_nodes(result, "local_ee_runtime_table_op")
    matrix = process_nodes(result, "local_ee_error_matrix")
    assert len(operations) == len(matrix) == 1
    assert matrix[0][1]["arguments"]["data"] == {"from_node": operations[0][0]}

    bad_column = query(ee).classify(classifier, "predicted").randomColumn("split")
    with pytest.raises(UnsupportedEEError, match="property is missing"):
        compile_value(ee, bad_column.errorMatrix("missing", "predicted", [0, 1]).accuracy())


def test_empty_sampled_classification_and_retraining_remain_rejected_or_explicit(ee, local):
    regions = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([0.5, 0.5]), {"actual": 0}),
    ])
    empty = ee.Image("query-scene").select(["red", "nir"]).sampleRegions(
        collection=regions, properties=["actual"], geometries=False,
        scale=10, projection=ee.Projection("EPSG:32610"),
    ).limit(0)
    classifier = trained(ee)
    classified = empty.classify(classifier, "predicted")
    with pytest.raises(UnsupportedEEError, match="explicit order for an empty"):
        compile_value(ee, classified.errorMatrix("actual", "predicted").accuracy(), local)
    result = compile_value(
        ee, classified.errorMatrix("actual", "predicted", [0, 1]).accuracy(), local,
    )
    assert len(process_nodes(result, "local_ee_error_matrix")) == 1

    with pytest.raises(UnsupportedEEError):
        compile_value(ee, rf(ee).train(
            features=classified, classProperty="actual", inputProperties=["nir", "red"],
        ), local)


def test_classified_filter_work_stays_inside_the_shared_compiler_budget(ee):
    classifier = trained(ee)
    classified = query(ee).classify(classifier, "predicted")
    long_literal = "x" * 4096
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        compile_value(
            ee, classified.filter(ee.Filter.eq("actual", long_literal)),
        )
