"""Pinned List.reduce serialization and bounded reducer semantics."""
from copy import deepcopy
from pathlib import Path
import math

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


def add_unknown_argument(expression, function_name):
    result = deepcopy(expression)
    for _, node in reversed(result.get("scope", [])):
        if isinstance(node, dict) and node.get("functionName") == function_name:
            node["arguments"]["unexpected"] = 1
            return result
    raise AssertionError(f"No {function_name} invocation in SDK serialization")


@pytest.mark.parametrize(("name", "expected"), [
    ("sum", 6),
    ("mean", 3),
    ("min", 2),
    ("max", 4),
    ("count", 2),
    ("first", 4),
    ("last", 2),
    ("median", 3),
    ("sampleStdDev", math.sqrt(2)),
])
def test_pinned_sdk_list_reduce_skips_nulls_for_scalar_reducers(ee, name, expected):
    result = ee.List([None, 4, None, 2]).reduce(getattr(ee.Reducer, name)())
    assert output(ee, result) == pytest.approx(expected)


@pytest.mark.parametrize("values", [[], [None, None]])
@pytest.mark.parametrize("name", [
    "sum", "mean", "min", "max", "count", "first", "last", "median", "sampleStdDev",
])
def test_empty_and_all_null_reducer_results_are_explicit(ee, values, name):
    result = output(ee, ee.List(values).reduce(getattr(ee.Reducer, name)()))
    expected = 0 if name in {"sum", "count"} else None
    assert result == expected


def test_sample_std_dev_needs_two_non_null_values(ee):
    result = ee.List([None, 5, None]).reduce(ee.Reducer.sampleStdDev())
    assert output(ee, result) is None


def test_count_first_and_last_preserve_non_numeric_values(ee):
    payload = {"nested": [3, 5]}
    assert output(ee, ee.List([None, True, payload]).reduce(ee.Reducer.count())) == 2
    assert output(ee, ee.List([None, payload, None]).reduce(ee.Reducer.first())) == payload
    assert output(ee, ee.List([None, [7, 8], None]).reduce(ee.Reducer.last())) == [7, 8]


@pytest.mark.parametrize("bad", [True, "2", float("inf"), float("nan"), 2**53 + 1])
def test_numeric_reducers_reject_boolean_non_numeric_nonfinite_and_inexact_values(ee, bad):
    with pytest.raises(UnsupportedEEError):
        output(ee, ee.List([1, bad]).reduce(ee.Reducer.sum()))


def test_list_reduce_linear_fit_matches_closed_form_hand_reference(ee):
    # xbar=1.5, ybar=4, sum((x-xbar)(y-ybar))=11 and
    # sum((x-xbar)^2)=5, so slope=11/5=2.2 and offset=4-2.2*1.5=0.7.
    values = ee.List([[0, 1], [1, 2], [2, 6], [3, 7]])
    result = output(ee, values.reduce(ee.Reducer.linearFit()))
    assert result["scale"] == pytest.approx(2.2, abs=1e-14)
    assert result["offset"] == pytest.approx(0.7, abs=1e-14)


def test_multi_response_regression_rms_and_typed_coefficients_compose(ee):
    rows = ee.List([
        [1, 0, 1, 5],
        [1, 1, 2, 7],
        [1, 2, 6, 9],
        [1, 3, 7, 11],
    ])
    regression = rows.reduce(ee.Reducer.linearRegression(numX=2, numY=2))
    result = output(ee, regression)

    # The first response has the same hand-derived fit above and residuals
    # (0.3, -0.9, 0.9, -0.3), giving RMS sqrt(0.45). The second is 5+2*x.
    np.testing.assert_allclose(
        result["coefficients"], [[0.7, 5], [2.2, 2]], atol=1e-14, rtol=0,
    )
    np.testing.assert_allclose(
        result["residuals"], [math.sqrt(0.45), 0], atol=1e-14, rtol=0,
    )

    coefficients = ee.Array(ee.Dictionary(regression).get("coefficients"))
    assert output(ee, coefficients.get([1, 0])) == pytest.approx(2.2, abs=1e-14)
    prediction = ee.Array([[1, 2]]).matrixMultiply(coefficients)
    np.testing.assert_allclose(output(ee, prediction), [[5.1, 9]], atol=1e-14, rtol=0)


