"""Pinned Python List layout serialization and bounded static controls."""
from copy import deepcopy
from pathlib import Path

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


def invocation(expression, function_name):
    for _, node in reversed(expression.get("scope", [])):
        if isinstance(node, dict) and node.get("functionName") == function_name:
            return node
    if expression.get("type") == "Invocation" and expression.get("functionName") == function_name:
        return expression
    raise AssertionError(f"No {function_name} invocation in SDK serialization")


def add_unknown_argument(expression, function_name):
    result = deepcopy(expression)
    invocation(result, function_name)["arguments"]["unexpected"] = 1
    return result


def replace_argument(expression, function_name, argument, value):
    result = deepcopy(expression)
    invocation(result, function_name)["arguments"][argument] = value
    return result


def test_zip_truncates_to_the_shorter_list_and_handles_empty_inputs(ee):
    zipped = ee.List(["a", "b", "c", "d"]).zip([10, 20])
    assert output(ee, zipped) == [["a", 10], ["b", 20]]
    assert output(ee, ee.List([]).zip([10])) == []
    assert output(ee, ee.List([10]).zip([])) == []


def test_unzip_transposes_ragged_rows_only_to_the_shortest_width(ee):
    rows = [[10, 11, 12], [20, 21], [30, 31, 32, 33]]
    # Independent transpose of columns shared by every row.
    expected = [[10, 20, 30], [11, 21, 31]]
    assert output(ee, ee.List(rows).unzip()) == expected
    assert output(ee, ee.List([[1, 2], [], [3]]).unzip()) == []
    assert output(ee, ee.List([]).unzip()) == []


def test_flatten_recurses_through_lists_and_keeps_ee_array_as_a_typed_leaf(ee):
    value = ee.List([
        ee.List([1, ee.List([2, ee.List([3])])]),
        ee.List([4, 5]),
        ee.Array([[7, 8], [9, 10]]),
    ]).flatten()
    assert output(ee, value) == [1, 2, 3, 4, 5, [[7, 8], [9, 10]]]
    assert output(ee, ee.List([]).flatten()) == []

    extracted = ee.Array(value.get(5))
    assert output(ee, extracted.get([1, 0])) == 9
    assert output(ee, extracted.length().toList()) == [2, 2]


def test_repeat_accepts_nested_dictionary_values_and_zero_count(ee):
    value = ee.Dictionary({"label": "sample", "vector": ee.Array([4, 7])})
    repeated = ee.List.repeat(value, 2)
    assert output(ee, repeated) == [
        {"label": "sample", "vector": [4, 7]},
        {"label": "sample", "vector": [4, 7]},
    ]
    assert output(ee, ee.List.repeat(value, 0)) == []


@pytest.mark.parametrize("count", [0, 1])
def test_sdk_repeat_none_omits_required_value_and_compiler_rejects_wire_form(ee, count):
    # SDK 1.7.49 serializes None by omitting this Object argument, even though
    # List.repeat requires it. Keep the S success and C rejection explicit.
    expression = encode(ee, ee.List.repeat(None, count))
    assert expression == {
        "type": "Invocation",
        "functionName": "List.repeat",
        "arguments": {"count": count},
    }
    with pytest.raises(UnsupportedEEError, match="List.repeat requires value"):
        compile_expression(expression, [], {})


def test_reverse_set_and_swap_preserve_order_with_negative_indices(ee):
    source = ee.List([10, 20, 30, 40])
    assert output(ee, source.reverse()) == [40, 30, 20, 10]
    assert output(ee, ee.List([]).reverse()) == []

    # -2 addresses the second-to-last element; swap's negative positions count
    # back from the end, as documented by the pinned SDK.
    assert output(ee, source.set(-2, 99)) == [10, 20, 99, 40]
    assert output(ee, source.swap(-1, 0)) == [40, 20, 30, 10]
    assert output(ee, source.swap(-4, -1)) == [40, 20, 30, 10]


