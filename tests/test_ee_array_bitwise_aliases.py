"""Pinned static Array bitwise semantics and official SDK bindings."""
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_bitwise import (
    ARRAY_BITWISE_ALIAS_MAP,
    ARRAY_BITWISE_FUNCTIONS,
    invoke_array_bitwise,
)
from gee.compat.earthengine.array_core import (
    MAX_ARRAY_CELLS,
    MAX_ARRAY_WORK,
    StaticArray,
    wrap_array,
)
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.integer_aliases import (
    NUMBER_INTEGER_ALIAS_FUNCTIONS,
    NUMBER_INTEGER_ALIAS_MAP,
    canonical_integer_name,
)
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


def invoke(name, **arguments):
    return invoke_array_bitwise(Translator([], {}, None), name, arguments)


def output(ee, value):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, [], {})["value"]


def final_invocation(serialized):
    if serialized["type"] == "Invocation":
        return serialized
    assert serialized["type"] == "CompoundValue"
    reference = serialized["value"]["value"]
    return dict(serialized["scope"])[reference]


def test_array_bit_count_and_smallest_signed_not_preserve_shape():
    values = wrap_array([[0, -1], [-2, 25]])
    counts = invoke("Array.bitCount", input=values)
    assert counts.to_value() == [[0, 64], [63, 3]]
    assert counts.data.dtype == np.int64
    assert counts.data.shape == values.data.shape
    assert not counts.data.flags.writeable

    source = np.array([[-128, -129], [127, 128]], dtype=np.int64)
    complemented = invoke("Array.bitwiseNot", input=StaticArray(source))
    assert complemented.to_value() == [[127, 128], [-128, -129]]
    assert complemented.data.dtype == np.int64
    assert complemented.data.shape == source.shape
    assert not np.shares_memory(complemented.data, source)


@pytest.mark.parametrize(("name", "expected"), [
    ("Array.bitwiseAnd", [17, 17]),
    ("Array.bitwiseOr", [29, 29]),
    ("Array.bitwiseXor", [12, 12]),
    ("Array.bitwise_and", [17, 17]),
    ("Array.bitwise_or", [29, 29]),
    ("Array.bitwise_xor", [12, 12]),
])
def test_array_binary_bitwise_algorithms_and_pinned_aliases(name, expected):
    result = invoke(
        name,
        left=wrap_array([25, 21]),
        right=wrap_array([21, 25]),
    )
    assert result.to_value() == expected
    assert result.data.shape == (2,)
    assert result.data.dtype == np.int64
    assert not result.data.flags.writeable


def test_array_shift_algorithms_use_scalar_counts_and_signed_right_shift():
    left = wrap_array([-8, 20])
    assert invoke("Array.rightShift", left=left, right=wrap_array(2)).to_value() == [-2, 5]
    assert invoke(
        "Array.right_shift", left=left, right=wrap_array([2, 2])
    ).to_value() == [-2, 5]
    assert invoke(
        "Array.leftShift", left=wrap_array([20, 3]), right=wrap_array(2)
    ).to_value() == [80, 12]
    assert invoke(
        "Array.left_shift", left=wrap_array([20, 3]), right=wrap_array([2, 3])
    ).to_value() == [80, 24]


@pytest.mark.parametrize(("name", "arguments", "message"), [
    ("Array.bitwiseAnd", {"left": [-1], "right": [1]}, "negative operands"),
    ("Array.bitwiseOr", {"left": [2**53], "right": [1]}, "exact Float64"),
    ("Array.bitwiseXor", {"left": [1, 2], "right": [[1, 2]]}, "same shape"),
    ("Array.leftShift", {"left": [-1], "right": [1]}, "negative inputs"),
    ("Array.leftShift", {"left": [2**53], "right": [11]}, "signed 64-bit"),
    ("Array.rightShift", {"left": [1], "right": [-1]}, r"in \[0, 63\]"),
    ("Array.rightShift", {"left": [1], "right": [64]}, r"in \[0, 63\]"),
])
def test_array_bitwise_operations_reject_unverified_domains(name, arguments, message):
    normalized = {
        key: wrap_array(value) if isinstance(value, list) else value
        for key, value in arguments.items()
    }
    with pytest.raises(UnsupportedEEError, match=message):
        invoke_array_bitwise(Translator([], {}, None), name, normalized)


