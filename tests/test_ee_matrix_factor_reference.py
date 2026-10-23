"""Direct controls for the independent binary64 factorization oracle."""
from fractions import Fraction

import numpy as np
import pytest

from ee_matrix_factor_reference import (
    _exact_decimal, _rounded_binary64, factor_matrix_result,
)


def test_exact_dyadic_decimal_conversion_keeps_residual_below_mc50_precision():
    value = Fraction(1) + Fraction(1, 2**200)
    decimal_value = _exact_decimal(value)
    assert Fraction(decimal_value) == value
    assert decimal_value > 1


def test_lu_rational_conversion_handles_binary64_midpoint_and_adjacent_values():
    lower = Fraction.from_float(1.0)
    upper_float = np.nextafter(1.0, 2.0)
    upper = Fraction.from_float(float(upper_float))
    midpoint = (lower + upper) / 2
    epsilon = Fraction(1, 2**200)

    # 1.0 has an even significand, so the exact midpoint rounds down; moving
    # either side by an exact amount far below Decimal MC50 tests the boundary.
    assert _rounded_binary64(midpoint - epsilon) == 1.0
    assert _rounded_binary64(midpoint) == 1.0
    assert _rounded_binary64(midpoint + epsilon) == upper_float


def test_cholesky_reference_has_exact_lower_factor_and_original_scale_tiny_pivot():
    matrix = np.asarray([
        [4, 12, -16],
        [12, 37, -43],
        [-16, -43, 98],
    ], dtype=np.float64)
    np.testing.assert_array_equal(factor_matrix_result("cholesky", matrix), [
        [2, 0, 0],
        [6, 1, 0],
        [-8, 5, 3],
    ])

    extreme = np.diag(np.asarray([1e300, 1e-300], dtype=np.float64))
    lower = factor_matrix_result("cholesky", extreme)
    assert lower is not None
    assert lower[0, 0] == pytest.approx(1e150, rel=2e-16)
    assert lower[1, 1] == pytest.approx(1e-150, rel=2e-16)
    assert lower[1, 0] == 0.0
    np.testing.assert_allclose(lower @ lower.T, extreme, rtol=3e-16, atol=0.0)


@pytest.mark.parametrize("matrix", [
    [[1, 1], [1 + np.spacing(1.0), 2]],
    [[1, 2], [2, 4]],
    [[1, 0, 0], [0, 1, 0], [0, 0, 0]],
    [[1, 2], [2, 1]],
])
def test_cholesky_reference_rejects_asymmetry_and_nonpositive_exact_pivots(matrix):
    assert factor_matrix_result("cholesky", np.asarray(matrix, dtype=np.float64)) is None


def test_lu_reference_swaps_prior_lower_columns_and_returns_l_u_p():
    matrix = np.asarray([
        [2, 0, 1],
        [4, 5, 2],
        [1, 7, 8],
    ], dtype=np.float64)
    factors = factor_matrix_result("lu", matrix)
    assert factors is not None and factors.shape == (3, 3, 3)
    lower, upper, permutation = factors
    np.testing.assert_array_equal(np.diag(lower), np.ones(3))
    np.testing.assert_array_equal(np.triu(lower, 1), np.zeros((3, 3)))
    np.testing.assert_array_equal(np.tril(upper, -1), np.zeros((3, 3)))
    np.testing.assert_array_equal(permutation, [
        [0, 1, 0],
        [0, 0, 1],
        [1, 0, 0],
    ])
    assert lower[1, 0] == 0.25  # The prior L column follows the second pivot swap.
    assert lower[2, 0] == 0.5
    np.testing.assert_allclose(permutation @ matrix, lower @ upper, rtol=0, atol=2e-16)


def test_lu_reference_uses_first_equal_maximum_and_rejects_zero_pivot_or_overflow():
    tied = np.asarray([[2.0, 1.0], [2.0, 3.0]], dtype=np.float64)
    factors = factor_matrix_result("lu", tied)
    assert factors is not None
    np.testing.assert_array_equal(factors[2], np.eye(2))
    np.testing.assert_allclose(factors[2] @ tied, factors[0] @ factors[1], atol=0)

    assert factor_matrix_result("lu", np.asarray([[1, 2], [2, 4]], dtype=np.float64)) is None
    overflow = np.asarray([[1.0, 1.7e308], [0.5, -1.7e308]], dtype=np.float64)
    assert factor_matrix_result("lu", overflow) is None


def test_lu_exact_elimination_detects_fractional_multiplier_singularity():
    singular = np.asarray([[3.0, 3.0], [1.0, 1.0]], dtype=np.float64)
    assert factor_matrix_result("lu", singular) is None

    just_nonsingular = np.asarray([
        [3.0, 3.0], [1.0, np.nextafter(1.0, 2.0)],
    ], dtype=np.float64)
    factors = factor_matrix_result("lu", just_nonsingular)
    assert factors is not None
    assert factors[1, 1, 1] == np.spacing(1.0)


@pytest.mark.parametrize("op", ["cholesky", "lu"])
def test_factor_reference_rejects_invalid_shapes_nonfinite_values_and_unknown_ops(op):
    with pytest.raises(ValueError, match="square"):
        factor_matrix_result(op, np.ones((2, 3), dtype=np.float64))
    with pytest.raises(ValueError, match="finite"):
        factor_matrix_result(op, np.asarray([[np.inf]], dtype=np.float64))
    with pytest.raises(ValueError, match="supports"):
        factor_matrix_result("qr", np.eye(1, dtype=np.float64))
