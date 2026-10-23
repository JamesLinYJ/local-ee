from decimal import Decimal, localcontext
import math
import statistics

import pytest

from gee.compat.earthengine.finite_reducer_numeric import (
    MAX_NUMERIC_REDUCER_VALUES,
    NUMERIC_REDUCER_OUTPUTS,
    reduce_numeric_leaf,
)
from gee.compat.earthengine.ir import UnsupportedEEError


class Budget:
    def __init__(self, steps=0):
        self.steps = steps


def pairs(translator, name, values):
    return dict(reduce_numeric_leaf(translator, name, values))


def decimal_variance(values, *, sample=False):
    with localcontext() as context:
        context.prec = 100
        converted = [Decimal.from_float(float(value)) for value in values]
        mean = sum(converted) / len(converted)
        divisor = len(converted) - 1 if sample else len(converted)
        return sum((value - mean) ** 2 for value in converted) / divisor


def test_leaf_names_and_pinned_output_name_contract():
    assert NUMERIC_REDUCER_OUTPUTS == {
        "minMax": ("min", "max"),
        "product": ("product",),
        "stdDev": ("stdDev",),
        "variance": ("variance",),
        "sampleVariance": ("variance",),
    }


def test_min_max_skips_nulls_and_returns_both_named_outputs():
    assert pairs(Budget(), "minMax", [None, 4, -2, None, 3]) == {
        "min": -2.0,
        "max": 4.0,
    }
    assert pairs(Budget(), "minMax", []) == {"min": None, "max": None}
    assert pairs(Budget(), "minMax", [None, None]) == {
        "min": None,
        "max": None,
    }


def test_product_uses_normalized_factors_across_overflow_and_underflow_ranges():
    values = [1e308, 1e308, 1e-308, 1e-308]
    expected = Decimal(1)
    for value in values:
        expected *= Decimal.from_float(value)
    result = pairs(Budget(), "product", values)["product"]
    assert result == pytest.approx(float(expected), rel=5e-15)

    # The first two factors underflow to zero if multiplied directly, while
    # the final mathematical product is still a representable subnormal-scale
    # value.
    tiny = [math.ulp(0.0), math.ulp(0.0), 1e308, 1e308]
    expected = Decimal(1)
    for value in tiny:
        expected *= Decimal.from_float(value)
    result = pairs(Budget(), "product", tiny)["product"]
    assert result == pytest.approx(float(expected), rel=5e-15)


def test_product_identity_sign_and_final_overflow_policy():
    assert pairs(Budget(), "product", [None, None]) == {"product": 1.0}
    assert math.copysign(1.0, pairs(Budget(), "product", [-0.0, 2.0])["product"]) == -1.0
    assert pairs(Budget(), "product", [-2, -3]) == {"product": 6.0}
    with pytest.raises(UnsupportedEEError, match="product exceeds"):
        pairs(Budget(), "product", [1e308, 1e308])


def test_dispersion_uses_centered_statistics_for_large_common_offsets():
    values = [1e16 - 4, 1e16 - 2, 1e16, 1e16 + 2, 1e16 + 4]
    assert pairs(Budget(), "variance", values)["variance"] == pytest.approx(
        statistics.pvariance(values), rel=1e-15,
    )
    assert pairs(Budget(), "sampleVariance", values)["variance"] == pytest.approx(
        statistics.variance(values), rel=1e-15,
    )
    assert pairs(Budget(), "stdDev", values)["stdDev"] == pytest.approx(
        math.sqrt(statistics.pvariance(values)), rel=1e-15,
    )
    assert pairs(Budget(), "variance", values)["variance"] == pytest.approx(
        float(decimal_variance(values)), rel=1e-15,
    )


def test_requested_stddev_does_not_square_an_unrepresentable_variance():
    values = [-1e308, 1e308]
    expected = float(decimal_variance(values).sqrt())
    assert pairs(Budget(), "stdDev", values)["stdDev"] == pytest.approx(expected, rel=1e-15)
    with pytest.raises(UnsupportedEEError):
        pairs(Budget(), "variance", values)


def test_variance_underflow_and_empty_singleton_rules_are_explicit():
    assert pairs(Budget(), "stdDev", [None]) == {"stdDev": None}
    assert pairs(Budget(), "variance", []) == {"variance": None}
    assert pairs(Budget(), "variance", [9]) == {"variance": 0.0}
    assert pairs(Budget(), "sampleVariance", [9]) == {"variance": None}
    assert pairs(Budget(), "stdDev", [9]) == {"stdDev": 0.0}

    values = [-1e-200, 1e-200]
    expected = float(decimal_variance(values))
    assert pairs(Budget(), "variance", values)["variance"] == expected == 0.0


@pytest.mark.parametrize("bad", [True, "2", [], float("inf"), float("nan"), 2**53 + 1])
@pytest.mark.parametrize("name", list(NUMERIC_REDUCER_OUTPUTS))
def test_all_leaves_validate_every_non_null_input(bad, name):
    with pytest.raises(UnsupportedEEError):
        reduce_numeric_leaf(Budget(), name, [0, bad])


def test_zero_product_still_validates_later_values():
    with pytest.raises(UnsupportedEEError):
        reduce_numeric_leaf(Budget(), "product", [0, True])


def test_exact_integer_boundary_and_1000_value_limit():
    assert pairs(Budget(), "minMax", [-(2**53), 2**53]) == {
        "min": float(-(2**53)),
        "max": float(2**53),
    }
    values = list(range(MAX_NUMERIC_REDUCER_VALUES))
    translator = Budget()
    assert pairs(translator, "minMax", values) == {"min": 0.0, "max": 999.0}
    assert translator.steps <= 50_000
    with pytest.raises(UnsupportedEEError, match="at most 1000"):
        reduce_numeric_leaf(Budget(), "minMax", values + [1000])


def test_work_is_reserved_before_numeric_materialization_and_shares_existing_budget():
    translator = Budget(49_999)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        reduce_numeric_leaf(translator, "minMax", [])
    assert translator.steps == 49_999

    translator = Budget(30_000)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        reduce_numeric_leaf(translator, "variance", [1.0] * 1_000)
    assert translator.steps == 30_000


def test_values_must_be_a_list_within_the_preflight_bound():
    with pytest.raises(UnsupportedEEError, match="at most 1000"):
        reduce_numeric_leaf(Budget(), "product", tuple(range(2)))
    with pytest.raises(UnsupportedEEError, match="at most 1000"):
        reduce_numeric_leaf(Budget(), "product", list(range(1_001)))
