"""Offline synthetic validation for trained minimum-distance metrics."""
from decimal import Decimal, localcontext
from fractions import Fraction
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-distance-metric-validation-v1.json"


def fixture():
    return json.loads(FIXTURE_PATH.read_text())


def example_module():
    spec = importlib.util.spec_from_file_location(
        "distance_metric_validation_example",
        ROOT / "examples/26_GEE_python_distance_metric_validation.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def independent_reference(data, metric):
    """Use independent NumPy/Python and Decimal geometry plus exact counts."""
    properties = data["input_properties"]
    class_order = data["class_order"]
    label_name = data["class_property"]
    training = data["training"]
    validation = data["validation"]

    means = {}
    for label in class_order:
        members = [row for row in training if row[label_name] == label]
        means[label] = tuple(
            sum(Fraction.from_float(float(row[name])) for row in members) / len(members)
            for name in properties
        )

    def predict(rows):
        vectors = np.asarray(
            [[float(row[name]) for name in properties] for row in rows],
            dtype=np.float64,
        )
        center_values = np.asarray(
            [[float(value) for value in means[label]] for label in class_order],
            dtype=np.float64,
        )
        if metric == "euclidean":
            distances = np.sum(
                (vectors[:, None, :] - center_values[None, :, :]) ** 2, axis=2,
            )
            assert np.all(distances[:, 0] != distances[:, 1])
            return [class_order[index] for index in np.argmin(distances, axis=1)]
        if metric == "manhattan":
            distances = np.sum(
                np.abs(vectors[:, None, :] - center_values[None, :, :]), axis=2,
            )
            assert np.all(distances[:, 0] != distances[:, 1])
            return [class_order[index] for index in np.argmin(distances, axis=1)]

        def decimal_fraction(value):
            return Decimal(value.numerator) / Decimal(value.denominator)

        with localcontext() as context:
            context.prec = 100
            decimal_centers = [
                [decimal_fraction(value) for value in means[label]]
                for label in class_order
            ]
            labels = []
            for row in rows:
                query = [Decimal.from_float(float(row[name])) for name in properties]
                query_norm = sum(value * value for value in query).sqrt()
                assert query_norm != 0
                scores = []
                for center in decimal_centers:
                    center_norm = sum(value * value for value in center).sqrt()
                    assert center_norm != 0
                    dot = sum(left * right for left, right in zip(query, center))
                    scores.append(dot / (query_norm * center_norm))
                assert scores[0] != scores[1]
                labels.append(class_order[max(range(len(scores)), key=scores.__getitem__)])
            return labels

    validation_predictions = predict(validation)
    training_predictions = predict(training)

    def confusion(rows, predictions):
        return [
            [
                sum(row[label_name] == actual and predicted == expected
                    for row, predicted in zip(rows, predictions))
                for expected in class_order
            ]
            for actual in class_order
        ]

    train_matrix = confusion(training, training_predictions)
    matrix = confusion(validation, validation_predictions)
    row_totals = [sum(row) for row in matrix]
    column_totals = [sum(matrix[row][column] for row in range(len(class_order)))
                     for column in range(len(class_order))]
    accuracy = Fraction(sum(matrix[i][i] for i in range(len(class_order))), len(validation))
    consumers = [Fraction(matrix[i][i], row_totals[i]) for i in range(len(class_order))]
    producers = [Fraction(matrix[i][i], column_totals[i]) for i in range(len(class_order))]

    def fscore(beta):
        beta_squared = beta * beta
        return [
            (1 + beta_squared) * matrix[i][i]
            / (beta_squared * row_totals[i] + column_totals[i])
            for i in range(len(class_order))
        ]

    return {
        "predictions": validation_predictions,
        "training_confusion": train_matrix,
        "validation_confusion": matrix,
        "accuracy": accuracy,
        "consumers_accuracy": consumers,
        "producers_accuracy": producers,
        "fscore": fscore(Fraction(1)),
        "fscore_beta2": fscore(Fraction(2)),
    }


def test_offline_sdk_workflow_matches_hand_pinned_and_independent_metric_references():
    data = fixture()
    example = example_module()
    assert example.SYNTHETIC_VERSION == data["schema"]
    assert example.INPUT_PROPERTIES == data["input_properties"]
    assert example.CLASS_PROPERTY == data["class_property"]
    assert example.CLASS_ORDER == data["class_order"]
    assert example.PREDICTION_PROPERTY == data["prediction_property"]
    assert list(example.DISTANCE_METRICS) == data["distance_metrics"]
    assert example.TRAINING_ROWS == data["training"]
    assert example.VALIDATION_ROWS == data["validation"]

    source_training = json.loads(json.dumps(data["training"]))
    source_validation = json.loads(json.dumps(data["validation"]))
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        training = ee.FeatureCollection([
            ee.Feature(None, row) for row in example.TRAINING_ROWS
        ])
        validation = ee.FeatureCollection([
            ee.Feature(None, row) for row in example.VALIDATION_ROWS
        ])
        expression = ee.serializer.encode(
            example.build_all_validations(ee, training, validation),
            for_cloud_api=False,
        )
        invocation_nodes = [
            node for _, node in expression.get("scope", [])
            if isinstance(node, dict) and node.get("type") == "Invocation"
        ]
        assert {
            "Classifier.minimumDistance", "Classifier.train", "Classifier.schema",
            "Classifier.confusionMatrix", "FeatureCollection.classify",
            "Collection.errorMatrix", "ConfusionMatrix.accuracy",
            "ConfusionMatrix.fscore",
        } <= {node["functionName"] for node in invocation_nodes}
        assert {
            node.get("arguments", {}).get("metric")
            for node in invocation_nodes
            if node.get("functionName") == "Classifier.minimumDistance"
        } == set(data["distance_metrics"])
        value = compile_expression(expression, [], {})["value"]

    assert guard.evidence()["attempt_count"] == 0
    assert example.TRAINING_ROWS == source_training
    assert example.VALIDATION_ROWS == source_validation
    assert value["training_before"] == value["training_after"]
    assert value["validation_before"] == value["validation_after"]
    assert [feature["properties"] for feature in value["training_after"]["features"]] == data["training"]
    assert [feature["properties"] for feature in value["validation_after"]["features"]] == data["validation"]

    for metric in data["distance_metrics"]:
        expected = data["independent_reference"][metric]
        reference = independent_reference(data, metric)
        assert reference["predictions"] == expected["predictions"]
        assert reference["training_confusion"] == expected["training_confusion"]
        assert reference["validation_confusion"] == expected["validation_confusion"]
        for key in ("accuracy", "consumers_accuracy", "producers_accuracy", "fscore", "fscore_beta2"):
            assert [str(item) for item in ([reference[key]] if key == "accuracy" else reference[key])] == (
                [expected[key]] if key == "accuracy" else expected[key]
            )

        result = value["by_metric"][metric]
        assert result["schema"] == data["input_properties"]
        assert result["training_confusion"] == expected["training_confusion"]
        assert result["validation_sample_ids"] == [row["sample_id"] for row in data["validation"]]
        assert result["predictions"] == expected["predictions"]
        assert result["validation_confusion"] == expected["validation_confusion"]
        assert result["accuracy"] == pytest.approx(float(Fraction(expected["accuracy"])), abs=1e-15)
        for key in ("consumers_accuracy", "producers_accuracy", "fscore", "fscore_beta2"):
            assert result[key] == pytest.approx(
                [float(Fraction(item)) for item in expected[key]], abs=1e-15,
            )
        for feature, row, prediction in zip(
                result["classified_features"]["features"],
                data["validation"], expected["predictions"]):
            assert feature["properties"] == {**row, "predicted": prediction}
            assert list(feature["properties"]) == list(row) + ["predicted"]


def test_independent_reference_covers_positive_scale_and_signed_cosine_direction():
    data = fixture()
    diagonal_small, diagonal_large = data["validation"][:2]
    assert diagonal_large["nir"] == 8 * diagonal_small["nir"]
    assert diagonal_large["red"] == 8 * diagonal_small["red"]
    assert independent_reference(data, "cosine")["predictions"][:2] == [1, 1]
    assert independent_reference(data, "manhattan")["predictions"][:2] == [0, 1]
    assert independent_reference(data, "cosine")["predictions"][4] == 0


def test_cosine_rejects_zero_norm_queries_centers_and_ambiguous_ties_offline():
    data = fixture()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        standard_training = ee.FeatureCollection([
            ee.Feature(None, row) for row in data["training"]
        ])
        zero_query = ee.FeatureCollection([
            ee.Feature(None, {"nir": 0, "red": 0, "landcover": 0})
        ])
        query_model = ee.Classifier.minimumDistance(metric="cosine", kNearest=1).train(
            standard_training, "landcover", data["input_properties"],
        )
        with pytest.raises(UnsupportedEEError, match="zero-norm query"):
            compile_expression(
                ee.serializer.encode(zero_query.classify(query_model), for_cloud_api=False),
                [], {},
            )

        zero_center_training = ee.FeatureCollection([
            ee.Feature(None, {"nir": 0, "red": 0, "landcover": 0}),
            ee.Feature(None, {"nir": 2, "red": 0, "landcover": 1}),
        ])
        nonzero_query = ee.FeatureCollection([
            ee.Feature(None, {"nir": 1, "red": 0, "landcover": 1})
        ])
        center_model = ee.Classifier.minimumDistance(metric="cosine", kNearest=1).train(
            zero_center_training, "landcover", data["input_properties"],
        )
        with pytest.raises(UnsupportedEEError, match="zero-norm class center"):
            compile_expression(
                ee.serializer.encode(nonzero_query.classify(center_model), for_cloud_api=False),
                [], {},
            )

        tied_training = ee.FeatureCollection([
            ee.Feature(None, {"nir": 1, "red": 0, "landcover": 0}),
            ee.Feature(None, {"nir": 2, "red": 0, "landcover": 1}),
        ])
        tied_query = ee.FeatureCollection([
            ee.Feature(None, {"nir": 3, "red": 0, "landcover": 1})
        ])
        tied_model = ee.Classifier.minimumDistance(metric="cosine", kNearest=1).train(
            tied_training, "landcover", data["input_properties"],
        )
        with pytest.raises(UnsupportedEEError, match="equal-distance class centers"):
            compile_expression(
                ee.serializer.encode(tied_query.classify(tied_model), for_cloud_api=False),
                [], {},
            )

    assert guard.evidence()["attempt_count"] == 0