def test_array_bitwise_checks_integral_finite_values_and_owned_arguments():
    with pytest.raises(UnsupportedEEError, match="finite integers"):
        invoke("Array.bitCount", input=StaticArray(np.array([1.5])))
    with pytest.raises(UnsupportedEEError, match="integers, not booleans|finite real"):
        invoke("Array.bitCount", input=StaticArray(np.array([True])))
    with pytest.raises(UnsupportedEEError, match="finite integers"):
        invoke("Array.bitwiseNot", input=StaticArray(np.array([np.inf])))
    with pytest.raises(UnsupportedEEError, match="static ee.Array"):
        invoke("Array.bitCount", input=[1, 2])
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke("Array.bitCount", input=wrap_array([1]), width=8)


def test_array_bitwise_precharges_the_existing_shared_work_budget():
    translator = Translator([], {}, None)
    translator.steps = MAX_ARRAY_WORK - 1
    values = wrap_array([1])
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_array_bitwise(translator, "Array.bitCount", {"input": values})
    assert translator.steps == MAX_ARRAY_WORK - 1


def test_array_bitwise_keeps_rank_eight_and_ten_thousand_cell_boundaries():
    rank_eight = StaticArray(np.ones((1,) * 8, dtype=np.int64))
    assert invoke("Array.bitCount", input=rank_eight).data.shape == (1,) * 8

    translator = Translator([], {}, None)
    largest = wrap_array(np.ones(MAX_ARRAY_CELLS, dtype=np.int64))
    result = invoke_array_bitwise(translator, "Array.bitCount", {"input": largest})
    assert result.data.size == MAX_ARRAY_CELLS
    assert translator.steps == MAX_ARRAY_WORK

    too_deep = StaticArray(np.ones((1,) * 9, dtype=np.int64))
    with pytest.raises(UnsupportedEEError, match="rank/cell budget"):
        invoke("Array.bitCount", input=too_deep)
    too_many = StaticArray(np.ones(MAX_ARRAY_CELLS + 1, dtype=np.int64))
    with pytest.raises(UnsupportedEEError, match="rank/cell budget"):
        invoke("Array.bitCount", input=too_many)


def test_sdk_1749_serializes_array_names_arguments_and_scalar_shift_arrays(ee):
    array = ee.Array([25, 21])
    other = ee.Array([21, 25])
    cases = [
        ("Array.bitCount", array.bitCount(), {"input"}),
        ("Array.bitwiseNot", array.bitwiseNot(), {"input"}),
        ("Array.bitwiseAnd", array.bitwiseAnd(other), {"left", "right"}),
        ("Array.bitwiseOr", array.bitwiseOr(other), {"left", "right"}),
        ("Array.bitwiseXor", array.bitwiseXor(other), {"left", "right"}),
        ("Array.leftShift", array.leftShift(2), {"left", "right"}),
        ("Array.rightShift", array.rightShift(2), {"left", "right"}),
        ("Array.bitwise_and", array.bitwise_and(other), {"left", "right"}),
        ("Array.bitwise_not", array.bitwise_not(), {"input"}),
        ("Array.bitwise_or", array.bitwise_or(other), {"left", "right"}),
        ("Array.bitwise_xor", array.bitwise_xor(other), {"left", "right"}),
        ("Array.left_shift", array.left_shift(2), {"left", "right"}),
        ("Array.right_shift", array.right_shift(2), {"left", "right"}),
    ]
    assert ARRAY_BITWISE_FUNCTIONS == frozenset(name for name, _, _ in cases)
    for name, expression, argument_names in cases:
        serialized = ee.serializer.encode(expression, for_cloud_api=False)
        invocation = final_invocation(serialized)
        assert invocation["functionName"] == name
        assert set(invocation["arguments"]) == argument_names
    for _, expression, _ in cases[5:7] + cases[11:13]:
        serialized = ee.serializer.encode(expression, for_cloud_api=False)
        invocation = final_invocation(serialized)
        references = dict(serialized["scope"])
        right_ref = invocation["arguments"]["right"]["value"]
        right_array = references[right_ref]
        assert right_array["functionName"] == "Array"
        assert right_array["arguments"]["values"] == 2


