"""Array reducer axes, prefix ordering and independent statistical controls."""
import math
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_core import StaticArray
from gee.compat.earthengine.array_reductions import invoke_reduction
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Reducer
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression


@pytest.fixture
def ee():
    return configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=Path(__file__).resolve().parents[1] / "vendor/earthengine-js/algorithms.json")


def output(ee, value):
    return compile_expression(ee.serializer.encode(value, for_cloud_api=False), [], {})["value"]


@pytest.mark.parametrize("reducer,expected", [
    ("sum", [[6, 8]]), ("mean", [[3, 4]]), ("min", [[1, 2]]),
    ("max", [[5, 6]]), ("median", [[3, 4]]), ("count", [[2, 2]]),
    ("sampleStdDev", [[math.sqrt(8), math.sqrt(8)]]),
])
def test_single_output_reducers_preserve_rank_and_match_hand_values(ee, reducer, expected):
    value = ee.Array([[1, 2], [5, 6]]).reduce(getattr(ee.Reducer, reducer)(), [0])
    np.testing.assert_allclose(output(ee, value), expected, atol=1e-15)
    assert output(ee, value.length()) == [1, 2]


def test_multiple_reduced_axes_are_independent_of_retained_axes(ee):
    values = ee.Array([[[1, 2], [3, 4]], [[5, 6], [7, 8]]])
    assert output(ee, values.reduce(ee.Reducer.sum(), [0, 2])) == [[[14], [22]]]
    assert output(ee, values.reduce(ee.Reducer.sum(), [2, 0])) == [[[14], [22]]]
    assert output(ee, values.reduce(ee.Reducer.count(), [0, 1, 2])) == [[[8]]]


def test_array_statistics_handle_large_offsets_and_extreme_finite_values(ee):
    low, high = 1e100, math.nextafter(1e100, math.inf)
    sd = output(ee, ee.Array([low, high]).reduce(ee.Reducer.sampleStdDev(), [0]))[0]
    assert sd == pytest.approx((high - low) / math.sqrt(2), rel=3e-16)
    assert output(ee, ee.Array([1e308, 1e308]).reduce(ee.Reducer.mean(), [0])) == [1e308]
    huge_sd = output(ee, ee.Array([-1e308, 1e308]).reduce(ee.Reducer.sampleStdDev(), [0]))[0]
    assert huge_sd == pytest.approx(math.sqrt(2) * 1e308, rel=3e-16)
    assert output(ee, ee.Array([1e308, -1e308, 1]).reduce(ee.Reducer.mean(), [0]))[0] == pytest.approx(1 / 3)


def test_finite_cancellation_and_median_survive_intermediate_overflow(ee):
    values = ee.Array([1e308, 1e308, -1e308, -1e308, 1e-300])
    assert output(ee, values.reduce(ee.Reducer.sum(), [0])) == [1e-300]
    assert output(ee, values.reduce(ee.Reducer.mean(), [0])) == [1e-300 / 5]
    assert output(ee, ee.Array([1e308, 1e308]).reduce(ee.Reducer.median(), [0])) == [1e308]
    with pytest.raises(UnsupportedEEError, match="finite"):
        output(ee, ee.Array([1e308, 1e308]).reduce(ee.Reducer.sum(), [0]))


@pytest.mark.parametrize("method,expected", [
    ("sum", [[2, 7, 8], [3, 3, 7]]),
    ("min", [[2, 2, 1], [3, 0, 0]]),
    ("max", [[2, 5, 5], [3, 3, 4]]),
])
def test_prefix_reductions_use_axis_order_and_default_sum(ee, method, expected):
    values = ee.Array([[2, 5, 1], [3, 0, 4]])
    assert output(ee, values.accum(1, getattr(ee.Reducer, method)())) == expected
    assert output(ee, values.accum(0)) == [[2, 5, 1], [5, 5, 5]]


@pytest.mark.parametrize("axes", [[], [0, 0], [-1], [2], [True], [0.5]])
def test_invalid_or_unimplemented_axes_are_rejected(ee, axes):
    with pytest.raises(UnsupportedEEError):
        output(ee, ee.Array([[1, 2]]).reduce(ee.Reducer.sum(), axes))


def test_field_axis_empty_inputs_and_unsupported_reducers_are_not_ignored(ee):
    with pytest.raises(UnsupportedEEError, match="fieldAxis"):
        output(ee, ee.Array([[1], [2]]).reduce(ee.Reducer.mean(), [0], fieldAxis=1))
    with pytest.raises(UnsupportedEEError, match="single-output scalar Reducer"):
        output(ee, ee.Array([[1, 2]]).reduce(ee.Reducer.linearRegression(1), [0]))
    with pytest.raises(UnsupportedEEError, match="sum/min/max only"):
        output(ee, ee.Array([1, 2]).accum(0, ee.Reducer.mean()))
    with pytest.raises(UnsupportedEEError, match="at least two"):
        output(ee, ee.Array([1]).reduce(ee.Reducer.sampleStdDev(), [0]))
    empty = ee.Array([[1, 2]]).slice(0, 0, 0)
    with pytest.raises(UnsupportedEEError, match="Empty Array"):
        output(ee, empty.reduce(ee.Reducer.sum(), [0]))
    with pytest.raises(UnsupportedEEError, match="Empty Array"):
        output(ee, empty.accum(0))


def test_integer_sums_and_prefixes_never_wrap_or_silently_round(ee):
    for value in (ee.Array([2**53, 1]).reduce(ee.Reducer.sum(), [0]),
                  ee.Array([2**53, 1]).accum(0)):
        with pytest.raises(UnsupportedEEError, match="exact Float64"):
            output(ee, value)


def test_reduction_parameters_and_work_preflight_are_strict():
    arguments = {"array": StaticArray(np.array([[1, 2], [3, 4]])),
                 "reducer": Reducer("mean"), "axes": [0]}
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_reduction(Translator([], {}, None), "Array.reduce", {**arguments, "ignored": 1})
    translator = Translator([], {}, None)
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_reduction(translator, "Array.reduce", arguments)
