"""Pinned SDK serialization and independent values for Array binary math."""
import math
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine import array_binary
from gee.compat.earthengine.array_core import MAX_ARRAY_WORK, StaticArray
from gee.compat.earthengine.decoder import Translator
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def output(ee, value):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, [], {})["value"]


def array_invocation(expression):
    calls = [call for _, call in expression.get("scope", [])
             if isinstance(call, dict) and call.get("type") == "Invocation"
             and call.get("functionName", "").startswith("Array.")]
    return calls[-1]


@pytest.mark.parametrize("method,expected", [
    ("max", [3, 4, 2]),
    ("min", [1, -4, 0]),
    ("first", [1, 4, 0]),
    ("firstNonZero", [1, 4, 2]),
    ("first_nonzero", [1, 4, 2]),
    ("and", [1, 1, 0]),
    ("or", [1, 1, 1]),
    ("eq", [0, 0, 0]),
    ("neq", [1, 1, 1]),
    ("lt", [1, 0, 1]),
    ("lte", [1, 0, 1]),
    ("gt", [0, 1, 0]),
    ("gte", [0, 1, 0]),
])
def test_pinned_sdk_serializes_and_computes_binary_operations(ee, method, expected):
    left, right = [1, 4, 0], [3, -4, 2]
    sdk_method = {"and": "And", "or": "Or"}.get(method, method)
    expression = ee.serializer.encode(
        getattr(ee.Array(left), sdk_method)(right), for_cloud_api=False)
    call = array_invocation(expression)
    assert call["functionName"] == f"Array.{method}"
    assert set(call["arguments"]) == {"left", "right"}
    assert compile_expression(expression, [], {})["value"] == expected


def test_mod_uses_ee_remainder_examples_and_finite_fractional_values(ee):
    # Pinned EE examples show the remainder keeps the dividend's sign.
    assert output(ee, ee.Array([-1, -7, -8, -9]).mod([8, 8, 8, 8])) == [-1, -7, 0, -1]
    assert output(ee, ee.Array([8, 8, 8, 8]).mod([-1, -7, -8, -9])) == [0, 1, 0, 8]
    result = output(ee, ee.Array([2.5]).mod([1.2]))[0]
    assert result == math.fmod(2.5, 1.2)


def test_power_handles_exact_integers_and_real_inputs(ee):
    assert output(ee, ee.Array([2, -2, 3]).pow([3, 4, 0])) == [8, 16, 1]
    assert output(ee, ee.Array([-2]).pow([-3])) == [-0.125]
    assert output(ee, ee.Array([2.0, 3.0]).pow([0.5, 2.0])) == pytest.approx(
        [math.sqrt(2), 9])
    with pytest.raises(UnsupportedEEError, match="exact Float64"):
        output(ee, ee.Array([2]).pow([54]))


def test_binary_scalar_empty_highrank_and_exact_shape(ee):
    assert output(ee, ee.Array(3).max(ee.Array(4))) == 4
    empty = StaticArray(np.empty((0, 2), dtype=np.float64))
    result = array_binary.invoke_binary(
        Translator([], {}, None), "Array.max", {"left": empty, "right": empty})
    assert result.data.shape == (0, 2)

    high_rank = StaticArray(np.full((1,) * 8, 2.0))
    result = array_binary.invoke_binary(
        Translator([], {}, None), "Array.pow",
        {"left": high_rank, "right": high_rank})
    assert result.data.shape == (1,) * 8
    np.testing.assert_array_equal(result.data, 4)

    with pytest.raises(UnsupportedEEError, match="same shape"):
        output(ee, ee.Array([1, 2]).max(3))
    with pytest.raises(UnsupportedEEError, match="same shape"):
        output(ee, ee.Array([[1, 2]]).max([[1], [2]]))


def test_binary_outputs_are_owned_readonly_and_precharged(monkeypatch):
    left_source = np.array([2.0, 4.0])
    left = StaticArray(left_source)
    right = StaticArray(np.array([3.0, 3.0]))
    result = array_binary.invoke_binary(
        Translator([], {}, None), "Array.max", {"left": left, "right": right})
    left_source[0] = 99
    assert not np.shares_memory(result.data, left_source)
    assert not result.data.flags.writeable
    np.testing.assert_array_equal(result.data, [3, 4])

    at_limit = Translator([], {}, None)
    at_limit.steps = MAX_ARRAY_WORK - 5
    array_binary.invoke_binary(at_limit, "Array.max", {
        "left": StaticArray(np.array([1])), "right": StaticArray(np.array([2])),
    })
    assert at_limit.steps == MAX_ARRAY_WORK

    translator = Translator([], {}, None)
    translator.steps = MAX_ARRAY_WORK - 4

    def forbidden_kernel(*_args, **_kwargs):
        raise AssertionError("Array kernel ran before its work was charged")

    monkeypatch.setattr(array_binary.np, "maximum", forbidden_kernel)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        array_binary.invoke_binary(translator, "Array.max", {
            "left": StaticArray(np.array([1.])), "right": StaticArray(np.array([2.])),
        })
    assert translator.steps == MAX_ARRAY_WORK - 4


def test_integer_power_charges_bounded_work_before_computation(monkeypatch):
    operands = {"left": StaticArray(np.array([2])),
                "right": StaticArray(np.array([3]))}
    at_limit = Translator([], {}, None)
    at_limit.steps = MAX_ARRAY_WORK - 110
    result = array_binary.invoke_binary(at_limit, "Array.pow", operands)
    assert result.data.item() == 8
    assert at_limit.steps == MAX_ARRAY_WORK

    too_late = Translator([], {}, None)
    too_late.steps = MAX_ARRAY_WORK - 109

    def forbidden_power(*_args):
        raise AssertionError("integer power ran before its worst-case cost was charged")

    monkeypatch.setattr(array_binary, "_integer_power", forbidden_power)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        array_binary.invoke_binary(too_late, "Array.pow", operands)
    assert too_late.steps == MAX_ARRAY_WORK - 109


@pytest.mark.parametrize("name,left,right", [
    ("Array.mod", [1], [0]),
    ("Array.pow", [0.0], [-1.0]),
    ("Array.pow", [-2.0], [0.5]),
    ("Array.pow", [1.0e308], [2.0]),
])
def test_binary_domain_overflow_and_nonfinite_errors(name, left, right):
    left_array = StaticArray(np.asarray(left))
    right_array = StaticArray(np.asarray(right))
    with pytest.raises(UnsupportedEEError):
        array_binary.invoke_binary(
            Translator([], {}, None), name,
            {"left": left_array, "right": right_array})


def test_binary_arguments_types_and_unsupported_casts_fail_closed():
    translator = Translator([], {}, None)
    array = StaticArray(np.array([1]))
    with pytest.raises(UnsupportedEEError, match="requires right"):
        array_binary.invoke_binary(translator, "Array.max", {"left": array})
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        array_binary.invoke_binary(translator, "Array.max", {
            "left": array, "right": array, "extra": 1,
        })
    with pytest.raises(UnsupportedEEError, match="static ee.Array"):
        array_binary.invoke_binary(translator, "Array.eq", {"left": [1], "right": array})
    with pytest.raises(UnsupportedEEError, match="Unsupported static Array"):
        array_binary.invoke_binary(translator, "Array.bitwiseAnd", {"left": array, "right": array})
