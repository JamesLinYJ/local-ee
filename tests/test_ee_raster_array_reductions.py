"""Array pixel reductions checked against hand-computed two-band controls."""
import math
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from test_ee_translate import evaluate_graph


@pytest.fixture
def ee():
    return configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=Path(__file__).resolve().parents[1] / "vendor/earthengine-js/algorithms.json")


def compute(ee, expression):
    metadata = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": ["red", "nir"]}}}]
    items = {"sentinel-2-l2a": [{"id": "a", "bbox": [0, 0, 2, 2], "properties": {}}]}
    result = compile_expression(ee.serializer.encode(expression, for_cloud_api=False), metadata, items)
    values, names, timed = evaluate_graph(result, {"a": {
        "red": np.array([1, 2, np.nan, 5]), "nir": np.array([3, np.nan, 7, 5]),
    }})
    assert timed is False
    return values, names


def matrix(ee):
    column = ee.ImageCollection("sentinel-2-l2a").first().toArray().toArray(1)
    return ee.Image(ee.Array([[1, 2], [3, 4]])).matrixMultiply(column)


@pytest.mark.parametrize("reducer,expected", [
    ("sum", [22, 50]), ("mean", [11, 25]), ("min", [7, 15]),
    ("max", [15, 35]), ("median", [11, 25]), ("count", [2, 2]),
    ("sampleStdDev", [4 * math.sqrt(2), 10 * math.sqrt(2)]),
])
def test_reducers_keep_axes_and_whole_array_mask(ee, reducer, expected):
    reduced = matrix(ee).arrayReduce(getattr(ee.Reducer, reducer)(), [0])
    values, names = compute(ee, reduced.arrayFlatten([["row"], ["column"]]))
    assert names == ["row_column"]
    np.testing.assert_allclose(values, [[expected[0], np.nan, np.nan, expected[1]]], equal_nan=True)


def test_multiple_axes_and_singleton_groups_preserve_layout(ee):
    values, names = compute(ee, matrix(ee).arrayReduce(ee.Reducer.sum(), [1]).arrayFlatten(
        [["first", "second"], ["sum"]]))
    assert names == ["first_sum", "second_sum"]
    np.testing.assert_allclose(values, [[7, np.nan, np.nan, 15], [15, np.nan, np.nan, 35]], equal_nan=True)
    for axes in ([0, 1], [1, 0]):
        result, _ = compute(ee, matrix(ee).arrayReduce(ee.Reducer.count(), axes).arrayFlatten([["x"], ["y"]]))
        np.testing.assert_allclose(result, [[2, np.nan, np.nan, 2]], equal_nan=True)


@pytest.mark.parametrize("axes", [[], [0, 0], [-1], [2], [True], [0.5]])
def test_invalid_axes_are_explicitly_rejected(ee, axes):
    with pytest.raises(UnsupportedEEError, match="axes|axis"):
        compute(ee, matrix(ee).arrayReduce(ee.Reducer.sum(), axes).arrayFlatten([["r"], ["c"]]))


def test_field_axis_multi_output_and_undefined_sample_deviation_reject(ee):
    values, names = compute(ee, matrix(ee).arrayReduce(
        ee.Reducer.mean(), [0], fieldAxis=1).arrayFlatten([["r"], ["c"]]))
    assert names == ["r_c"]
    np.testing.assert_allclose(values, [[11, np.nan, np.nan, 25]], equal_nan=True)
    for expression, reason in [
        (matrix(ee).arrayReduce(ee.Reducer.mean(), [0], fieldAxis=0), "fieldAxis"),
        (matrix(ee).arrayReduce(ee.Reducer.linearRegression(1), [0]), "legacy Reducer or closed ReducerSpec"),
        (matrix(ee).arrayReduce(ee.Reducer.sampleStdDev(), [1]), "at least two"),
    ]:
        with pytest.raises(UnsupportedEEError, match=reason):
            compute(ee, expression.arrayFlatten([["r"], ["c"]]))
