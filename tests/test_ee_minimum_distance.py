"""Pinned Python SDK and independent controls for minimum-distance classifiers."""
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def output(ee, value):
    return compile_expression(encode(ee, value), [], {})["value"]


def invocation_names(expression):
    return [node["functionName"] for _, node in expression.get("scope", [])
            if isinstance(node, dict) and node.get("type") == "Invocation"]


def add_unknown_argument(expression, function_name):
    result = deepcopy(expression)
    candidates = result.get("scope", [])
    for _, node in reversed(candidates):
        if isinstance(node, dict) and node.get("functionName") == function_name:
            node["arguments"]["unexpected"] = 1
            return result
    if result.get("functionName") == function_name:
        result["arguments"]["unexpected"] = 1
        return result
    raise AssertionError(f"No {function_name} invocation in SDK serialization")


TRAINING = [
    {"east": 0, "north": 0, "actual": 1},
    {"east": 2, "north": 0, "actual": 1},
    {"east": 10, "north": 10, "actual": 1},
    {"east": 5, "north": 5, "actual": 3},
    {"east": 6, "north": 6, "actual": 3},
]

# These held-out labels intentionally disagree with the classifier at both
# points: validation labels are not folded into the training means.
VALIDATION = [
    {"east": 5.5, "north": 5.5, "actual": 1,
     "system:index": "held-out-a", "note": "kept-a"},
    {"east": 0, "north": 0, "actual": 3,
     "system:index": "held-out-b", "note": "kept-b"},
]


def feature_collection(ee, rows, geometries=None):
    geometries = [None] * len(rows) if geometries is None else geometries
    return ee.FeatureCollection([
        ee.Feature(geometry, row)
        for row, geometry in zip(rows, geometries)
    ])


def train(ee, rows=TRAINING, schema=("north", "east"), *,
          class_property="actual", metric="euclidean", k_nearest=1,
          mode="CLASSIFICATION", subsampling=1, seed=0):
    model = ee.Classifier.minimumDistance(
        metric=metric, kNearest=k_nearest,
    ).train(
        features=feature_collection(ee, rows),
        classProperty=class_property,
        inputProperties=schema,
        subsampling=subsampling,
        subsamplingSeed=seed,
    )
    return model.setOutputMode(mode) if mode is not None else model


def test_sdk_training_classification_and_resubstitution_match_independent_reference(ee):
    model = train(ee)
    validation = feature_collection(ee, VALIDATION)
    predicted = validation.classify(model, "predicted")
    validation_matrix = predicted.errorMatrix("actual", "predicted", [1, 3])
    result = ee.Dictionary({
        "schema": model.schema(),
        "train_confusion": model.confusionMatrix().array(),
        "train_accuracy": model.confusionMatrix().accuracy(),
        "train_kappa": model.confusionMatrix().kappa(),
        "predictions": predicted.aggregate_array("predicted"),
        "validation_confusion": validation_matrix.array(),
    })

    expression = encode(ee, result)
    names = set(invocation_names(expression))
    assert {
        "Classifier.minimumDistance", "Classifier.train", "Classifier.schema",
        "Classifier.setOutputMode", "Classifier.confusionMatrix",
        "FeatureCollection.classify", "Collection.errorMatrix",
    } <= names
    value = compile_expression(expression, [], {})["value"]

    # Independent NumPy reference: the ordered class means are (10/3, 4) and
    # (5.5, 5.5) in (north, east) coordinates. The training outlier (10,10)
    # belongs to class 1 but is closer to the class-3 mean, proving this is a
    # nearest-mean model rather than nearest-neighbour classification.
    labels = np.array([1, 3])
    means = np.array([
        [np.mean([row[name] for row in TRAINING if row["actual"] == label])
         for name in ("north", "east")]
        for label in labels
    ])
    samples = np.array([[row[name] for name in ("north", "east")]
                        for row in VALIDATION])
    distances = np.sum((samples[:, None, :] - means[None, :, :]) ** 2, axis=2)
    assert np.all(distances[:, 0] != distances[:, 1])
    assert labels[np.argmin(distances, axis=1)].tolist() == [3, 1]
    assert value["schema"] == ["north", "east"]
    assert value["train_confusion"] == [
        [0, 0, 0, 0],
        [0, 2, 0, 1],
        [0, 0, 0, 0],
        [0, 0, 0, 2],
    ]
    # N=5, trace=4, row totals (3,2), column totals (2,3):
    # kappa=(5*4 - (3*2 + 2*3))/(5**2 - (3*2 + 2*3)) = 8/13.
    assert value["train_accuracy"] == 4 / 5
    assert value["train_kappa"] == 8 / 13
    assert value["predictions"] == [3, 1]
    assert value["validation_confusion"] == [[0, 1], [1, 0]]


