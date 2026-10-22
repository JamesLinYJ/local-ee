"""Pinned per-class ConfusionMatrix metrics and offline numerical controls."""
from fractions import Fraction
from pathlib import Path

import pytest
import numpy as np

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


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


MATRIX = [[5, 1, 0], [2, 3, 1], [0, 1, 4]]


def confusion_matrix(ee, matrix=MATRIX):
    return ee.ConfusionMatrix(ee.Array(matrix), [10, -1, 3])


@pytest.mark.parametrize("used_work", [0, 42_000])
def test_fscore_charges_both_matrix_scans_before_processing(used_work):
    from gee.compat.earthengine.array_core import wrap_array
    from gee.compat.earthengine.confusion_values import invoke_confusion, make_confusion
    from gee.compat.earthengine.decoder import Translator

    translator = Translator([], {}, {})
    matrix = make_confusion(translator, wrap_array(np.eye(64, dtype=np.int64)))
    translator.steps = used_work
    if used_work:
        with pytest.raises(UnsupportedEEError, match="budget"):
            invoke_confusion(translator, "ConfusionMatrix.fscore", {"confusionMatrix": matrix})
    else:
        result = invoke_confusion(translator, "ConfusionMatrix.fscore", {"confusionMatrix": matrix})
        assert result.data.tolist() == [1.0] * 64
        assert translator.steps == 2 * 64 * 64 + 64


def accuracy_reference(matrix, *, rows):
    classes = len(matrix)
    return [
        float(Fraction(
            matrix[index][index],
            sum(matrix[index]) if rows else sum(matrix[row][index] for row in range(classes)),
        ))
        for index in range(classes)
    ]


def fscore_reference(matrix, beta):
    beta = Fraction(beta)
    beta_squared = beta * beta
    classes = len(matrix)
    scores = []
    for index in range(classes):
        actual_total = sum(matrix[index])
        predicted_total = sum(matrix[row][index] for row in range(classes))
        denominator = beta_squared * actual_total + predicted_total
        if denominator == 0:
            raise ZeroDivisionError
        scores.append(float(
            (1 + beta_squared) * matrix[index][index] / denominator
        ))
    return scores


def test_consumer_and_producer_accuracy_use_pinned_row_and_column_totals(ee):
    matrix = confusion_matrix(ee)
    consumers = output(ee, matrix.consumersAccuracy())
    producers = output(ee, matrix.producersAccuracy())

    assert consumers == accuracy_reference(MATRIX, rows=True)
    assert producers == accuracy_reference(MATRIX, rows=False)
    # The docs guarantee an Array but do not specify its rank. The local
    # materialization policy is one rank-1 per-class vector for both methods.
    assert output(ee, matrix.consumersAccuracy().length().toList()) == [3]
    assert output(ee, matrix.producersAccuracy().length().toList()) == [3]
    assert output(ee, matrix.consumersAccuracy().get([0])) == 5 / 6
    assert output(ee, matrix.producersAccuracy().get([0])) == 5 / 7


def test_fscore_default_and_beta_weighted_values_match_fraction_references(ee):
    matrix = confusion_matrix(ee)
    assert output(ee, matrix.fscore()) == fscore_reference(MATRIX, 1)
    assert output(ee, matrix.fscore(beta=2)) == fscore_reference(MATRIX, 2)
    assert output(ee, matrix.fscore(beta=2).length().toList()) == [3]

    # For this asymmetric fixture, F1 and F2 differ in class 0 and class 1;
    # the reference uses actual rows for recall and predicted columns for precision.
    assert fscore_reference(MATRIX, 1) == [float(Fraction(10, 13)),
                                           float(Fraction(6, 11)), 4 / 5]
    assert fscore_reference(MATRIX, 2) == [float(Fraction(25, 31)),
                                           float(Fraction(15, 29)), 4 / 5]


@pytest.mark.parametrize("beta", [1e308, 2**53,
                                   float.fromhex("0x0.0000000000001p-1022")])
