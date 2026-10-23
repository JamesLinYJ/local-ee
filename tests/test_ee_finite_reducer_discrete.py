"""Focused contracts for bounded finite discrete Reducer leaves."""
import numpy as np
import pytest

from gee.compat.earthengine.array_values import StaticArray
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.finite_reducer_discrete import (
    DISCRETE_REDUCER_OUTPUTS,
    reduce_discrete_leaf,
)
from gee.compat.earthengine.ir import Pixel, UnsupportedEEError


def reduce(name, values, translator=None):
    translator = translator or Translator([], {}, {})
    return translator, reduce_discrete_leaf(translator, name, values)


@pytest.mark.parametrize(("name", "expected"), [
    ("countEvery", [("count", 4)]),
    ("countDistinct", [("count", 3)]),
    ("countDistinctNonNull", [("count", 2)]),
    ("countRuns", [("count", 4)]),
    ("frequencyHistogram", [("histogram", {
        "1": 2, "true": 1, "false": 1, "a": 2,
    })]),
    ("allNonZero", [("all", 0)]),
    ("anyNonZero", [("any", 1)]),
    ("and", [("all", 0)]),
    ("or", [("any", 1)]),
    ("bitwiseAnd", [("bitwiseAnd", 2)]),
    ("bitwiseOr", [("bitwiseOr", 15)]),
])
def test_discrete_scalar_results_use_independent_expected_values(name, expected):
    values = {
        "countEvery": [1, None, {"ignored": [True]}, "x"],
        "countDistinct": [1, 1.0, True, None, None],
        "countDistinctNonNull": [1, 1.0, True, None, None],
        "countRuns": [1, 1.0, None, True, 1, 1, None, 2],
        "frequencyHistogram": [1, 1.0, True, False, None, "a", "a"],
        "allNonZero": [2, -1, None, 0.0],
        "anyNonZero": [0, None, -2],
        "and": [1, 3, 0],
        "or": [0, 3, 0],
        "bitwiseAnd": [15, 6.0, 3],
        "bitwiseOr": [8, 3, 4],
    }[name]
    _, result = reduce(name, values)
    assert result == expected


@pytest.mark.parametrize(("name", "expected"), [
    ("countEvery", [("count", 0)]),
    ("countDistinct", [("count", 0)]),
    ("countDistinctNonNull", [("count", 0)]),
    ("firstNonNull", [("first", None)]),
    ("lastNonNull", [("last", None)]),
    ("countRuns", [("count", 0)]),
    ("frequencyHistogram", [("histogram", {})]),
    ("allNonZero", [("all", 1)]),
    ("and", [("all", 1)]),
    ("anyNonZero", [("any", 0)]),
    ("or", [("any", 0)]),
    ("bitwiseAnd", [("bitwiseAnd", -1)]),
    ("bitwiseOr", [("bitwiseOr", 0)]),
])
def test_empty_reducer_identities_are_bounded_and_typed(name, expected):
    _, result = reduce(name, [])
    assert result == expected


def test_non_null_first_and_last_return_owned_nested_json_and_arrays():
    source = {"rows": [None, {"label": "first"}], "array": StaticArray(np.array([2.0, 4.0]))}
    _, first = reduce("firstNonNull", [None, source, {"later": True}])
    _, last = reduce("lastNonNull", [source, None, {"later": [True]}])
    first_value = first[0][1]
    last_value = last[0][1]
    assert first_value["rows"] == source["rows"]
    assert first_value["array"].data.tolist() == [2.0, 4.0]
    assert last_value == {"later": [True]}
    assert not np.shares_memory(source["array"].data, first_value["array"].data)
    assert not first_value["array"].data.flags.writeable
    first_value["rows"][1]["label"] = "changed"
    assert source["rows"][1]["label"] == "first"


def test_histogram_key_collisions_fail_instead_of_overwriting():
    with pytest.raises(UnsupportedEEError, match="collide"):
        reduce("frequencyHistogram", ["1", 1])


def test_count_every_counts_zero_selected_column_rows_represented_by_nulls():
    assert reduce("countEvery", [None, None, None])[1] == [("count", 3)]


@pytest.mark.parametrize(("name", "values", "message"), [
    ("countDistinct", [1, []], "scalar"),
    ("frequencyHistogram", [None, {"x": 1}], "scalar"),
    ("allNonZero", [0, True], "numbers"),
    ("anyNonZero", [1, "bad"], "numbers"),
    ("and", [0, float("nan")], "finite numbers"),
    ("or", [0, float("inf")], "finite numbers"),
    ("bitwiseAnd", [1, 1.5], "integer-valued"),
    ("bitwiseOr", [1, 2**53 + 1], "exact"),
])
def test_operation_domains_reject_unsupported_inputs(name, values, message):
    with pytest.raises(UnsupportedEEError, match=message):
        reduce(name, values)


def test_bitwise_reducers_follow_signed_integer_examples_and_reject_rounded_output():
    assert reduce("bitwiseAnd", [-1, 0xFF])[1] == [("bitwiseAnd", 255)]
    assert reduce("bitwiseAnd", [-1, -2])[1] == [("bitwiseAnd", -2)]
    with pytest.raises(UnsupportedEEError, match="result exceeds"):
        reduce("bitwiseOr", [2**53, 1])


@pytest.mark.parametrize("name", ["countEvery", "firstNonNull", "anyNonZero"])
def test_invalid_dynamic_or_cyclic_later_rows_are_checked_before_selection(name):
    dynamic = Pixel("constant", (1,))
    with pytest.raises(UnsupportedEEError, match="finite static JSON or Array"):
        reduce(name, [1, dynamic] if name != "firstNonNull" else [0, dynamic])

    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(UnsupportedEEError, match="cycles"):
        reduce(name, [1, cyclic] if name != "firstNonNull" else [0, cyclic])


def test_exact_integer_validation_applies_inside_ignored_nested_values():
    with pytest.raises(UnsupportedEEError, match="exact"):
        reduce("firstNonNull", ["selected", {"ignored": [2**53 + 1]}])


def test_shared_work_and_row_limits_apply_before_reduction():
    translator = Translator([], {}, {})
    translator.steps = 49_998
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        reduce("countEvery", [], translator)
    with pytest.raises(UnsupportedEEError, match="at most 1000"):
        reduce("countEvery", [0] * 1001)


def test_output_names_cover_the_discrete_leaf_contract():
    assert set(DISCRETE_REDUCER_OUTPUTS) == {
        "countEvery", "countDistinct", "countDistinctNonNull", "firstNonNull",
        "lastNonNull", "countRuns", "frequencyHistogram", "allNonZero",
        "anyNonZero", "and", "or", "bitwiseAnd", "bitwiseOr",
    }