def test_regression_drops_null_rows_and_incomplete_rows(ee):
    rows = ee.List([
        [1, 0, 1],
        None,
        [1, 1, 3],
        [1, None, 100],
        [1, 2, 5],
    ])
    result = output(ee, rows.reduce(ee.Reducer.linearRegression(numX=2, numY=1)))
    np.testing.assert_allclose(result["coefficients"], [[1], [2]], atol=1e-14, rtol=0)
    np.testing.assert_allclose(result["residuals"], [0], atol=1e-14, rtol=0)


def test_regression_rejects_invalid_values_even_when_the_row_has_nulls(ee):
    rows = ee.List([[1, None, True], [1, 0, 1], [1, 1, 3]])
    with pytest.raises(UnsupportedEEError, match="finite numbers|numeric inputs|finite"):
        output(ee, rows.reduce(ee.Reducer.linearRegression(numX=2, numY=1)))


@pytest.mark.parametrize("bad", [True, "2", float("inf"), float("nan"), 2**53 + 1])
def test_regression_rejects_invalid_non_null_values(ee, bad):
    rows = ee.List([[1, 0, 1], [1, 1, 3], [1, 2, bad]])
    with pytest.raises(UnsupportedEEError):
        output(ee, rows.reduce(ee.Reducer.linearRegression(numX=2, numY=1)))


@pytest.mark.parametrize("rows", [
    [[1, 0], [1, 1, 3]],
    [[1, 0, 1, 2]],
])
def test_regression_requires_exact_row_width(ee, rows):
    expression = ee.List(rows).reduce(ee.Reducer.linearRegression(numX=2, numY=1))
    with pytest.raises(UnsupportedEEError, match="rows of 3 inputs"):
        output(ee, expression)


def test_insufficient_or_rank_deficient_regression_returns_null_outputs(ee):
    reducer = ee.Reducer.linearRegression(numX=2, numY=1)
    insufficient = ee.List([[1, 0, 1], [1, 1, 3]]).reduce(reducer)
    rank_deficient = ee.List([[1, 2, 1], [1, 2, 3], [1, 2, 5]]).reduce(reducer)
    for expression in (insufficient, rank_deficient):
        assert output(ee, expression) == {"coefficients": None, "residuals": None}

    no_x_variation = ee.List([[2, 1], [2, 4]]).reduce(ee.Reducer.linearFit())
    assert output(ee, no_x_variation) == {"scale": None, "offset": None}


def test_list_size_and_regression_input_column_boundaries(ee):
    assert output(ee, ee.List(list(range(1000))).reduce(ee.Reducer.count())) == 1000
    with pytest.raises(UnsupportedEEError, match="at most 1000 inline values"):
        output(ee, ee.List(list(range(1001))).reduce(ee.Reducer.count()))

    # 31 predictors plus one response is the supported 32-column limit.
    accepted = ee.List([[1] * 32]).reduce(
        ee.Reducer.linearRegression(numX=31, numY=1)
    )
    assert output(ee, accepted) == {"coefficients": None, "residuals": None}
    rejected = ee.List([[1] * 33]).reduce(
        ee.Reducer.linearRegression(numX=32, numY=1)
    )
    with pytest.raises(UnsupportedEEError, match="32 input columns"):
        output(ee, rejected)


def test_list_reduce_regression_accepts_1000_complete_rows(ee):
    rows = [[1, index, 2 * index + 1] for index in range(1000)]
    expression = ee.List(rows).reduce(ee.Reducer.linearRegression(numX=2, numY=1))
    result = output(ee, expression)
    np.testing.assert_allclose(result["coefficients"], [[1], [2]], atol=1e-12, rtol=0)
    np.testing.assert_allclose(result["residuals"], [0], atol=1e-12, rtol=0)


def test_unknown_list_reduce_parameters_are_rejected_after_sdk_serialization(ee):
    expression = encode(ee, ee.List([1, 2]).reduce(ee.Reducer.sum()))
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(add_unknown_argument(expression, "List.reduce"), [], {})


def test_list_reduce_rejects_reducers_outside_the_supported_subset(ee):
    expression = ee.List([1, 2]).reduce(ee.Reducer.variance())
    with pytest.raises(UnsupportedEEError):
        output(ee, expression)


def test_large_regression_work_is_rejected_by_the_shared_budget(ee):
    rows = [[1] * 31 + [index] for index in range(100)]
    expression = ee.List(rows).reduce(ee.Reducer.linearRegression(numX=31, numY=1))
    with pytest.raises(UnsupportedEEError, match="work budget"):
        output(ee, expression)
