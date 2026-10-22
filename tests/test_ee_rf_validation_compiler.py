"""Compiler-only checks for lazy Smile RF feature prediction and validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import (
    Function,
    Image,
    SampledFeatures,
    SmileRandomForest,
    TrainedSmileRandomForest,
)
from gee.compat.earthengine.runtime_validation_graph import compile_runtime_table
from gee.graph import validate
from gee.rf_validation_spec import (
    decode_classify_spec,
    decode_feature_rows,
    decode_matrix_spec,
    decode_metric_spec,
)
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
        "id": "training-scene", "bbox": [0, 0, 2, 2], "geometry": EXTENT,
        "properties": {"system:index": "training-scene"},
    }]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_value(ee, value, local=([], {})):
    result = compile_expression(encode(ee, value), local[0], local[1])
    if "process_graph" in result:
        validate(result["process_graph"])
    return result


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


def process_nodes(result, process_id):
    return [(key, node) for key, node in result["process_graph"].items()
            if node["process_id"] == process_id]


def test_decoder_value_ref_cache_is_root_scoped_and_charges_each_hit():
    translator = Translator([], {}, {})
    translator.evaluate(0)
    sample = SampledFeatures(Image([], {}), "{}")
    translator.scope["shared_sample"] = sample
    reference = {"type": "ValueRef", "value": "shared_sample"}

    before = translator.steps
    assert translator.evaluate(reference, translator._root_env, 1) is sample
    first_cost = translator.steps - before
    before = translator.steps
    assert translator.evaluate(reference, translator._root_env, 1) is sample
    cached_cost = translator.steps - before
    assert first_cost > cached_cost == 1

    model = TrainedSmileRandomForest(
        SmileRandomForest(1, 1, 1, 0.5, None, 0),
        ("red",), "actual", "{}", samples=sample,
    )
    translator.scope["shared_model"] = model
    model_reference = {"type": "ValueRef", "value": "shared_model"}
    assert translator.evaluate(model_reference, translator._root_env, 1) is model
    assert translator.evaluate(model_reference, translator._root_env, 1) is model
    assert translator._root_value_cache["shared_model"] is model

    translator.scope["mapped_value"] = {
        "type": "ArgumentRef", "value": "table",
    }
    mapped = {"type": "ValueRef", "value": "mapped_value"}
    function = translator.evaluate({
        "type": "Function", "argumentNames": ["table"], "body": mapped,
    }, translator._root_env, 1)
    assert isinstance(function, Function)
    first = SampledFeatures(Image([], {}), "first")
    second = SampledFeatures(Image([], {}), "second")
    assert translator.evaluate(
        function.body, {**function.env, "table": first}, 2,
    ) is first
    assert translator.evaluate(
        function.body, {**function.env, "table": second}, 2,
    ) is second
    assert "mapped_value" not in translator._root_value_cache

    for _ in range(50_000 - translator.steps):
        assert translator.evaluate(reference, translator._root_env, 1) is sample
    assert translator.steps == 50_000
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        translator.evaluate(reference, translator._root_env, 1)


def test_feature_collection_classify_lowers_canonical_rows_and_opaque_model(ee):
    classifier = trained(ee)
    query = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([1, 1]), {
            "actual": 1, "nir": 0.75, "red": 0.65, "note": "retained",
        }),
        ee.Feature(None, {"actual": 0, "nir": 0.25, "red": 0.15, "note": "second"}),
    ])

    result = compile_value(ee, query.classify(classifier, "predicted"))
    assert result["kind"] == "runtime_table"
    assert result["bands"] == [
        "system:index", "actual", "nir", "red", "note", "predicted", ".geo",
    ]
    # Header order comes from the evaluated FeatureCollection, not the sorted
    # keys in its canonical JSON wire payload.
    assert result["bands"].index("red") < result["bands"].index("note")
    trainer = process_nodes(result, "local_ee_train_smile_rf_rows")
    classify = process_nodes(result, "local_ee_smile_rf_classify_rows")
    assert len(trainer) == len(classify) == 1
    trainer_id, _ = trainer[0]
    _, node = classify[0]
    assert set(node["arguments"]) == {"rows", "spec", "model"}
    assert node["arguments"]["model"] == {"from_node": trainer_id}
    rows = decode_feature_rows(node["arguments"]["rows"])
    assert rows["features"][0]["geometry"] == {
        "type": "Point", "coordinates": [1, 1],
    }
    spec = decode_classify_spec(node["arguments"]["spec"])
    assert spec["output_name"] == "predicted"
    assert spec["columns"] == result["bands"]
    assert all("predicted" not in feature["properties"]
               for feature in rows["features"])


def test_empty_literal_prediction_keeps_empty_rows_and_accepts_explicit_matrix_order(ee):
    classifier = trained(ee)
    classified = ee.FeatureCollection([]).classify(classifier, "predicted")
    result = compile_value(ee, classified)
    assert result["bands"] == ["system:index", "predicted", ".geo"]
    classify = process_nodes(result, "local_ee_smile_rf_classify_rows")
    assert len(classify) == 1
    rows = decode_feature_rows(classify[0][1]["arguments"]["rows"])
    assert rows["features"] == []
    assert decode_classify_spec(classify[0][1]["arguments"]["spec"])["columns"] == result["bands"]

    explicit = classified.errorMatrix("actual", "predicted", [0, 1]).array()
    matrix = compile_value(ee, explicit)
    error = process_nodes(matrix, "local_ee_error_matrix")
    assert len(error) == 1
    assert decode_matrix_spec(error[0][1]["arguments"]["spec"]) == {
        "version": 1, "actual": "actual", "predicted": "predicted", "order": [0, 1],
    }

    without_order = classified.errorMatrix("actual", "predicted")
    with pytest.raises(UnsupportedEEError, match="explicit order for an empty"):
        compile_value(ee, without_order.array())


def test_rf_resubstitution_and_classified_error_metrics_are_lazy(ee):
    classifier = trained(ee)
    resubstitution = classifier.confusionMatrix()
    train_accuracy = compile_value(ee, resubstitution.accuracy())
    assert train_accuracy["kind"] == "runtime_value"
    train_confusion = process_nodes(train_accuracy, "local_ee_smile_rf_confusion")
    train_metric = process_nodes(train_accuracy, "local_ee_confusion_value")
    assert len(train_confusion) == len(train_metric) == 1
    assert decode_metric_spec(train_metric[0][1]["arguments"]["spec"])["operation"] == "accuracy"
    train_node = process_nodes(train_accuracy, "local_ee_train_smile_rf_rows")[0][0]
    assert train_confusion[0][1]["arguments"] == {"model": {"from_node": train_node}}

    query = ee.FeatureCollection([
        ee.Feature(None, {"actual": 1, "nir": 0.75, "red": 0.65}),
        ee.Feature(None, {"actual": 0, "nir": 0.25, "red": 0.15}),
    ])
    matrix = query.classify(classifier, "predicted").errorMatrix(
        "actual", "predicted", [1, 0],
    )
    result = compile_value(ee, matrix.fscore(beta=2))
    assert result["kind"] == "runtime_value"
    error_matrix = process_nodes(result, "local_ee_error_matrix")
    metric = process_nodes(result, "local_ee_confusion_value")
    assert len(error_matrix) == len(metric) == 1
    matrix_spec = decode_matrix_spec(error_matrix[0][1]["arguments"]["spec"])
    assert matrix_spec == {
        "version": 1, "actual": "actual", "predicted": "predicted", "order": [1, 0],
    }
    assert decode_metric_spec(metric[0][1]["arguments"]["spec"]) == {
        "version": 1, "operation": "fscore", "beta": 2,
    }
    classified_ref = error_matrix[0][1]["arguments"]["data"]
    assert set(classified_ref) == {"from_node"}
    classified = result["process_graph"][classified_ref["from_node"]]
    assert classified["process_id"] == "local_ee_smile_rf_classify_rows"
    assert result["source_item_ids"] == []


def test_sampled_feature_prediction_keeps_training_and_query_branches_separate(ee, local):
    def sample_regions(offset=0):
        regions = ee.FeatureCollection([
            ee.Feature(ee.Geometry.Point([0.5 + offset, 0.5]), {"actual": 0}),
            ee.Feature(ee.Geometry.Point([1.5 + offset, 1.5]), {"actual": 1}),
        ])
        return ee.Image("training-scene").select(["red", "nir"]).sampleRegions(
            collection=regions, properties=["actual"], geometries=False,
            scale=10, projection=ee.Projection("EPSG:32610"),
        ).filter(ee.Filter.gte("nir", 0)).limit(20)

    classifier = trained(ee, sample_regions())
    query = sample_regions(0.1)
    result = compile_value(ee, query.classify(classifier, "predicted"), local)
    assert result["kind"] == "runtime_table"
    assert len(process_nodes(result, "local_ee_sample_regions")) == 2
    assert len(process_nodes(result, "local_ee_sample_table_op")) == 4
    trainers = process_nodes(result, "local_ee_train_smile_rf_samples")
    predictors = process_nodes(result, "local_ee_smile_rf_classify_samples")
    assert len(trainers) == len(predictors) == 1
    trainer_id, _ = trainers[0]
    assert predictors[0][1]["arguments"]["model"] == {"from_node": trainer_id}
    assert result["source_item_ids"] == ["training-scene"]
    assert result["bands"] == [
        "system:index", "actual", "red", "nir", "predicted", ".geo",
    ]


def test_sampled_training_predictions_reuse_the_trainer_sample_table(ee, local):
    regions = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([0.5, 0.5]), {"actual": 0}),
        ee.Feature(ee.Geometry.Point([1.5, 1.5]), {"actual": 1}),
    ])
    samples = ee.Image("training-scene").select(["red", "nir"]).sampleRegions(
        collection=regions, properties=["actual"], geometries=False,
        scale=10, projection=ee.Projection("EPSG:32610"),
    ).filter(ee.Filter.gte("nir", 0)).limit(20)
    classifier = trained(ee, samples)

    expression = encode(ee, samples.classify(classifier, "predicted"))
    translator = Translator(local[0], local[1], {})
    table = translator.evaluate(expression)
    assert table.source is table.classifier.samples
    image = table.source.image
    bands_before = list(image.bands)
    props_before = dict(image.props)
    source_before = image.source
    result = compile_runtime_table(table, translator)
    validate(result["process_graph"])
    assert image.bands == bands_before
    assert image.props == props_before
    assert image.source is source_before

    trainers = process_nodes(result, "local_ee_train_smile_rf_samples")
    predictors = process_nodes(result, "local_ee_smile_rf_classify_samples")
    assert len(trainers) == len(predictors) == 1
    assert len(process_nodes(result, "local_ee_sample_regions")) == 1
    assert len(process_nodes(result, "local_ee_sample_table_op")) == 2
    training_table = trainers[0][1]["arguments"]["data"]
    prediction_table = predictors[0][1]["arguments"]["data"]
    assert training_table == prediction_table


def test_sampled_feature_error_matrix_is_lazy_and_empty_samples_need_order(ee, local):
    regions = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([0.5, 0.5]), {"actual": 0, "predicted": 0}),
        ee.Feature(ee.Geometry.Point([1.5, 1.5]), {"actual": 1, "predicted": 0}),
    ])
    samples = ee.Image("training-scene").select(["red", "nir"]).sampleRegions(
        collection=regions, properties=["actual", "predicted"],
        geometries=False, scale=10, projection=ee.Projection("EPSG:32610"),
    )
    result = compile_value(
        ee, samples.errorMatrix("actual", "predicted", [0, 1]).accuracy(), local,
    )
    error = process_nodes(result, "local_ee_error_matrix")
    sampled = process_nodes(result, "local_ee_sample_regions")
    metric = process_nodes(result, "local_ee_confusion_value")
    assert len(error) == len(sampled) == len(metric) == 1
    assert error[0][1]["arguments"]["data"] == {"from_node": sampled[0][0]}
    assert decode_matrix_spec(error[0][1]["arguments"]["spec"]) == {
        "version": 1, "actual": "actual", "predicted": "predicted", "order": [0, 1],
    }

    empty_samples = samples.limit(0)
    empty_matrix = empty_samples.errorMatrix("actual", "predicted")
    with pytest.raises(UnsupportedEEError, match="explicit order for an empty"):
        compile_value(ee, empty_matrix.accuracy(), local)

    empty_with_order = empty_samples.errorMatrix("actual", "predicted", [0, 1])
    result = compile_value(ee, empty_with_order.accuracy(), local)
    assert len(process_nodes(result, "local_ee_error_matrix")) == 1


@pytest.mark.parametrize("mutation", ["collision", "missing", "nonnumeric"])
def test_static_rf_prediction_rejects_invalid_query_rows(ee, mutation):
    classifier = trained(ee)
    properties = {"actual": 0, "nir": 0.2, "red": 0.1}
    if mutation == "collision":
        properties["predicted"] = 99
    elif mutation == "missing":
        del properties["red"]
    elif mutation == "nonnumeric":
        properties["red"] = "red"
    query = ee.FeatureCollection([ee.Feature(None, properties)])
    expression = encode(ee, query.classify(classifier, "predicted"))
    with pytest.raises(UnsupportedEEError):
        compile_expression(expression, [], {})


def test_runtime_matrices_cannot_escape_as_direct_or_nested_outputs(ee):
    classifier = trained(ee)
    with pytest.raises(UnsupportedEEError, match=r"requires array\(\)"):
        compile_value(ee, classifier.confusionMatrix())
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, ee.Dictionary({"score": classifier.confusionMatrix().accuracy()}))


def test_dynamic_matrix_checks_known_columns_and_metric_arguments(ee):
    classifier = trained(ee)
    query = ee.FeatureCollection([
        ee.Feature(None, {"actual": 0, "nir": 0.2, "red": 0.1}),
    ]).classify(classifier, "predicted")
    bad_property = query.errorMatrix("missing", "predicted")
    with pytest.raises(UnsupportedEEError, match="property is missing"):
        compile_value(ee, bad_property.accuracy())

    bad_order = query.errorMatrix("actual", "predicted", [0, 0])
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, bad_order.accuracy())

    invalid_beta = query.errorMatrix("actual", "predicted", [0, 1]).fscore(beta=0)
    with pytest.raises(UnsupportedEEError, match="beta"):
        compile_value(ee, invalid_beta)
