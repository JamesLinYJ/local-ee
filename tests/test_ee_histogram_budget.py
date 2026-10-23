"""Histogram accounting charges repeated lookup work, not duplicate output keys."""
from __future__ import annotations

import pytest

import gee.compat.earthengine.aggregate_statistics_histogram as histogram_module
from gee.compat.earthengine.aggregate_statistics_histogram import aggregate_histogram
from gee.compat.earthengine.aggregate_statistics_values import MAX_WORK
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.finite_reducer_discrete import reduce_discrete_leaf
from gee.ee_translate import UnsupportedEEError


def _translator():
    return Translator([], {}, None)


def test_aggregate_histogram_repeated_values_fit_the_shared_budget():
    translator = _translator()
    assert aggregate_histogram(translator, [1] * 1_000) == {"1": 1_000}
    assert translator.steps < MAX_WORK


def test_aggregate_histogram_repeated_string_key_fits_and_counts_once():
    translator = _translator()
    assert aggregate_histogram(translator, ["zone"] * 1_000) == {"zone": 1_000}
    assert translator.steps < MAX_WORK


def test_aggregate_histogram_simple_unique_values_fit_when_their_cost_allows():
    translator = _translator()
    result = aggregate_histogram(translator, list(range(1_000)))
    assert len(result) == 1_000
    assert result["0"] == result["999"] == 1
    assert list(result)[:3] == ["0", "1", "2"]
    assert translator.steps < MAX_WORK


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([1] * 1_000, {"1": 1_000}),
        (list(range(1_000)), {str(value): 1 for value in range(1_000)}),
    ],
)
def test_discrete_histogram_repeated_and_simple_unique_values_fit(values, expected):
    translator = _translator()
    assert reduce_discrete_leaf(
        translator, "frequencyHistogram", values,
    ) == [("histogram", expected)]
    assert translator.steps < MAX_WORK


def test_repeated_keys_preserve_source_order_and_only_grow_output_once():
    translator = _translator()
    assert aggregate_histogram(translator, [2, 1, 2, None, 1]) == {
        "2": 2,
        "1": 2,
    }


@pytest.mark.parametrize(
    "values",
    [
        ["x" * 50_001],
        ["x" * 50] * 1_000,
    ],
)
def test_long_or_repeated_long_keys_fail_the_work_budget(values):
    with pytest.raises(UnsupportedEEError, match="shared 50000-step compilation work budget"):
        aggregate_histogram(_translator(), values)


def test_distinct_values_that_stringify_to_one_key_still_fail_closed():
    with pytest.raises(UnsupportedEEError, match="collide after conversion"):
        aggregate_histogram(_translator(), ["1", 1])


def test_public_json_output_limit_is_checked_before_growing_the_result(monkeypatch):
    monkeypatch.setattr(histogram_module, "MAX_PUBLIC_BYTES", 7)
    with pytest.raises(UnsupportedEEError, match="1 MB public JSON limit"):
        aggregate_histogram(_translator(), [1])