@pytest.mark.parametrize("value", [
    lambda ee: ee.List([1, 2]).set(2, 9),
    lambda ee: ee.List([1, 2]).set(-3, 9),
    lambda ee: ee.List([]).set(0, 9),
    lambda ee: ee.List([1, 2]).set(1.5, 9),
    lambda ee: ee.List([1, 2]).set(True, 9),
    lambda ee: ee.List([1, 2]).swap(0, 2),
    lambda ee: ee.List([1, 2]).swap(-3, 1),
    lambda ee: ee.List([]).swap(0, 0),
    lambda ee: ee.List([1, 2]).swap(True, 0),
])
def test_set_and_swap_reject_invalid_or_out_of_range_positions(ee, value):
    with pytest.raises(UnsupportedEEError):
        output(ee, value(ee))


@pytest.mark.parametrize("count", [True, -1, 1.5, 10001])
def test_repeat_rejects_boolean_negative_fractional_or_oversized_counts(ee, count):
    # SDK 1.7.49 serializes these Integer-typed arguments without coercing
    # them, so the local compiler receives and validates the original value.
    expression = encode(ee, ee.List.repeat("x", count))
    with pytest.raises(UnsupportedEEError):
        compile_expression(expression, [], {})


def test_repeat_accepts_10000_values_and_flatten_stays_within_shared_budget(ee):
    repeated = ee.List.repeat("x", 10000)
    assert output(ee, repeated.length()) == 10000
    # Flatten scans and emits each value under the shared work budget, so use
    # a near-boundary list that leaves room for the compiler's own traversal.
    assert output(ee, ee.List(list(range(9000))).flatten().length()) == 9000


def test_flatten_obeys_the_decoder_depth_limit_on_sdk_wire_values(ee):
    # Build the official List.flatten invocation, then provide a literal nested
    # list as its argument so this specifically exercises the decoder's depth
    # preflight rather than Python-side SDK recursion.
    wire = invocation(encode(ee, ee.List([0]).flatten()), "List.flatten")
    deepest_valid = 0
    for _ in range(95):
        deepest_valid = [deepest_valid]
    valid = deepcopy(wire)
    valid["arguments"]["list"] = deepest_valid
    assert compile_expression(valid, [], {})["value"] == [0]

    too_deep = [deepest_valid]
    invalid = deepcopy(wire)
    invalid["arguments"]["list"] = too_deep
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        compile_expression(invalid, [], {})


def test_list_layout_operations_share_the_compilation_work_budget(ee):
    value = ee.List.repeat(0, 9000)
    for _ in range(6):
        value = value.reverse()
    with pytest.raises(UnsupportedEEError, match="work budget|compilation limits"):
        output(ee, value.length())


def test_invalid_unzip_and_nonlist_zip_inputs_fail_in_compiler(ee):
    with pytest.raises(UnsupportedEEError, match="every element.*static List"):
        output(ee, ee.List([[1, 2], 3]).unzip())

    valid = encode(ee, ee.List([1]).zip([2]))
    malformed = replace_argument(valid, "List.zip", "other", 2)
    with pytest.raises(UnsupportedEEError, match="requires a static List"):
        compile_expression(malformed, [], {})


def test_unknown_arguments_are_rejected_for_each_layout_operation(ee):
    values = [
        (ee.List([1]).zip([2]), "List.zip"),
        (ee.List([[1], [2]]).unzip(), "List.unzip"),
        (ee.List([[1]]).flatten(), "List.flatten"),
        (ee.List.repeat(1, 1), "List.repeat"),
        (ee.List([1]).reverse(), "List.reverse"),
        (ee.List([1]).set(0, 2), "List.set"),
        (ee.List([1]).swap(0, 0), "List.swap"),
    ]
    for value, name in values:
        malformed = add_unknown_argument(encode(ee, value), name)
        with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
            compile_expression(malformed, [], {})