@pytest.mark.parametrize(("method", "left", "right", "expected"), [
    ("bitCount", [0, -1, -2], None, [0, 64, 63]),
    ("bitwiseNot", [-128, -129, 127, 128], None, [127, 128, -128, -129]),
    ("bitwiseAnd", [25, 21], [21, 25], [17, 17]),
    ("bitwiseOr", [25, 21], [21, 25], [29, 29]),
    ("bitwiseXor", [25, 21], [21, 25], [12, 12]),
    ("leftShift", [20, 3], 2, [80, 12]),
    ("rightShift", [-8, 20], 2, [-2, 5]),
    ("bitwise_not", [-128, -129, 127, 128], None, [127, 128, -128, -129]),
    ("bitwise_and", [25, 21], [21, 25], [17, 17]),
    ("bitwise_or", [25, 21], [21, 25], [29, 29]),
    ("bitwise_xor", [25, 21], [21, 25], [12, 12]),
    ("left_shift", [20, 3], 2, [80, 12]),
    ("right_shift", [-8, 20], 2, [-2, 5]),
])
def test_official_sdk_array_operations_compile_to_exact_values(ee, method, left, right, expected):
    operation = getattr(ee.Array(left), method)
    expression = operation() if right is None else operation(
        ee.Array(right) if isinstance(right, list) else right
    )
    assert output(ee, expression) == expected


def test_pinned_number_snake_case_aliases_serialize_with_expected_arguments(ee):
    expected_names = {
        "Number.bitwiseAnd", "Number.bitwiseNot", "Number.bitwiseOr",
        "Number.bitwiseXor", "Number.leftShift", "Number.rightShift",
    }
    assert NUMBER_INTEGER_ALIAS_FUNCTIONS == frozenset(NUMBER_INTEGER_ALIAS_MAP)
    assert set(NUMBER_INTEGER_ALIAS_MAP.values()) == expected_names
    assert canonical_integer_name("Number.bitwise_and") == "Number.bitwiseAnd"
    assert canonical_integer_name("Number.bitCount") == "Number.bitCount"
    cases = [
        ("Number.bitwise_and", ee.Number(25).bitwise_and(21), {"left", "right"}),
        ("Number.bitwise_or", ee.Number(25).bitwise_or(21), {"left", "right"}),
        ("Number.bitwise_xor", ee.Number(25).bitwise_xor(21), {"left", "right"}),
        ("Number.bitwise_not", ee.Number(25).bitwise_not(), {"input"}),
        ("Number.left_shift", ee.Number(20).left_shift(2), {"left", "right"}),
        ("Number.right_shift", ee.Number(-8).right_shift(2), {"left", "right"}),
    ]
    for name, expression, argument_names in cases:
        serialized = ee.serializer.encode(expression, for_cloud_api=False)
        invocation = final_invocation(serialized)
        assert invocation["functionName"] == name
        assert set(invocation["arguments"]) == argument_names


@pytest.mark.parametrize(("method", "left", "right", "expected"), [
    ("bitwise_and", 25, 21, 17),
    ("bitwise_or", 25, 21, 29),
    ("bitwise_xor", 25, 21, 12),
    ("bitwise_not", 25, None, -26),
    ("left_shift", 20, 2, 80),
    ("right_shift", -8, 2, -2),
])
def test_number_snake_case_aliases_compile_to_audited_integer_semantics(
    ee, method, left, right, expected,
):
    operation = getattr(ee.Number(left), method)
    expression = operation() if right is None else operation(right)
    assert output(ee, expression) == expected
