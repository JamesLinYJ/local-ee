"""Pinned SDK serialization and independent values for Array unary math."""
import math
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine import array_unary
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


@pytest.mark.parametrize("method,values,expected", [
    ("sin", [0, math.pi / 6, math.pi / 2], [0, 0.5, 1]),
    ("cos", [0, math.pi / 3, math.pi], [1, 0.5, -1]),
    ("tan", [0, math.pi / 4, -math.pi / 4], [0, 1, -1]),
    ("asin", [-1, 0, 0.5], [-math.pi / 2, 0, math.pi / 6]),
    ("acos", [-1, 0, 1], [math.pi, math.pi / 2, 0]),
    ("atan", [-1, 0, 1], [-math.pi / 4, 0, math.pi / 4]),
    ("sinh", [-1, 0, 1], [-math.sinh(1), 0, math.sinh(1)]),
    ("cosh", [-1, 0, 1], [math.cosh(1), 1, math.cosh(1)]),
    ("tanh", [-1, 0, 1], [-math.tanh(1), 0, math.tanh(1)]),
    ("log", [0.5, 1, 2], [math.log(0.5), 0, math.log(2)]),
    ("log10", [0.1, 1, 100], [-1, 0, 2]),
    ("exp", [-1, 0, 1], [math.exp(-1), 1, math.e]),
    ("floor", [-1.1, -0.1, 0.1, 1.1], [-2, -1, 0, 1]),
    ("ceil", [-1.1, -0.1, 0.1, 1.1], [-1, 0, 1, 2]),
    ("round", [-2.5, -1.5, -0.5, 0.5, 1.5, 2.5], [-2, -1, 0, 1, 2, 3]),
    ("cbrt", [-8, -1, 0, 1, 8], [-2, -1, 0, 1, 2]),
    ("signum", [-2, -0.0, 3], [-1, 0, 1]),
    ("erf", [-1, 0, 1], [math.erf(-1), 0, math.erf(1)]),
    ("erfc", [-1, 0, 1], [math.erfc(-1), 1, math.erfc(1)]),
    ("gamma", [0.5, 1, 3], [math.sqrt(math.pi), 1, 2]),
    ("not", [0, -1, 2], [1, 0, 0]),
])
def test_pinned_sdk_serializes_and_computes_each_unary_operation(ee, method, values, expected):
    sdk_method = "Not" if method == "not" else method
    expression = ee.serializer.encode(
        getattr(ee.Array(values), sdk_method)(), for_cloud_api=False)
    call = array_invocation(expression)
    assert call["functionName"] == f"Array.{method}"
    assert set(call["arguments"]) == {"input"}
    actual = compile_expression(expression, [], {})["value"]
    np.testing.assert_allclose(actual, expected, rtol=1e-14, atol=1e-14)


def test_unary_scalar_empty_and_rank_eight_preserve_shape(ee):
    assert output(ee, ee.Array(0.5).sin()) == pytest.approx(math.sin(0.5))

    empty = StaticArray(np.empty((0, 2), dtype=np.float64))
    empty_result = array_unary.invoke_unary(
        Translator([], {}, None), "Array.sin", {"input": empty})
    assert empty_result.data.shape == (0, 2)

    nested = np.full((1,) * 8, 0.5, dtype=np.float64)
    high_rank = array_unary.invoke_unary(
        Translator([], {}, None), "Array.sin", {"input": StaticArray(nested)})
    assert high_rank.data.shape == (1,) * 8
    np.testing.assert_allclose(high_rank.data, math.sin(0.5))


def test_atan_is_radians_and_existing_array_atan2_keeps_x_y_argument_order(ee):
    assert output(ee, ee.Array([-1, 0, 1]).atan()) == pytest.approx(
        [-math.pi / 4, 0, math.pi / 4])
    assert output(ee, ee.Array(-1).atan2(0)) == pytest.approx(math.pi)
    assert output(ee, ee.Array(0).atan2(1)) == pytest.approx(math.pi / 2)


def test_cheap_unary_operation_preserves_the_10000_cell_limit(ee):
    values = output(ee, ee.Array([1] * 10_000).Not())
    assert len(values) == 10_000
    assert set(values) == {0}


def test_unary_result_is_owned_readonly_and_charged_before_the_kernel(monkeypatch):
    source = np.array([0.25, 0.75], dtype=np.float64)
    input_array = StaticArray(source)
    result = array_unary.invoke_unary(
        Translator([], {}, None), "Array.sin", {"input": input_array})
    source[0] = 99
    assert not np.shares_memory(result.data, source)
    assert not result.data.flags.writeable
    assert result.data[0] == pytest.approx(math.sin(0.25))

    at_limit = Translator([], {}, None)
    at_limit.steps = MAX_ARRAY_WORK - 9
    array_unary.invoke_unary(
        at_limit, "Array.sin", {"input": StaticArray(np.array([1.0]))})
    assert at_limit.steps == MAX_ARRAY_WORK

    translator = Translator([], {}, None)
    translator.steps = MAX_ARRAY_WORK - 8

    def forbidden_kernel(*_args, **_kwargs):
        raise AssertionError("Array kernel ran before its work was charged")

    monkeypatch.setattr(array_unary.np, "sin", forbidden_kernel)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        array_unary.invoke_unary(
            translator, "Array.sin", {"input": StaticArray(np.array([1.0]))})
    assert translator.steps == MAX_ARRAY_WORK - 8


@pytest.mark.parametrize("name,value", [
    ("Array.asin", [1.01]), ("Array.acos", [-1.01]),
    ("Array.log", [0]), ("Array.log10", [-1]),
    ("Array.gamma", [0]), ("Array.gamma", [-2]),
    ("Array.exp", [1000]), ("Array.cosh", [1000]),
])
def test_unary_domain_and_overflow_errors(name, value):
    from gee.compat.earthengine.array_values import invoke_array

    with pytest.raises(UnsupportedEEError):
        invoke_array(Translator([], {}, None), name,
                     {"input": StaticArray(np.asarray(value, dtype=np.float64))})


def test_unary_arguments_types_and_static_only_boundary():
    from gee.compat.earthengine.array_values import invoke_array

    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="requires input"):
        invoke_array(translator, "Array.sin", {})
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_array(translator, "Array.sin", {"input": StaticArray(np.array([1.])), "extra": 1})
    with pytest.raises(UnsupportedEEError, match="static ee.Array"):
        invoke_array(translator, "Array.sin", {"input": [1, 2]})
    with pytest.raises(UnsupportedEEError, match="Unsupported static Array"):
        invoke_array(translator, "Array.gammainc", {"input": StaticArray(np.array([1.]))})
