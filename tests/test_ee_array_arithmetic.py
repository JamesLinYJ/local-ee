"""Pinned Array arithmetic, exact integer controls and explicit local limits."""
import math
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_arithmetic import invoke_arithmetic
from gee.compat.earthengine.array_core import StaticArray
from gee.compat.earthengine.decoder import Translator
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression


@pytest.fixture
def ee():
    return configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=Path(__file__).resolve().parents[1] / "vendor/earthengine-js/algorithms.json")


def output(ee, value):
    return compile_expression(ee.serializer.encode(value, for_cloud_api=False), [], {})["value"]


@pytest.mark.parametrize("method,expected", [
    ("add", [3, 0]), ("subtract", [-1, 8]),
    ("multiply", [2, -16]), ("divide", [0.5, -1]),
])
def test_array_binary_operations_match_hand_values(ee, method, expected):
    assert output(ee, getattr(ee.Array([1, 4]), method)([2, -4])) == expected
    assert output(ee, getattr(ee.Array(4), method)(ee.Array(2))) == {
        "add": 6, "subtract": 2, "multiply": 8, "divide": 2,
    }[method]


def test_array_zero_division_and_unary_real_values(ee):
    assert output(ee, ee.Array([3, -3, 0]).divide([0, 0, 0])) == [0, 0, 0]
    assert output(ee, ee.Array([-4, 0, 2]).abs()) == [4, 0, 2]
    np.testing.assert_allclose(output(ee, ee.Array([0, 4, 2]).sqrt()), [0, 2, math.sqrt(2)])
    with pytest.raises(UnsupportedEEError, match="nonnegative"):
        output(ee, ee.Array([-1]).sqrt())


@pytest.mark.parametrize("operation", [
    lambda ee: ee.Array([2**53]).add([1]),
    lambda ee: ee.Array([-2**53]).subtract([1]),
    lambda ee: ee.Array([2**53]).multiply([2]),
    lambda ee: ee.Array([1e308]).multiply([2.0]),
])
def test_array_arithmetic_never_wraps_or_returns_nonfinite_values(ee, operation):
    with pytest.raises(UnsupportedEEError, match="exact Float64|finite"):
        output(ee, operation(ee))


def test_equal_shape_policy_and_derived_empty_axes_are_explicit(ee):
    with pytest.raises(UnsupportedEEError, match="same shape"):
        output(ee, ee.Array([1, 2]).add(3))
    with pytest.raises(UnsupportedEEError, match="same shape"):
        output(ee, ee.Array([[1, 2]]).add([[1], [2]]))
    empty = ee.Array([[1, 2]]).slice(axis=0, start=0, end=0)
    assert output(ee, empty.add(empty).length()) == [0, 2]
    assert output(ee, empty.add(empty).toList()) == []


def test_array_arithmetic_parameters_types_and_shared_work_are_checked():
    array = StaticArray(np.array([1, 2]))
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_arithmetic(translator, "Array.add", {"left": array, "right": array, "ignored": 1})
    with pytest.raises(UnsupportedEEError, match="static ee.Array"):
        invoke_arithmetic(translator, "Array.add", {"left": array, "right": [1, 2]})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_arithmetic(translator, "Array.add", {"left": array, "right": array})
    np.testing.assert_array_equal(array.data, [1, 2])