def test_classify_default_name_preserves_source_features_and_does_not_mutate_them(ee):
    model = train(ee)
    coordinates = [[12, 34], [-2, 7]]
    geometries = [ee.Geometry.Point(point) for point in coordinates]
    rows = [
        {**VALIDATION[0], "system:index": "default-a"},
        {**VALIDATION[1], "system:index": "default-b"},
    ]
    features = feature_collection(ee, rows, geometries)
    classified = features.classify(model)
    value = output(ee, ee.Dictionary({"source": features, "classified": classified}))

    original = value["source"]["features"]
    result = value["classified"]["features"]
    assert [feature["properties"]["classification"] for feature in result] == [3, 1]
    assert all("classification" not in feature["properties"] for feature in original)
    for index, (before, after, row) in enumerate(zip(original, result, rows)):
        assert before["properties"] == row
        assert after["properties"] == {**row, "classification": [3, 1][index]}
        assert after["geometry"] == {"type": "Point", "coordinates": coordinates[index]}


def test_untrained_schema_is_none_and_explicit_schema_order_is_retained(ee):
    assert output(ee, ee.Classifier.minimumDistance().schema()) is None
    model = train(ee, schema=("east", "north"))
    assert output(ee, model.schema()) == ["east", "north"]

    # With omitted constructor/training defaults, the pinned SDK omits the
    # optional wire arguments and the backend uses Euclidean, k=1, no sampling.
    defaults = ee.Classifier.minimumDistance().train(
        features=feature_collection(ee, TRAINING),
        classProperty="actual",
        inputProperties=["east", "north"],
    )
    before_and_after = output(ee, ee.Dictionary({
        "before": defaults.schema(),
        "after": defaults.setOutputMode("CLASSIFICATION").schema(),
    }))
    assert before_and_after == {"before": ["east", "north"], "after": ["east", "north"]}
    unsupported_clone = defaults.setOutputMode("PROBABILITY")
    with pytest.raises(UnsupportedEEError, match="CLASSIFICATION"):
        output(ee, unsupported_clone.schema())
    assert output(ee, defaults.schema()) == ["east", "north"]


def test_eight_unique_flat_input_properties_are_supported_in_declared_order(ee):
    schema = tuple(f"p{index}" for index in range(8))
    row = {name: index + 0.25 for index, name in enumerate(schema)}
    row["actual"] = 2
    model = train(ee, [row], schema=schema)
    assert output(ee, model.schema()) == list(schema)


def test_dictionary_and_if_type_round_trips_keep_the_typed_classifier(ee):
    model = train(ee)
    from_dictionary = ee.Classifier(
        ee.Dictionary({"selected": model}).get("selected")
    )
    from_if = ee.Classifier(ee.Algorithms.If(True, model, model))

    dictionary_expression = encode(ee, from_dictionary.schema())
    if_expression = encode(ee, from_if.confusionMatrix().array())
    assert "Dictionary.get" in invocation_names(dictionary_expression)
    # The pinned legacy serializer names the algorithm simply "If".
    assert "If" in invocation_names(if_expression)
    assert compile_expression(dictionary_expression, [], {})["value"] == ["north", "east"]
    assert compile_expression(if_expression, [], {})["value"] == [
        [0, 0, 0, 0], [0, 2, 0, 1], [0, 0, 0, 0], [0, 0, 0, 2]
    ]


