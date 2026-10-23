"""Independent Fraction/Decimal references for dynamic matrix factors.

The oracle works at the original binary64 scale. It does not call NumPy's
factorization routines or import any production implementation.
"""
from __future__ import annotations

from decimal import Context, Decimal, Inexact, ROUND_HALF_EVEN
from fractions import Fraction
import math

import numpy as np


_DECIMAL = Context(prec=50, rounding=ROUND_HALF_EVEN)


def _fraction(value: float) -> Fraction:
    return Fraction.from_float(float(value))


def _exact_decimal(value: Fraction) -> Decimal:
    """Convert a terminating exact residual before applying MC50 sqrt."""
    context = Context(
        prec=len(str(abs(value.numerator))) + value.denominator.bit_length() + 2,
        rounding=ROUND_HALF_EVEN,
    )
    context.traps[Inexact] = True
    return context.divide(Decimal(value.numerator), Decimal(value.denominator))


def _rounded_divide(numerator: Fraction, denominator: Fraction) -> float:
    quotient = numerator / denominator
    return float(_DECIMAL.divide(Decimal(quotient.numerator),
                                  Decimal(quotient.denominator)))


def _rounded_sqrt(value: Fraction) -> float:
    return float(_DECIMAL.sqrt(_exact_decimal(value)))


def _rounded_binary64(value: Fraction) -> float:
    """Round an exact rational directly to binary64, ties to even."""
    return float(value)


def _checked_matrix(matrix: np.ndarray, op: str) -> np.ndarray:
    if op not in {"cholesky", "lu"}:
        raise ValueError("matrix factor reference supports cholesky and lu")
    try:
        array = np.asarray(matrix, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("matrix factor input must be binary64 values") from error
    if (array.ndim != 2 or array.shape[0] == 0
            or array.shape[0] != array.shape[1]):
        raise ValueError("matrix factor input must be a nonempty square matrix")
    size = array.shape[0]
    if size > (8 if op == "cholesky" else 4):
        raise ValueError("matrix factor input exceeds its bounded output shape")
    if not np.isfinite(array).all():
        raise ValueError("matrix factor input must be finite binary64")
    return array.copy()


def _cholesky(matrix: np.ndarray) -> np.ndarray | None:
    size = matrix.shape[0]
    lower = np.zeros((size, size), dtype=np.float64)
    for row in range(size):
        for column in range(row + 1):
            residual = _fraction(matrix[row, column]) - sum((
                _fraction(lower[row, inner]) * _fraction(lower[column, inner])
                for inner in range(column)
            ), Fraction())
            if row == column:
                if residual <= 0:
                    return None
                try:
                    value = _rounded_sqrt(residual)
                except (ArithmeticError, OverflowError, ValueError):
                    return None
                if not math.isfinite(value) or value <= 0.0:
                    return None
            else:
                pivot = _fraction(lower[column, column])
                if pivot <= 0:
                    return None
                try:
                    value = _rounded_divide(residual, pivot)
                except (ArithmeticError, OverflowError, ValueError, ZeroDivisionError):
                    return None
                if not math.isfinite(value):
                    return None
            lower[row, column] = value
    return lower


def _lu(matrix: np.ndarray) -> np.ndarray | None:
    size = matrix.shape[0]
    upper = [[_fraction(matrix[row, column]) for column in range(size)]
             for row in range(size)]
    lower = [[Fraction(int(row == column)) for column in range(size)]
             for row in range(size)]
    permutation = [[Fraction(int(row == column)) for column in range(size)]
                   for row in range(size)]

    for column in range(size):
        # The input binary64 values become exact rationals before elimination.
        # max() keeps the first row on ties, matching partial pivoting.
        pivot_row = max(range(column, size), key=lambda row: abs(upper[row][column]))
        if upper[pivot_row][column] == 0:
            return None
        if pivot_row != column:
            upper[column], upper[pivot_row] = upper[pivot_row], upper[column]
            permutation[column], permutation[pivot_row] = (
                permutation[pivot_row], permutation[column]
            )
            lower[column][:column], lower[pivot_row][:column] = (
                lower[pivot_row][:column], lower[column][:column]
            )

        pivot = upper[column][column]
        for row in range(column + 1, size):
            multiplier = upper[row][column] / pivot
            lower[row][column] = multiplier
            upper[row][column] = Fraction()
            for target in range(column + 1, size):
                upper[row][target] -= multiplier * upper[column][target]

    factors = []
    for exact_matrix in (lower, upper, permutation):
        rounded = np.empty((size, size), dtype=np.float64)
        try:
            for row in range(size):
                for column in range(size):
                    rounded[row, column] = _rounded_binary64(exact_matrix[row][column])
        except (OverflowError, ValueError):
            return None
        if not np.isfinite(rounded).all():
            return None
        factors.append(rounded)
    return np.stack(factors, axis=0)


def factor_matrix_result(op: str, matrix: np.ndarray) -> np.ndarray | None:
    """Return one factor result, or ``None`` for whole-matrix NoData.

    ``op`` is ``cholesky`` or ``lu``. Cholesky returns its lower factor; LU
    returns ``(3, n, n)`` factors in ``L, U, P`` order. Inputs are exact finite
    binary64 values. Residuals are exact Fractions of those values and of the
    actual rounded binary64 Cholesky factors; Cholesky square roots and
    divisions use a 50-digit Decimal context. LU keeps the exact rational
    values of its binary64 inputs through pivoting and elimination, rounding
    each returned factor only once at the end.
    """
    source = _checked_matrix(matrix, op)
    if op == "cholesky":
        if not np.array_equal(source, source.T):
            return None
        return _cholesky(source)
    return _lu(source)
