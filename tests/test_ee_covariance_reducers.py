from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext

import numpy as np
import pytest

from gee.compat.earthengine.array_core import StaticArray
from gee.compat.earthengine.covariance_reducers import (
    COVARIANCE_REDUCER_NAMES,
    MAX_COVARIANCE_ROWS,
    CovarianceReducerLeaf,
    describe_covariance_reducer,
    make_covariance_reducer,
    reduce_covariance_reducer,
)
from gee.compat.earthengine.ir import UnsupportedEEError


class Budget:
    def __init__(self, steps=0):
        self.steps = steps

    @staticmethod
    def allowed(arguments, names):
        if set(arguments) - names:
            raise UnsupportedEEError("Unexpected constructor argument")


def vector(values, dtype=None):
    data = np.asarray(values, dtype=dtype)
    data.flags.writeable = False
    return StaticArray(data)


def leaf(name="covariance"):
    return CovarianceReducerLeaf(name)


def reduce(name, rows, budget=None):
    return dict(reduce_covariance_reducer(budget or Budget(), leaf(name), rows))["array"]


def decimal_reference(rows, *, centered=False):
    with localcontext() as context:
        context.prec = 100
        values = [
            [Decimal.from_float(float(item)) for item in row]
            for row in rows
        ]
        width = len(values[0])
        count = len(values)
        means = [
            sum((row[column] for row in values), Decimal()) / count
            for column in range(width)
        ]
        divisor = Decimal(count - 1)
        return [
            [
                float(sum((
                    (row[left] if centered else row[left] - means[left])
                    * (row[right] if centered else row[right] - means[right])
                    for row in values
                ), Decimal()) / divisor)
                for right in range(width)
            ]
            for left in range(width)
        ]


def matrix(result):
    assert type(result) is StaticArray
    assert result.data.ndim == 2
    assert not result.data.flags.writeable
    assert result.data.flags.owndata
    return result.data


def test_closed_leaf_constructor_and_output_contract():
    budget = Budget()
    assert COVARIANCE_REDUCER_NAMES == {
        "Reducer.covariance", "Reducer.centeredCovariance",
    }
    covariance = make_covariance_reducer(budget, "Reducer.covariance", {})
    centered = make_covariance_reducer(
        budget, "Reducer.centeredCovariance", {},
    )
    assert covariance == leaf("covariance")
    assert centered == leaf("centeredCovariance")
    assert describe_covariance_reducer(budget, covariance) == (1, ("array",))
    assert describe_covariance_reducer(budget, centered) == (1, ("array",))
    with pytest.raises(FrozenInstanceError):
        covariance.name = "other"
    with pytest.raises(UnsupportedEEError):
        make_covariance_reducer(budget, "Reducer.covariance", {"maxBuckets": 4})


def test_covariance_is_online_sample_covariance_and_returns_owned_array():
    rows = [[vector(row)] for row in ([1, 2], [2, 4], [3, 8])]
    result = matrix(reduce("covariance", rows))
    expected = decimal_reference([[1, 2], [2, 4], [3, 8]])
    np.testing.assert_allclose(result, expected, rtol=1e-15, atol=0)
    np.testing.assert_allclose(result, [[1.0, 3.0], [3.0, 28 / 3]])
    assert result[0, 1] == result[1, 0]


def test_online_covariance_preserves_large_common_offsets_and_small_spread():
    base = 1e16
    values = [base - 4, base - 2, base, base + 2, base + 4]
    rows = [[vector([value])] for value in values]
    result = matrix(reduce("covariance", rows))
    expected = decimal_reference([[value] for value in values])
    np.testing.assert_allclose(result, expected, rtol=1e-15, atol=0)
    assert result[0, 0] == pytest.approx(10.0)


def test_centered_covariance_uses_the_sample_denominator_without_recentering():
    centered_values = [[-1, 1], [0, 0], [1, -1]]
    result = matrix(reduce(
        "centeredCovariance",
        [[vector(row)] for row in centered_values],
    ))
    np.testing.assert_allclose(
        result, decimal_reference(centered_values, centered=True), rtol=0, atol=0,
    )
    np.testing.assert_array_equal(result, [[1, -1], [-1, 1]])

    # The centered reducer trusts its precondition. It computes X^T X/(n-1),
    # rather than subtracting a mean and returning ordinary sample covariance.
    uncentered_values = [[10, 1], [12, -1]]
    uncentered = matrix(reduce(
        "centeredCovariance",
        [[vector(row)] for row in uncentered_values],
    ))
    np.testing.assert_array_equal(uncentered, [[244, -2], [-2, 2]])
    assert not np.array_equal(
        uncentered,
        matrix(reduce("covariance", [[vector(row)] for row in uncentered_values])),
    )


