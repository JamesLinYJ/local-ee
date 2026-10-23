"""Pinned SDK Array dtype casts and bounded static semantics."""
import json
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_casts import (
    ARRAY_CAST_ALIAS_MAP,
    ARRAY_CAST_FUNCTIONS,
    invoke_array_cast,
)
from gee.compat.earthengine.array_core import MAX_ARRAY_WORK, StaticArray, wrap_array
from gee.compat.earthengine.decoder import Translator
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
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def invocation(serialized):
    assert serialized["type"] == "CompoundValue"
    scope = dict(serialized["scope"])
    return scope[serialized["value"]["value"]]


def cast(name, value, translator=None):
    return invoke_array_cast(
        translator or Translator([], {}, None), name, {"input": value})


_SDK_CASTS = [
    ("toByte", "Array.toByte", np.uint8),
    ("toInt", "Array.toInt", np.int32),
    ("toInt8", "Array.toInt8", np.int8),
    ("toInt16", "Array.toInt16", np.int16),
    ("toInt32", "Array.toInt32", np.int32),
    ("toInt64", "Array.toInt64", np.int64),
    ("toLong", "Array.toLong", np.int64),
    ("toShort", "Array.toShort", np.int16),
    ("toUint8", "Array.toUint8", np.uint8),
    ("toUint16", "Array.toUint16", np.uint16),
    ("toUint32", "Array.toUint32", np.uint32),
    ("toFloat", "Array.toFloat", np.float32),
    ("toDouble", "Array.toDouble", np.float64),
    ("byte", "Array.byte", np.uint8),
    ("int", "Array.int", np.int32),
    ("int8", "Array.int8", np.int8),
    ("int16", "Array.int16", np.int16),
    ("int32", "Array.int32", np.int32),
    ("int64", "Array.int64", np.int64),
    ("long", "Array.long", np.int64),
    ("short", "Array.short", np.int16),
    ("uint8", "Array.uint8", np.uint8),
    ("uint16", "Array.uint16", np.uint16),
    ("uint32", "Array.uint32", np.uint32),
    ("float", "Array.float", np.float32),
    ("double", "Array.double", np.float64),
]


def test_sdk_1749_serializes_every_cast_and_alias_with_input_only(ee):
    source = ee.Array([1, 2])
    assert ARRAY_CAST_FUNCTIONS == frozenset(name for _, name, _ in _SDK_CASTS)
    assert ARRAY_CAST_ALIAS_MAP == {
        "Array.byte": "Array.toByte",
        "Array.int": "Array.toInt",
        "Array.int8": "Array.toInt8",
        "Array.int16": "Array.toInt16",
        "Array.int32": "Array.toInt32",
        "Array.int64": "Array.toInt64",
        "Array.long": "Array.toLong",
        "Array.short": "Array.toShort",
        "Array.uint8": "Array.toUint8",
        "Array.uint16": "Array.toUint16",
        "Array.uint32": "Array.toUint32",
        "Array.float": "Array.toFloat",
        "Array.double": "Array.toDouble",
    }
    signatures = json.loads(
        (ROOT / "vendor/earthengine-js/algorithms.json").read_text())
    pinned = {
        item["name"].removeprefix("algorithms/"): item
        for item in signatures["algorithms"]
        if item["name"].removeprefix("algorithms/") in ARRAY_CAST_FUNCTIONS
    }
    assert set(pinned) == ARRAY_CAST_FUNCTIONS
    for signature in pinned.values():
        assert signature["returnType"] == "Array"
        assert [arg["argumentName"] for arg in signature["arguments"]] == ["input"]

    for method, function_name, _dtype in _SDK_CASTS:
        expression = getattr(source, method)()
        serialized = ee.serializer.encode(expression, for_cloud_api=False)
        call = invocation(serialized)
        assert call["functionName"] == function_name
        assert set(call["arguments"]) == {"input"}
        assert compile_expression(serialized, [], {})["value"] == [1, 2]


@pytest.mark.parametrize("method,function_name,dtype", _SDK_CASTS)
def test_each_pinned_cast_returns_the_documented_numpy_dtype_and_shape(
        method, function_name, dtype):
    result = cast(function_name, wrap_array([[1, 2], [3, 4]]))
    assert result.data.dtype == np.dtype(dtype)
    assert result.data.shape == (2, 2)
    assert result.to_value() == [[1, 2], [3, 4]]
    assert not result.data.flags.writeable


@pytest.mark.parametrize("name", ["Array.toByte", "Array.byte"])
def test_byte_cast_matches_official_array_byte_rounding_example(name):
    values = wrap_array([-0.1, 0.1, 0.5, 127.1, 255.1, 255.9])
    result = cast(name, values)
    assert result.data.dtype == np.dtype(np.uint8)
    assert result.to_value() == [0, 0, 1, 127, 255, 255]


@pytest.mark.parametrize("name", ["Array.toInt8", "Array.int8"])
def test_other_integer_cast_rounding_and_negative_ties_are_local_inferences(name):
    values = wrap_array([[-1.5, -1.1, -0.5], [0.49, 0.5, 1.5]])
    result = cast(name, values)
    assert result.data.shape == values.data.shape
    assert result.to_value() == [[-1, -1, 0], [0, 1, 2]]


