"""Independent controls for finite quantile-style Reducer leaves."""
from fractions import Fraction
import math
import sys

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.quantile_reducers import (
    QUANTILE_REDUCER_NAMES,
    QuantileReducerLeaf,
    describe_quantile_reducer,
    make_quantile_reducer,
    reduce_quantile_reducer,
)


def budget():
    return Translator([], {}, None)


def make(name, **arguments):
    return make_quantile_reducer(budget(), name, arguments)


def reduce(name, records, **arguments):
    work = budget()
    leaf = make_quantile_reducer(work, name, arguments)
    return dict(reduce_quantile_reducer(work, leaf, records))


def exact(value):
    return Fraction(value) if type(value) is int else Fraction.from_float(value)


def reference_quantile(values, percentile):
    values = sorted(map(exact, values))
    position = Fraction(percentile) * (len(values) - 1) / 100
    lower = position.numerator // position.denominator
    fraction = position - lower
    if fraction == 0:
        return values[lower]
    return values[lower] * (1 - fraction) + values[lower + 1] * fraction


def test_family_signatures_default_names_and_custom_percentile_outputs():
    assert QUANTILE_REDUCER_NAMES == {
        "Reducer.percentile", "Reducer.intervalMean", "Reducer.mode",
    }
    leaf = make("Reducer.percentile", percentiles=[0, 50.0, 100])
    assert describe_quantile_reducer(budget(), leaf) == (
        1, ("p0", "p50", "p100"),
    )
    custom = make(
        "Reducer.percentile", percentiles=[25, 75], outputNames=["q1", "q3"],
    )
    assert describe_quantile_reducer(budget(), custom) == (1, ("q1", "q3"))
    assert describe_quantile_reducer(
        budget(), make("Reducer.intervalMean", minPercentile=25, maxPercentile=75),
    ) == (1, ("intervalMean",))
    assert describe_quantile_reducer(budget(), make("Reducer.mode")) == (1, ("mode",))


@pytest.mark.parametrize("name,arguments", [
    ("Reducer.percentile", {}),
    ("Reducer.percentile", {"percentiles": []}),
    ("Reducer.percentile", {"percentiles": [True]}),
    ("Reducer.percentile", {"percentiles": [math.nan]}),
    ("Reducer.percentile", {"percentiles": [10**10000]}),
    ("Reducer.percentile", {"percentiles": [-1]}),
    ("Reducer.percentile", {"percentiles": [101]}),
    ("Reducer.percentile", {"percentiles": [50], "outputNames": ["x", "y"]}),
    ("Reducer.percentile", {"percentiles": [50], "outputNames": [1]}),
    ("Reducer.percentile", {"percentiles": [50], "maxBuckets": 64}),
    ("Reducer.percentile", {"percentiles": [50], "minBucketWidth": 0.1}),
    ("Reducer.intervalMean", {"minPercentile": 30}),
    ("Reducer.intervalMean", {"minPercentile": 75, "maxPercentile": 25}),
    ("Reducer.intervalMean", {"minPercentile": 0, "maxPercentile": 101}),
    ("Reducer.mode", {"unweighted": True}),
    ("Reducer.mode", {"maxRaw": True}),
    ("Reducer.mode", {"maxRaw": -1}),
])
def test_constructor_rejects_invalid_or_unsupported_parameters(name, arguments):
    with pytest.raises(UnsupportedEEError):
        make_quantile_reducer(budget(), name, arguments)


def test_explicit_null_histogram_parameters_are_accepted_but_other_values_reject():
    leaf = make_quantile_reducer(budget(), "Reducer.mode", {
        "maxBuckets": None, "minBucketWidth": None, "maxRaw": 2,
    })
    assert leaf.max_raw == 2
    with pytest.raises(UnsupportedEEError, match="histogram"):
        make_quantile_reducer(budget(), "Reducer.mode", {"maxBuckets": 8})


@pytest.mark.parametrize("field,value", [
    ("name", "Reducer.median"),
    ("name", "x" * 65),
    ("percentiles", (Fraction(101),)),
    ("percentiles", (Fraction(1, 2**1100),)),
    ("outputs", ("x" * 65,)),
    ("max_raw", True),
])
def test_frozen_leaf_is_revalidated(field, value):
    leaf = make("Reducer.percentile", percentiles=[50])
    object.__setattr__(leaf, field, value)
    with pytest.raises(UnsupportedEEError):
        describe_quantile_reducer(budget(), leaf)


