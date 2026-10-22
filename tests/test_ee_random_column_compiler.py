"""Compiler support for bounded inline and lazy sampled random columns."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from gee.random_column_spec import decode_random_column_spec
from gee.sample_table_spec import decode_sample_operation
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
EXTENT = {
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
        "cube:dimensions": {"bands": {"values": ["red", "nir"]}},
    }]
    items = {"sentinel-2-l2a": [{
        "id": "training-scene", "bbox": [0, 0, 2, 2], "geometry": EXTENT,
        "properties": {"system:index": "training-scene"},
    }]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def sample_regions(ee):
    regions = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([0.5, 0.5]), {"label": 0}),
        ee.Feature(ee.Geometry.Point([1.5, 1.5]), {"label": 1}),
    ])
    return ee.Image("training-scene").select(["red", "nir"]).sampleRegions(
        collection=regions, properties=["label"], geometries=False,
        scale=10, projection=ee.Projection("EPSG:32610"),
    )


def process_nodes(result, process_id):
    return [(key, node) for key, node in result["process_graph"].items()
            if node["process_id"] == process_id]


def test_inline_random_column_uses_typed_row_keys_and_preserves_source(ee, local):
    source = ee.FeatureCollection([
        ee.Feature(None, {"site": "same", "random": -1, "label": 0}),
        ee.Feature(None, {"site": "other", "random": -2, "label": 1}),
        ee.Feature(None, {"site": "same", "random": -3, "label": 2}),
    ])
    randomized = source.randomColumn(
        columnName="random", seed=9.0, distribution="uniform", rowKeys=["site"],
    )
    result = compile_expression(encode(ee, randomized), local[0], local[1])["value"]
    original = compile_expression(encode(ee, source), local[0], local[1])["value"]

    values = [feature["properties"]["random"] for feature in result["features"]]
    assert len(set(values)) == 2
    assert values[0] == values[2]
    assert all(0 <= value < 1 and math.isfinite(value) for value in values)
    assert [feature["properties"]["random"] for feature in original["features"]] == [-1, -2, -3]

    with_system_index = ee.FeatureCollection([
        ee.Feature(None, {"system:index": "row-a"}),
        ee.Feature(None, {"system:index": "row-b"}),
    ])
    defaulted = compile_expression(
        encode(ee, with_system_index.randomColumn()), local[0], local[1],
    )["value"]
    assert all(0 <= row["properties"]["random"] < 1
               for row in defaulted["features"])


def test_sampled_random_operations_are_lazy_ordered_and_schema_aware(ee, local):
    source = sample_regions(ee)
    once = source.randomColumn("split", seed=7, rowKeys=["label"])
    twice = once.randomColumn(
        "split", seed=8, distribution="normal", rowKeys=["split", "label"],
    )
    selected = twice.filter(ee.Filter.gte("split", -10))
    result = compile_expression(encode(ee, selected), local[0], local[1])
    original_result = compile_expression(encode(ee, source), local[0], local[1])

    assert result["kind"] == "sample_table"
    assert result["bands"] == ["system:index", "label", "red", "nir", "split", ".geo"]
    assert original_result["bands"] == ["system:index", "label", "red", "nir", ".geo"]
    assert len(result["sample_operations"]) == 3
    decoded = [decode_sample_operation(text) for text in result["sample_operations"]]
    assert [item["operation"] for item in decoded] == [
        "random_column", "random_column", "filter",
    ]
    first = decode_random_column_spec(result["sample_operations"][0])
    second = decode_random_column_spec(result["sample_operations"][1])
    assert first["row_keys"] == ["label"]
    assert second["row_keys"] == ["split", "label"]
    assert first["column_name"] == second["column_name"] == "split"
    assert "rows" not in result and "features" not in result

    samplers = process_nodes(result, "local_ee_sample_regions")
    operations = process_nodes(result, "local_ee_sample_table_op")
    assert len(samplers) == 1 and len(operations) == 3
    previous = samplers[0][0]
    for text, (node_id, node) in zip(result["sample_operations"], operations):
        assert node["arguments"]["data"] == {"from_node": previous}
        assert node["arguments"]["spec"] == text
        previous = node_id
    validate(result["process_graph"])

    filtered_first = source.filter(ee.Filter.notNull(["label"])).randomColumn(
        "early", seed=5, rowKeys=["label"],
    )
    filtered_result = compile_expression(
        encode(ee, filtered_first), local[0], local[1],
    )
    assert [item["operation"] for item in map(
        decode_sample_operation, filtered_result["sample_operations"],
    )] == ["filter", "random_column"]

    overwrite_band = compile_expression(
        encode(ee, source.randomColumn("red", seed=6, rowKeys=["label"])),
        local[0], local[1],
    )
    assert overwrite_band["bands"] == [
        "system:index", "label", "red", "nir", ".geo",
    ]


def test_transformed_sample_schema_reaches_training_classification_and_matrix(ee, local):
    samples = sample_regions(ee).randomColumn(
        "split", seed=11, distribution="normal", rowKeys=["label"],
    )
    rf = ee.Classifier.smileRandomForest(numberOfTrees=3).train(
        features=samples, classProperty="label", inputProperties=["split"],
    )
    target = ee.Image("training-scene").addBands(
        ee.Image.constant(0.5).rename("split"),
    )
    image_result = compile_expression(
        encode(ee, target.classify(rf)),
        local[0], local[1],
    )
    assert image_result["bands"] == ["classification"]
    assert len(process_nodes(image_result, "local_ee_train_smile_rf_samples")) == 1
    assert len(process_nodes(image_result, "local_ee_sample_table_op")) == 1
    validate(image_result["process_graph"])

    minimum_distance = ee.Classifier.minimumDistance(metric="manhattan").train(
        features=samples, classProperty="label", inputProperties=["split"],
    )
    distance_result = compile_expression(
        encode(ee, target.classify(minimum_distance)),
        local[0], local[1],
    )
    assert distance_result["bands"] == ["classification"]
    assert len(process_nodes(distance_result, "local_ee_train_minimum_distance")) == 1
    assert len(process_nodes(distance_result, "local_ee_sample_table_op")) == 1
    validate(distance_result["process_graph"])

    literal = ee.FeatureCollection([
        ee.Feature(None, {"label": 0, "split": -1.0}),
        ee.Feature(None, {"label": 0, "split": -0.5}),
        ee.Feature(None, {"label": 1, "split": 0.5}),
        ee.Feature(None, {"label": 1, "split": 1.0}),
    ])
    feature_classifier = ee.Classifier.smileRandomForest(numberOfTrees=3).train(
        features=literal, classProperty="label", inputProperties=["split"],
    )
    table_result = compile_expression(
        encode(ee, samples.classify(feature_classifier, outputName="predicted")),
        local[0], local[1],
    )
    assert table_result["kind"] == "runtime_table"
    assert table_result["bands"] == [
        "system:index", "label", "red", "nir", "split", "predicted", ".geo",
    ]
    assert len(process_nodes(table_result, "local_ee_sample_table_op")) == 1
    validate(table_result["process_graph"])

    matrix_result = compile_expression(
        encode(ee, samples.errorMatrix("label", "label", order=[0, 1]).array()),
        local[0], local[1],
    )
    assert matrix_result["kind"] == "runtime_value"
    assert len(process_nodes(matrix_result, "local_ee_sample_table_op")) == 1
    validate(matrix_result["process_graph"])


def test_image_sample_random_column_preserves_v2_descriptor_and_source_grid(ee, local):
    samples = ee.Image("training-scene").sample(
        region=ee.Geometry(EXTENT), scale=10,
        projection=ee.Projection("EPSG:32610"), dropNulls=False,
    ).randomColumn("split", seed=12, rowKeys=["system:index"])
    result = compile_expression(encode(ee, samples), local[0], local[1])

    assert result["kind"] == "sample_table"
    assert result["bands"] == ["system:index", "red", "nir", "split", ".geo"]
    assert len(result["sample_operations"]) == 1
    sampler, = process_nodes(result, "local_ee_sample_regions")
    assert sampler[1]["arguments"]["spec"] == result["sample_spec"]
    assert result["grid_options"] == {"scale": 10, "crs": "EPSG:32610"}
    validate(result["process_graph"])


def test_random_column_rejects_missing_row_keys_reserved_names_and_image_collections(ee, local):
    inline = ee.FeatureCollection([ee.Feature(None, {"site": "a"})])
    with pytest.raises(UnsupportedEEError, match="row key is missing"):
        compile_expression(encode(ee, inline.randomColumn()), local[0], local[1])

    sampled = sample_regions(ee)
    with pytest.raises(UnsupportedEEError, match="rowKeys must exist"):
        compile_expression(
            encode(ee, sampled.randomColumn("draw", rowKeys=["missing"])),
            local[0], local[1],
        )
    with pytest.raises(UnsupportedEEError, match="reserved output"):
        compile_expression(
            encode(ee, inline.randomColumn(".geo", rowKeys=["site"])),
            local[0], local[1],
        )
    with pytest.raises(UnsupportedEEError, match="Unsupported Earth Engine algorithm"):
        compile_expression(
            encode(ee, ee.ImageCollection("sentinel-2-l2a").randomColumn()),
            local[0], local[1],
        )

    rows = ee.FeatureCollection([
        ee.Feature(None, {"label": 0, "value": 0.1}),
        ee.Feature(None, {"label": 0, "value": 0.2}),
        ee.Feature(None, {"label": 1, "value": 0.8}),
        ee.Feature(None, {"label": 1, "value": 0.9}),
    ])
    trained = ee.Classifier.smileRandomForest(numberOfTrees=3).train(
        features=rows, classProperty="label", inputProperties=["value"],
    )
    classified = rows.classify(trained, outputName="predicted")
    with pytest.raises(UnsupportedEEError, match="Unsupported Earth Engine algorithm"):
        compile_expression(
            encode(ee, classified.randomColumn("after", rowKeys=["value"])),
            local[0], local[1],
        )
    with pytest.raises(UnsupportedEEError, match="Expected a collection and filter"):
        compile_expression(
            encode(ee, classified.filter(ee.Filter.gte("value", 0))),
            local[0], local[1],
        )


def test_random_column_seed_and_distribution_wire_validation(ee, local):
    features = ee.FeatureCollection([ee.Feature(None, {"site": "a"})])
    with pytest.raises(UnsupportedEEError, match="distribution"):
        compile_expression(
            encode(ee, features.randomColumn("draw", distribution="gaussian", rowKeys=["site"])),
            local[0], local[1],
        )
    with pytest.raises(UnsupportedEEError, match="signed 64-bit"):
        compile_expression(
            encode(ee, features.randomColumn("draw", seed=2**63, rowKeys=["site"])),
            local[0], local[1],
        )


def test_sampled_schema_memo_is_charged_scoped_and_returns_owned_values(ee, local):
    from gee.compat.earthengine.decoder import Translator
    from gee.compat.earthengine.ir import Filter, SampledFeatures
    from gee.compat.earthengine.sampled_feature_ops import validated_sampled_schema
    from gee.sample_table_spec import prepare_sample_filter
    from gee.sampling_spec import decode_sampling_spec, encode_spec

    table = sample_regions(ee).randomColumn("split", seed=4, rowKeys=["label"]).filter(
        ee.Filter.notNull(["label", "split"]),
    )
    translator = Translator(local[0], local[1], {})
    sampled = translator.evaluate(encode(ee, table))
    assert isinstance(sampled, SampledFeatures)

    first_at = translator.steps
    first_origin, first_columns, operations = validated_sampled_schema(
        sampled, translator, "schema memo regression",
    )
    first_work = translator.steps - first_at
    first_origin["bands"].clear()
    first_columns.clear()

    hit_at = translator.steps
    second_origin, second_columns, second_operations = validated_sampled_schema(
        sampled, translator, "schema memo regression",
    )
    hit_work = translator.steps - hit_at
    assert 0 < hit_work < first_work
    assert second_origin["bands"] == ["red", "nir"]
    assert second_columns == [
        "system:index", "label", "red", "nir", "split", ".geo",
    ]
    assert second_operations is operations
    assert translator._sampled_schema_cache[(id(sampled.spec), id(operations))][2] \
        is not first_origin

    # A different immutable operation tuple or spec string is a cache miss;
    # each variant must pass its own operation/spec validation.
    changed_ops = (*operations[:-1], prepare_sample_filter(Filter(
        "greaterThan", {"leftField": "split", "rightValue": 0.5},
    )))
    changed_operation_table = SampledFeatures(
        sampled.image, sampled.spec, changed_ops,
    )
    before_entries = len(translator._sampled_schema_cache)
    validated_sampled_schema(
        changed_operation_table, translator, "schema memo regression",
    )
    assert len(translator._sampled_schema_cache) == before_entries + 1

    changed_spec = decode_sampling_spec(sampled.spec)
    changed_spec["geometries"] = not changed_spec["geometries"]
    changed_spec_table = SampledFeatures(
        sampled.image, encode_spec(changed_spec), operations,
    )
    before_entries = len(translator._sampled_schema_cache)
    validated_sampled_schema(changed_spec_table, translator, "schema memo regression")
    assert len(translator._sampled_schema_cache) == before_entries + 1

    # The memo is local to one translator and must not bypass validation for a
    # new operation tuple that shares only the original sampling spec.
    invalid = SampledFeatures(sampled.image, sampled.spec, (*operations, "{}"))
    with pytest.raises(UnsupportedEEError, match="invalid operation spec"):
        validated_sampled_schema(invalid, translator, "schema memo regression")
    separate = Translator(local[0], local[1], {})
    validated_sampled_schema(sampled, separate, "schema memo regression")
    assert len(separate._sampled_schema_cache) == 1

    # A cache hit still consumes the same bounded compiler budget.
    saved_steps = translator.steps
    translator.steps = 49_999
    try:
        with pytest.raises(UnsupportedEEError, match="50000-step"):
            validated_sampled_schema(sampled, translator, "schema memo regression")
        assert translator.steps == 49_999
    finally:
        translator.steps = saved_steps