def test_direct_nested_json_and_truth_coercion_of_classifier_are_rejected(ee):
    model = train(ee)
    with pytest.raises(UnsupportedEEError, match="direct server-object JSON is unsupported"):
        output(ee, model)
    with pytest.raises(UnsupportedEEError, match="Unsupported internal value"):
        output(ee, ee.Dictionary({"nested": [model]}))
    with pytest.raises(UnsupportedEEError, match="static scalar/list/dictionary condition"):
        output(ee, ee.Algorithms.If(model, 1, 0))


def test_equal_distance_predictions_and_missing_image_schema_are_rejected(ee):
    tied_training = [
        {"x": 0, "actual": 1},
        {"x": 2, "actual": 3},
    ]
    model = train(ee, tied_training, schema=("x",))
    tied = feature_collection(ee, [{"x": 1}]).classify(model)
    with pytest.raises(UnsupportedEEError, match="equal-distance class centers"):
        output(ee, tied)

    image_classification = ee.Image.constant(1).classify(model)
    with pytest.raises(UnsupportedEEError, match="missing classifier schema band"):
        output(ee, image_classification)


@pytest.mark.parametrize(("metric", "k_nearest"), [
    ("mahalanobis", 1),
    ("", 1),
    (False, 1),
    (1, 1),
    ("euclidean", 2),
    ("euclidean", 0),
    ("euclidean", False),
])
def test_unsupported_metric_and_non_one_k_nearest_constructor_arguments_are_rejected(
        ee, metric, k_nearest):
    classifier = ee.Classifier.minimumDistance(metric=metric, kNearest=k_nearest)
    with pytest.raises(UnsupportedEEError):
        output(ee, classifier.schema())


def test_only_classification_output_mode_is_supported(ee):
    model = ee.Classifier.minimumDistance().setOutputMode("PROBABILITY")
    with pytest.raises(UnsupportedEEError, match="CLASSIFICATION"):
        output(ee, model.schema())


@pytest.mark.parametrize("subsampling,seed", [
    (0.5, 0),
    (0, 0),
    (True, 0),
    (1, 1),
    (1, False),
])
def test_training_rejects_nondefault_subsampling_and_seed(ee, subsampling, seed):
    model = train(ee, subsampling=subsampling, seed=seed)
    with pytest.raises(UnsupportedEEError):
        output(ee, model.schema())


def test_training_rejects_missing_or_empty_schema_and_bad_names(ee):
    rows = TRAINING
    for schema in (None, [], ["north", "north"], [""], ["north", 1], [["north"]],
                   list("123456789"), ["north.value"]):
        model = train(ee, rows, schema=schema)
        with pytest.raises(UnsupportedEEError):
            output(ee, model.schema())

    for class_property in ("", "actual.value"):
        model = train(ee, rows, class_property=class_property)
        with pytest.raises(UnsupportedEEError):
            output(ee, model.schema())


@pytest.mark.parametrize("row", [
    {"east": 0, "north": 0},
    {"east": 0, "north": 0, "actual": None},
    {"east": 0, "actual": 1},
    {"east": None, "north": 0, "actual": 1},
    {"east": "0", "north": 0, "actual": 1},
    {"east": True, "north": 0, "actual": 1},
    {"east": float("nan"), "north": 0, "actual": 1},
    {"east": float("inf"), "north": 0, "actual": 1},
    {"east": 2**53 + 1, "north": 0, "actual": 1},
])
def test_training_rejects_missing_null_non_numeric_boolean_nonfinite_or_inexact_values(ee, row):
    model = train(ee, [row])
    with pytest.raises(UnsupportedEEError):
        output(ee, model.schema())


@pytest.mark.parametrize("label", [None, "1", True, -1, 64, 1.5])
def test_training_rejects_invalid_class_labels(ee, label):
    model = train(ee, [{"east": 0, "north": 0, "actual": label}])
    with pytest.raises(UnsupportedEEError, match="class labels must be integers"):
        output(ee, model.schema())


def test_integer_valued_float_labels_and_exact_float64_feature_boundary_are_accepted(ee):
    rows = [{"x": 2**53, "actual": 63.0}]
    model = train(ee, rows, schema=("x",))
    matrix = output(ee, model.confusionMatrix().array())
    assert len(matrix) == 64 and all(len(row) == 64 for row in matrix)
    assert matrix[63][63] == 1