@pytest.mark.parametrize("name,dtype,low,high", [
    ("Array.toInt8", np.int8, -128, 127),
    ("Array.toInt16", np.int16, -32768, 32767),
    ("Array.toInt32", np.int32, -(2**31), 2**31 - 1),
    ("Array.toUint8", np.uint8, 0, 255),
    ("Array.toUint16", np.uint16, 0, 65535),
    ("Array.toUint32", np.uint32, 0, 2**32 - 1),
])
def test_integer_cast_range_edges_and_saturation(name, dtype, low, high):
    result = cast(name, wrap_array([low - 100, low, high, high + 100]))
    assert result.data.dtype == np.dtype(dtype)
    assert result.to_value() == [low, low, high, high]


def test_int64_cast_obeys_exact_float64_boundary_without_wrapping():
    values = wrap_array([
        -(2**53), -(2**53 - 1), -(2**52 + 1), -1,
        1, 2**52 + 1, 2**53 - 1, 2**53,
    ])
    for name in ("Array.toInt64", "Array.int64", "Array.toLong", "Array.long"):
        result = cast(name, values)
        assert result.data.dtype == np.dtype(np.int64)
        assert result.to_value() == [
            -(2**53), -(2**53 - 1), -(2**52 + 1), -1,
            1, 2**52 + 1, 2**53 - 1, 2**53,
        ]

    too_large = StaticArray(np.array([2**53 + 1], dtype=np.int64))
    with pytest.raises(UnsupportedEEError, match="exact Float64"):
        cast("Array.toInt64", too_large)


def test_float_casts_preserve_rank_zero_precision_and_typed_empty_shapes():
    scalar = cast("Array.toFloat", wrap_array(1.1))
    assert scalar.data.shape == ()
    assert scalar.data.dtype == np.dtype(np.float32)
    assert scalar.to_value() == pytest.approx(float(np.float32(1.1)))

    precise = cast("Array.double", wrap_array([1.1]))
    assert precise.data.dtype == np.dtype(np.float64)
    assert precise.to_value() == [1.1]

    empty = StaticArray(np.empty((0, 3), dtype=np.float64))
    for name, dtype in (("Array.toFloat", np.float32), ("Array.toInt16", np.int16)):
        result = cast(name, empty)
        assert result.data.shape == (0, 3)
        assert result.data.dtype == np.dtype(dtype)


def test_cast_rejects_dynamic_boolean_nonfinite_and_float32_overflow_inputs():
    with pytest.raises(UnsupportedEEError, match="static ee.Array"):
        cast("Array.toInt", [1, 2])
    with pytest.raises(UnsupportedEEError, match="booleans"):
        cast("Array.toInt", StaticArray(np.array([True])))
    with pytest.raises(UnsupportedEEError, match="finite real numbers"):
        cast("Array.toInt", StaticArray(np.array([np.inf])))
    with pytest.raises(UnsupportedEEError, match="finite Float32"):
        cast("Array.toFloat", wrap_array([1e100]))

    just_above_max = np.nextafter(
        np.float64(np.finfo(np.float32).max), np.float64(np.inf))
    rounded_to_max = cast("Array.toFloat", wrap_array([just_above_max]))
    assert rounded_to_max.to_value() == [float(np.finfo(np.float32).max)]


def test_cast_checks_required_and_unknown_arguments_and_precharges_work():
    translator = Translator([], {}, None)
    values = wrap_array([1])
    with pytest.raises(UnsupportedEEError, match="requires input"):
        invoke_array_cast(translator, "Array.toInt", {})
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_array_cast(translator, "Array.toInt", {"input": values, "pixelType": "int8"})

    translator.steps = MAX_ARRAY_WORK - 4
    cast("Array.toInt", values, translator)
    assert translator.steps == MAX_ARRAY_WORK

    translator.steps = MAX_ARRAY_WORK - 3
    with pytest.raises(UnsupportedEEError, match="work budget"):
        cast("Array.toInt", values, translator)
    assert translator.steps == MAX_ARRAY_WORK - 3


def test_cast_keeps_rank_cell_and_per_axis_limits():
    rank_eight = StaticArray(np.ones((1,) * 8, dtype=np.float64))
    assert cast("Array.toInt", rank_eight).data.shape == (1,) * 8

    translator = Translator([], {}, None)
    largest = StaticArray(np.arange(10_000, dtype=np.int32))
    result = cast("Array.toInt", largest, translator)
    assert result.data.size == 10_000
    assert translator.steps == 30_001

    too_deep = StaticArray(np.ones((1,) * 9, dtype=np.float64))
    with pytest.raises(UnsupportedEEError, match="rank/cell budget"):
        cast("Array.toInt", too_deep)
    too_many = StaticArray(np.ones(10_001, dtype=np.float64))
    with pytest.raises(UnsupportedEEError, match="rank/cell budget"):
        cast("Array.toInt", too_many)
    oversized_empty_axis = StaticArray(np.empty((0, 10_001), dtype=np.float64))
    with pytest.raises(UnsupportedEEError, match="rank/cell budget"):
        cast("Array.toInt", oversized_empty_axis)
