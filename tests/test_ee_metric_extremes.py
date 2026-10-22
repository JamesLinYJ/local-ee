"""Independent high-precision controls for class-center distance rankings."""
from decimal import Decimal, localcontext
from pathlib import Path
import sys

import pytest

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
    return configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                              signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")


def predict(ee, centers, queries, metric):
    training = ee.FeatureCollection([
        ee.Feature(None, {"label": index, "x": center[0], "y": center[1]})
        for index, center in enumerate(centers)
    ])
    classifier = ee.Classifier.minimumDistance(metric).train(training, "label", ["x", "y"])
    validation = ee.FeatureCollection([
        ee.Feature(None, {"x": query[0], "y": query[1]}) for query in queries
    ])
    value = validation.classify(classifier, "prediction").aggregate_array("prediction")
    return compile_expression(ee.serializer.encode(value, for_cloud_api=False), [], {})["value"]


def decimal_reference(centers, queries, metric):
    """Normalize explicitly and divide/sqrt in Decimal, unlike the exact comparator.

    1600 significant digits retain the angle difference between the smallest
    binary64 subnormal and the largest finite binary64 magnitude. This oracle
    uses no production distance helpers or squared cross-product rankings.
    """
    def decimal(value):
        return Decimal.from_float(value) if isinstance(value, float) else Decimal(value)

    predictions = []
    with localcontext() as context:
        context.prec = 1600
        converted = [[decimal(value) for value in row] for row in centers]
        for raw in queries:
            vector = [decimal(value) for value in raw]
            distances = []
            for center in converted:
                if metric == "cosine":
                    norm = sum(value * value for value in vector).sqrt()
                    center_norm = sum(value * value for value in center).sqrt()
                    # 1-cos is monotone in the spectral angle in [0,pi].
                    distance = 1 - sum((x / norm) * (y / center_norm)
                                       for x, y in zip(vector, center))
                else:
                    deltas = [abs(x - y) for x, y in zip(vector, center)]
                    distance = sum(deltas) if metric == "manhattan" else sum(
                        value * value for value in deltas).sqrt()
                distances.append(distance)
            best = min(distances)
            assert distances.count(best) == 1, "reference needs a unique winner"
            predictions.append(distances.index(best))
    return predictions


@pytest.mark.parametrize("centers,queries,expected", [
    ([(1, 0), (1, 1)], [(-1, -2), (-2, -1)], [0, 0]),
    ([(0, 1), (1, 0)], [(-1, 0), (0, -1)], [0, 1]),
    ([(1, 0), (-1, 0), (0, 1)], [(-1, 0), (0, 2)], [1, 2]),
    ([(sys.float_info.max, 5e-324), (sys.float_info.max, 1e-323)],
     [(sys.float_info.max, 1e-323)], [1]),
    ([(5e-324, 0), (0, 5e-324)], [(5e-324, 0), (0, 5e-324)], [0, 1]),
    ([(2**53, 2**53 - 1), (2**53 - 1, 2**53)],
     [(2**53, 2**53 - 1), (2**53 - 1, 2**53)], [0, 1]),
])
def test_spectral_angle_keeps_sign_extreme_norms_and_close_directions(
        ee, centers, queries, expected):
    assert decimal_reference(centers, queries, "cosine") == expected
    assert predict(ee, centers, queries, "cosine") == expected


@pytest.mark.parametrize("metric", ["euclidean", "manhattan", "cosine"])
def test_metric_selection_is_real_and_can_change_the_nearest_class(ee, metric):
    centers, queries = [(3, 0), (2, 2)], [(0.25, 0.25), (5, 0), (0, 5)]
    expected = decimal_reference(centers, queries, metric)
    assert expected[0] == (0 if metric == "manhattan" else 1)
    assert predict(ee, centers, queries, metric) == expected


@pytest.mark.parametrize("scale", [5e-324, 1e-200, 0.5, 1e200, 1e308])
def test_positive_rescaling_of_queries_preserves_spectral_angle_labels(ee, scale):
    centers = [(1, 0), (0, 1), (-1, 0)]
    queries = [(scale, 0), (0, scale), (-scale, 0)]
    assert decimal_reference(centers, queries, "cosine") == [0, 1, 2]
    assert predict(ee, centers, queries, "cosine") == [0, 1, 2]


@pytest.mark.parametrize("metric", ["euclidean", "manhattan"])
def test_large_finite_inputs_do_not_need_representable_distance_output(ee, metric):
    centers = [(-sys.float_info.max, -sys.float_info.max),
               (sys.float_info.max, sys.float_info.max)]
    queries = [(1e308, 1e308), (-1e308, -1e308)]
    assert decimal_reference(centers, queries, metric) == [1, 0]
    assert predict(ee, centers, queries, metric) == [1, 0]


@pytest.mark.parametrize("centers,query", [
    ([(1, 2), (10, 20)], (2, 4)),
    ([(1, 1), (1, -1)], (-2, 0)),
])
def test_equal_spectral_angles_keep_explicit_tie_rejection(ee, centers, query):
    with pytest.raises(UnsupportedEEError, match="equal-distance"):
        predict(ee, centers, [query], "cosine")