def test_class_labels_cannot_exceed_the_64_class_axis(ee):
    model = train(ee, [{"x": 0, "actual": 64}], schema=("x",))
    with pytest.raises(UnsupportedEEError, match="0 through 63"):
        output(ee, model.schema())


def test_training_accepts_1000_inline_features_and_rejects_1001(ee):
    rows = [{"x": index, "actual": 0} for index in range(1000)]
    assert output(ee, train(ee, rows, schema=("x",)).schema()) == ["x"]

    too_many = [{"x": index, "actual": 0} for index in range(1001)]
    with pytest.raises(UnsupportedEEError, match="1..1000 inline Features"):
        output(ee, train(ee, too_many, schema=("x",)).schema())


def test_classify_rejects_output_name_collision_and_invalid_names(ee):
    model = train(ee)
    for rows, output_name in [
        ([{"north": 0, "east": 0, "classification": 9}], None),
        ([{"north": 0, "east": 0, "predicted": 9}], "predicted"),
        ([{"north": 0, "east": 0}], ""),
        ([{"north": 0, "east": 0}], "predicted.value"),
        ([{"north": 0, "east": 0}], 2),
    ]:
        classified = feature_collection(ee, rows).classify(model, output_name)
        with pytest.raises(UnsupportedEEError):
            output(ee, classified)


def test_classify_rejects_missing_model_properties(ee):
    model = train(ee)
    for row in ({"north": 0},):
        with pytest.raises(UnsupportedEEError):
            output(ee, feature_collection(ee, [row]).classify(model))


@pytest.mark.parametrize("value", [
    None, "0", True, float("nan"), float("inf"), 2**53 + 1,
])
def test_classify_rejects_null_non_numeric_boolean_nonfinite_or_inexact_features(ee, value):
    model = train(ee)
    row = {"north": 0, "east": value}
    with pytest.raises(UnsupportedEEError):
        output(ee, feature_collection(ee, [row]).classify(model))


def test_classify_inline_feature_limit_is_enforced(ee):
    model = train(ee)
    rows = [{"north": 0, "east": 0} for _ in range(1001)]
    with pytest.raises(UnsupportedEEError, match="at most 1000 features"):
        output(ee, feature_collection(ee, rows).classify(model))


def test_classifier_schema_training_classification_and_confusion_reject_unknown_wire_arguments(ee):
    untrained = ee.Classifier.minimumDistance()
    model = train(ee)
    features = feature_collection(ee, VALIDATION)
    expressions = [
        (encode(ee, untrained.schema()), "Classifier.schema"),
        (encode(ee, model.schema()), "Classifier.schema"),
        (encode(ee, model.confusionMatrix().array()), "Classifier.confusionMatrix"),
        (encode(ee, features.classify(model).aggregate_array("classification")),
         "FeatureCollection.classify"),
        (encode(ee, model.setOutputMode("CLASSIFICATION").schema()), "Classifier.setOutputMode"),
        (encode(ee, ee.Classifier.minimumDistance().train(
            feature_collection(ee, TRAINING), "actual", ["east", "north"]).schema()),
         "Classifier.train"),
        (encode(ee, ee.Classifier.minimumDistance(metric="euclidean", kNearest=1).schema()),
         "Classifier.minimumDistance"),
    ]
    for expression, name in expressions:
        malformed = add_unknown_argument(expression, name)
        with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
            compile_expression(malformed, [], {})


def test_other_classifier_methods_are_not_silently_supported(ee):
    model = train(ee)
    with pytest.raises(UnsupportedEEError, match="trained Smile RandomForest"):
        output(ee, model.explain())


def test_classifier_training_work_is_bounded(ee):
    schema = tuple(f"x{index}" for index in range(8))
    rows = [
        {**{name: index for name in schema}, "actual": 0}
        for index in range(1000)
    ]
    model = train(ee, rows, schema=schema)
    with pytest.raises(UnsupportedEEError, match="budget|compilation limits"):
        output(ee, model.schema())