def test_percentiles_match_independent_fraction_reference_and_skip_nulls():
    values = [-4, 0.5, 2**40, 2**40 + 0.25, 9]
    rows = [[value] for value in values] + [[None]]
    actual = reduce(
        "Reducer.percentile", rows, percentiles=[0, 12.5, 50, 87.5, 100],
    )
    assert list(actual) == ["p0", "p12.5", "p50", "p87.5", "p100"]
    for percentile, name in zip([0, 12.5, 50, 87.5, 100], actual):
        assert actual[name] == float(reference_quantile(values, percentile))


def test_interval_mean_uses_local_closed_value_interval_and_returns_null_when_empty():
    result = reduce(
        "Reducer.intervalMean", [[0], [10], [20], [30], [None]],
        minPercentile=25, maxPercentile=75,
    )
    lower = reference_quantile([0, 10, 20, 30], 25)
    upper = reference_quantile([0, 10, 20, 30], 75)
    selected = [Fraction(value) for value in (0, 10, 20, 30)
                if lower <= value <= upper]
    expected = float(sum(selected) / len(selected))
    assert expected == 15.0
    assert result == {"intervalMean": expected}
    assert reduce(
        "Reducer.intervalMean", [[0], [10]], minPercentile=25, maxPercentile=75,
    ) == {"intervalMean": None}
    assert reduce(
        "Reducer.intervalMean", [[None]], minPercentile=0, maxPercentile=100,
    ) == {"intervalMean": None}


def test_mode_counts_exact_values_and_uses_smallest_value_for_local_ties():
    result = reduce("Reducer.mode", [[3], [1], [3], [2], [2], [None]])
    assert result == {"mode": 2.0}
    assert type(result["mode"]) is float
    assert reduce("Reducer.mode", [[-2**53], [2**53]]) == {"mode": float(-2**53)}
    assert reduce("Reducer.mode", [[None]]) == {"mode": None}


def test_maxraw_limits_nonnull_raw_count_without_approximating():
    assert reduce("Reducer.mode", [[1], [None], [2]], maxRaw=2) == {"mode": 1.0}
    with pytest.raises(UnsupportedEEError, match="maxRaw"):
        reduce("Reducer.mode", [[1], [2], [3]], maxRaw=2)


def test_fraction_interpolation_handles_float64_extremes_and_subnormals():
    largest = sys.float_info.max
    assert reduce(
        "Reducer.percentile", [[-largest], [largest]], percentiles=[50],
    ) == {"p50": float(reference_quantile([-largest, largest], 50))}
    smallest = math.nextafter(0.0, 1.0)
    values = [0.0, smallest]
    actual = reduce(
        "Reducer.percentile", [[value] for value in values], percentiles=[25, 50, 75],
    )
    expected = [float(reference_quantile(values, pct)) for pct in (25, 50, 75)]
    assert list(actual.values()) == expected


@pytest.mark.parametrize("value", [True, "4", math.nan, math.inf, -math.inf, 2**53 + 1])
def test_input_values_reject_bool_nonfinite_nonnumber_and_inexact_integer(value):
    with pytest.raises(UnsupportedEEError):
        reduce("Reducer.percentile", [[value]], percentiles=[50])


def test_very_large_integer_value_rejects_before_rational_conversion():
    with pytest.raises(UnsupportedEEError, match=r"±2\^53"):
        reduce("Reducer.mode", [[10**10000]])


@pytest.mark.parametrize("records", [None, (), [[1, 2]], [[1], None]])
def test_row_shape_and_collection_bounds_are_closed(records):
    with pytest.raises(UnsupportedEEError):
        reduce("Reducer.mode", records)
    with pytest.raises(UnsupportedEEError, match="1000"):
        reduce("Reducer.mode", [[1]] * 1001)


def test_full_1000_row_sort_stays_within_the_unchanged_work_budget():
    result = reduce(
        "Reducer.percentile", [[index] for index in range(1000)],
        percentiles=[0, 50, 100],
    )
    assert result == {"p0": 0.0, "p50": 499.5, "p100": 999.0}


def test_work_budget_is_charged_before_row_scan():
    work = budget()
    leaf = make_quantile_reducer(work, "Reducer.percentile", {"percentiles": [50]})
    work.steps = 50_000
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        reduce_quantile_reducer(work, leaf, [[1]])
