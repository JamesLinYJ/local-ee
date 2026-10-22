"""Pinned Python SDK checks for supported minimum-distance metric modes."""
from fractions import Fraction
from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield guard
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def output(ee, value):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, [], {})["value"]


def collection(ee, rows):
    return ee.FeatureCollection([ee.Feature(None, row) for row in rows])


def classify_centers(ee, metric, centers, query):
    training = collection(ee, [
        {"x": x, "y": y, "actual": label}
        for label, (x, y) in enumerate(centers)
    ])
    classifier = ee.Classifier.minimumDistance(metric=metric).train(
        features=training, classProperty="actual", inputProperties=["x", "y"],
    )
    validation = collection(ee, [{"x": query[0], "y": query[1]}])
    return output(ee, ee.Dictionary({
        "prediction": validation.classify(classifier).aggregate_array("classification"),
        "training_matrix": classifier.confusionMatrix().array(),
    }))


@pytest.mark.parametrize(("metric", "expected"), [
    ("euclidean", [1]),
    ("manhattan", [0]),
    ("cosine", [1]),
])
def test_three_metric_implementations_compose_with_training_classification_and_confusion(
        ee, offline_only, metric, expected):
    # For q=(2,1), centers (5,1) and (4,3) yield squared Euclidean
    # distances 9 and 8, Manhattan distances 3 and 4, and cosine scores
    # 11/sqrt(26) and 11/sqrt(25), respectively.
    result = classify_centers(ee, metric, [(5, 1), (4, 3)], (2, 1))
    assert result["prediction"] == expected
    assert result["training_matrix"] == [[1, 0], [0, 1]]
    assert offline_only.evidence()["attempt_count"] == 0


@pytest.mark.parametrize(("metric", "centers", "query"), [
    ("manhattan", [(0, 0), (2, 2)], (1, 1)),
    ("cosine", [(1, 0), (2, 0)], (1, 0)),
])
def test_exact_distance_or_angle_ties_remain_rejected(ee, metric, centers, query):
    with pytest.raises(UnsupportedEEError, match="equal-distance class centers"):
        classify_centers(ee, metric, centers, query)


@pytest.mark.parametrize(("centers", "query", "message"), [
    ([(0, 0), (1, 0)], (1, 0), "zero-norm class center"),
    ([(1, 0), (0, 1)], (0, 0), "zero-norm query"),
])
def test_cosine_zero_norms_are_rejected_with_a_stated_local_policy(
        ee, centers, query, message):
    with pytest.raises(UnsupportedEEError, match=message):
        classify_centers(ee, "cosine", centers, query)


@pytest.mark.parametrize("metric", ["mahalanobis", "chebyshev", "", False, 3, ["cosine"]])
def test_metric_name_and_type_validation_is_explicit(ee, metric):
    classifier = ee.Classifier.minimumDistance(metric=metric)
    with pytest.raises(UnsupportedEEError, match="metric must be"):
        output(ee, classifier.schema())


@pytest.mark.parametrize("k_nearest", [0, 2, 3.5, False])
def test_only_k_nearest_one_is_supported_for_each_metric(ee, k_nearest):
    for metric in ("euclidean", "manhattan", "cosine"):
        classifier = ee.Classifier.minimumDistance(metric=metric, kNearest=k_nearest)
        with pytest.raises(UnsupportedEEError):
            output(ee, classifier.schema())


@pytest.mark.parametrize("metric", ["euclidean", "manhattan", "cosine"])
def test_constructor_preserves_the_selected_metric_in_classifier_ir(metric):
    from gee.compat.earthengine.decoder import Translator
    from gee.compat.earthengine.minimum_distance import _construct

    classifier = _construct(Translator([], {}, {}), {"metric": metric})
    assert classifier.metric == metric


@pytest.mark.parametrize("mode", ["REGRESSION", "RAW", "PROBABILITY"])
def test_raw_and_regression_modes_remain_unsupported(ee, mode):
    classifier = ee.Classifier.minimumDistance(metric="cosine").setOutputMode(mode)
    with pytest.raises(UnsupportedEEError, match="CLASSIFICATION"):
        output(ee, classifier.schema())


def test_image_classification_remains_explicitly_unsupported(ee):
    classifier = ee.Classifier.minimumDistance(metric="manhattan").train(
        features=collection(ee, [
            {"x": 1, "y": 0, "actual": 0}, {"x": 0, "y": 1, "actual": 1},
        ]),
        classProperty="actual", inputProperties=["x", "y"],
    )
    with pytest.raises(UnsupportedEEError, match="missing classifier schema band"):
        output(ee, ee.Image.constant(1).classify(classifier))


def test_cosine_work_budget_is_charged_before_candidate_scoring(monkeypatch):
    from gee.compat.earthengine import minimum_distance_metrics as metrics
    from gee.compat.earthengine.decoder import Translator
    from gee.compat.earthengine.minimum_distance import StaticMinimumDistance, predict_class

    classifier = StaticMinimumDistance(
        metric="cosine", schema=("x", "y"), labels=(0, 1),
        centers=((Fraction(1), Fraction(0)), (Fraction(0), Fraction(1))),
        training_rows=((0, (Fraction(1), Fraction(0))),),
    )
    translator = Translator([], {}, {})
    translator.steps = 49_994
    monkeypatch.setattr(
        metrics, "_cosine_score",
        lambda *_args: pytest.fail("cosine scores were made before their work charge"),
    )
    with pytest.raises(UnsupportedEEError, match="budget"):
        predict_class(translator, classifier, [1, 0])
    # Vector conversion was charged; the larger cosine charge failed without
    # partially changing the work counter or entering the candidate loop.
    assert translator.steps == 49_996