def test_centered_compensated_sum_matches_independent_decimal_reference():
    rows = [[1e16, 1.0], [1.0, 1.0], [-1e16, 1.0]]
    result = matrix(reduce(
        "centeredCovariance", [[vector(row)] for row in rows],
    ))
    expected = decimal_reference(rows, centered=True)
    np.testing.assert_allclose(result, expected, rtol=1e-15, atol=0)
    assert result[0, 1] == 0.5


def test_null_rows_are_skipped_and_empty_or_singleton_samples_are_named_nulls():
    rows = [[None], [vector([1, 2])], [None], [vector([3, 6])]]
    np.testing.assert_array_equal(matrix(reduce("covariance", rows)), [[2, 4], [4, 8]])
    assert reduce("covariance", []) is None
    assert reduce("covariance", [[None], [None]]) is None
    assert reduce("covariance", [[vector([3, 4])]]) is None
    assert reduce("centeredCovariance", [[vector([0, 0])]]) is None


def test_all_non_null_values_are_checked_before_singleton_or_null_reduction():
    bad = StaticArray(np.array([float("inf")]))
    with pytest.raises(UnsupportedEEError, match="finite"):
        reduce("covariance", [[vector([1])], [None], [bad]])
    with pytest.raises(UnsupportedEEError, match=r"exact ±2\^53"):
        reduce("centeredCovariance", [[vector([0])], [vector([2**53 + 1], np.int64)]])


def test_typed_vector_shape_and_numeric_domain_are_strict():
    with pytest.raises(UnsupportedEEError, match="typed StaticArray"):
        reduce("covariance", [[[1.0]]])
    with pytest.raises(UnsupportedEEError, match="rank-1"):
        reduce("covariance", [[StaticArray(np.ones((1, 2)))]] )
    with pytest.raises(UnsupportedEEError, match="width 1..32"):
        reduce("covariance", [[vector([])]])
    with pytest.raises(UnsupportedEEError, match="width 1..32"):
        reduce("covariance", [[vector(range(33))]])
    with pytest.raises(UnsupportedEEError, match="match"):
        reduce("covariance", [[vector([1, 2])], [vector([1])]])
    with pytest.raises(UnsupportedEEError, match="real values"):
        reduce("covariance", [[StaticArray(np.array([1 + 2j]))]])
    with pytest.raises(UnsupportedEEError, match="finite"):
        reduce("covariance", [[vector([float("nan")])]])


def test_cycles_and_dynamic_or_list_values_fail_closed():
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(UnsupportedEEError, match="typed StaticArray"):
        reduce("covariance", [[cyclic]])
    with pytest.raises(UnsupportedEEError, match="one input array"):
        reduce("covariance", [[vector([1]), vector([2])]])


def test_exact_integer_boundary_tiny_values_and_unrepresentable_extremes():
    boundary = [[vector([-(2**53)], np.int64)], [vector([2**53], np.int64)]]
    assert matrix(reduce("covariance", boundary))[0, 0] == float(2**107)

    tiny = matrix(reduce("covariance", [
        [vector([-1e-160])], [vector([1e-160])],
    ]))
    assert tiny[0, 0] == float(Decimal("2e-320"))

    with pytest.raises(UnsupportedEEError, match="finite Float64 range"):
        reduce("covariance", [[vector([-1e308])], [vector([1e308])]])
    with pytest.raises(UnsupportedEEError, match="finite Float64 range"):
        reduce("centeredCovariance", [[vector([1e308])], [vector([0.0])]])


def test_width_thirty_two_and_one_thousand_row_limits_use_shared_budget():
    rows = [[vector([float(index), float(index * 2), float(index * 3)])]
            for index in range(MAX_COVARIANCE_ROWS)]
    result = matrix(reduce("covariance", rows))
    assert result.shape == (3, 3)

    width_32 = matrix(reduce("covariance", [
        [vector(np.zeros(32))], [vector(np.ones(32))],
    ]))
    assert width_32.shape == (32, 32)
    with pytest.raises(UnsupportedEEError, match="at most 1000"):
        reduce("covariance", [[vector([1])] for _ in range(1_001)])


def test_work_is_precharged_and_does_not_exceed_shared_budget():
    budget = Budget(49_999)
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        reduce("covariance", [], budget)
    assert budget.steps == 49_999

    budget = Budget()
    result = reduce("covariance", [[vector([1.0])], [vector([3.0])]], budget)
    assert matrix(result)[0, 0] == 2.0
    assert budget.steps <= 50_000