def test_fscore_finite_large_and_subnormal_beta_avoids_intermediate_overflow(ee, beta):
    matrix = confusion_matrix(ee)
    assert output(ee, matrix.fscore(beta=beta)) == fscore_reference(MATRIX, beta)


@pytest.mark.parametrize("beta", [0, -1, float("inf"), float("nan"), True,
                                   2**53 + 1])
def test_fscore_rejects_nonpositive_nonfinite_or_inexact_beta(ee, beta):
    with pytest.raises(UnsupportedEEError, match="ConfusionMatrix.fscore beta"):
        output(ee, confusion_matrix(ee).fscore(beta=beta))


def test_per_class_zero_denominators_fail_without_nonfinite_array_values(ee):
    empty_row = ee.ConfusionMatrix(ee.Array([[0, 0], [1, 1]]))
    with pytest.raises(UnsupportedEEError, match="consumersAccuracy.*zero row total"):
        output(ee, empty_row.consumersAccuracy())

    empty_column = ee.ConfusionMatrix(ee.Array([[1, 0], [1, 0]]))
    with pytest.raises(UnsupportedEEError, match="producersAccuracy.*zero column total"):
        output(ee, empty_column.producersAccuracy())

    absent_class = ee.ConfusionMatrix(ee.Array([[0, 0], [0, 1]]))
    with pytest.raises(UnsupportedEEError, match="fscore.*zero total"):
        output(ee, absent_class.fscore())

    one_sided = ee.ConfusionMatrix(ee.Array([[0, 1], [0, 0]]))
    assert output(ee, one_sided.fscore()) == [0.0, 0.0]


def test_classifier_and_feature_collection_error_matrix_compose_with_metrics(ee):
    rows = [
        {"x": 0, "actual": 0}, {"x": 2, "actual": 0}, {"x": 4, "actual": 0},
        {"x": 5, "actual": 1}, {"x": 7, "actual": 1}, {"x": 20, "actual": 1},
    ]
    training = ee.FeatureCollection([ee.Feature(None, row) for row in rows])
    classifier = ee.Classifier.minimumDistance().train(
        features=training, classProperty="actual", inputProperties=["x"]
    )
    resubstitution = classifier.confusionMatrix()
    validation = training.classify(classifier, "predicted").errorMatrix(
        "actual", "predicted", [0, 1]
    )

    result = output(ee, ee.Dictionary({
        "classifier_matrix": resubstitution.array(),
        "classifier_f1": resubstitution.fscore(),
        "validation_matrix": validation.array(),
        "validation_consumers": validation.consumersAccuracy(),
        "validation_producers": validation.producersAccuracy(),
        "validation_f2": validation.fscore(2),
    }))
    expected_matrix = [[3, 0], [1, 2]]
    assert result["classifier_matrix"] == expected_matrix
    assert result["validation_matrix"] == expected_matrix
    assert result["classifier_f1"] == fscore_reference(expected_matrix, 1)
    assert result["validation_consumers"] == accuracy_reference(expected_matrix, rows=True)
    assert result["validation_producers"] == accuracy_reference(expected_matrix, rows=False)
    assert result["validation_f2"] == fscore_reference(expected_matrix, 2)


def test_metric_arguments_remain_strict_and_large_results_stay_bounded(ee):
    matrix = confusion_matrix(ee)
    expression = encode(ee, matrix.fscore())
    for _, node in reversed(expression.get("scope", [])):
        if isinstance(node, dict) and node.get("functionName") == "ConfusionMatrix.fscore":
            node["arguments"]["unexpected"] = 1
            break
    else:
        raise AssertionError("No ConfusionMatrix.fscore invocation in SDK expression")
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(expression, [], {})

    wide = ee.ConfusionMatrix(ee.Array([[1 if r == c else 0 for c in range(64)]
                                        for r in range(64)]))
    repeated = ee.List([wide.consumersAccuracy() for _ in range(14)])
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        output(ee, repeated)
