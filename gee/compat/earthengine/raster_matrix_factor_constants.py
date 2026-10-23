"""Source-free finite folds for fixed Cholesky and LU raster matrices."""
from __future__ import annotations

import math
import struct
from decimal import Decimal, Inexact, localcontext
from fractions import Fraction

from .array_core import charge_array
from .ir import fail


def _cast_output(value, dtype, name):
    if not math.isfinite(value):
        fail(f"{name} constant factors must be finite Float64 values")
    if dtype == "to_float":
        try:
            value = struct.unpack("!f", struct.pack("!f", value))[0]
        except (OverflowError, struct.error):
            fail(f"{name} constant factors overflow Float32")
        if not math.isfinite(value):
            fail(f"{name} constant factors overflow Float32")
    return float(value)


def _cholesky(matrix, name):
    n = len(matrix)
    if any(matrix[row][column] != matrix[column][row]
           for row in range(n) for column in range(row)):
        fail(f"{name} requires an exactly symmetric constant matrix")

    lower = [[0.0] * n for _ in range(n)]
    for row in range(n):
        for column in range(row + 1):
            products = (Fraction.from_float(lower[row][k])
                        * Fraction.from_float(lower[column][k])
                        for k in range(column))
            residual = Fraction.from_float(matrix[row][column]) - sum(
                products, Fraction(),
            )
            if row == column:
                if residual <= 0:
                    fail(f"{name} requires positive computed Cholesky pivots")
                exact = _exact_fraction_decimal(residual, name)
                with localcontext() as context:
                    context.prec = 50
                    lower[row][column] = float(exact.sqrt())
            else:
                pivot = lower[column][column]
                if pivot == 0.0:
                    fail(f"{name} requires positive computed Cholesky pivots")
                lower[row][column] = _cholesky_quotient_to_float(
                    residual / Fraction.from_float(pivot), name,
                )
            if not math.isfinite(lower[row][column]):
                fail(f"{name} constant factors must be finite")
    return (lower,)


def _lu(matrix, name):
    n = len(matrix)
    upper = [[Fraction.from_float(value) for value in row] for row in matrix]
    lower = [[Fraction(int(row == column)) for column in range(n)]
             for row in range(n)]
    permutation = [[Fraction(int(row == column)) for column in range(n)]
                   for row in range(n)]

    for column in range(n):
        pivot_row = column
        largest = abs(upper[column][column])
        for row in range(column + 1, n):
            candidate = abs(upper[row][column])
            if candidate > largest:
                largest = candidate
                pivot_row = row
        if upper[pivot_row][column] == 0:
            fail(f"{name} encountered an exact zero LU pivot")
        if pivot_row != column:
            upper[column], upper[pivot_row] = upper[pivot_row], upper[column]
            permutation[column], permutation[pivot_row] = (
                permutation[pivot_row], permutation[column],
            )
            for previous in range(column):
                lower[column][previous], lower[pivot_row][previous] = (
                    lower[pivot_row][previous], lower[column][previous],
                )

        pivot = upper[column][column]
        for row in range(column + 1, n):
            multiplier = upper[row][column] / pivot
            lower[row][column] = multiplier
            upper[row][column] = Fraction()
            for target in range(column + 1, n):
                upper[row][target] -= multiplier * upper[column][target]

    return tuple(
        [[_fraction_to_float_once(value, name) for value in row] for row in factor]
        for factor in (lower, upper, permutation)
    )


def _exact_fraction_decimal(value, name):
    """Convert a dyadic residual to its exact terminating decimal expansion."""
    precision = len(str(abs(value.numerator))) + value.denominator.bit_length() + 2
    try:
        with localcontext() as context:
            context.prec = precision
            context.traps[Inexact] = True
            return Decimal(value.numerator) / Decimal(value.denominator)
    except Inexact:
        fail(f"{name} constant Cholesky residual did not convert exactly")


def _cholesky_quotient_to_float(value, name):
    """Apply the native 50-digit divide, then the binary64 output rounding."""
    try:
        with localcontext() as context:
            context.prec = 50
            return float(Decimal(value.numerator) / Decimal(value.denominator))
    except (OverflowError, ValueError, ZeroDivisionError):
        fail(f"{name} constant factors must be finite")


def _fraction_to_float_once(value, name):
    """Round an exact LU rational directly once at the binary64 boundary."""
    try:
        return float(value)
    except (OverflowError, ValueError, ZeroDivisionError):
        fail(f"{name} constant factors must be finite")


def fold_constant_factors(translator, name, op, rows, cols, values, dtype):
    """Fold valid finite literals without binding them to a fabricated grid."""
    if (type(values) is not tuple or rows != cols
            or len(values) != rows * cols
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   for value in values)):
        fail(f"{name} source-free factor input must be a finite square matrix")
    # Input floats are exact binary64 values. Scale the dense rational work by
    # their bounded binary representation size before building Fraction rows.
    output_count = rows * cols * (3 if op == "lu" else 1)
    ratio_bits = max(
        abs(float(value).as_integer_ratio()[0]).bit_length()
        + float(value).as_integer_ratio()[1].bit_length()
        for value in values
    )
    rational_scale = max(1, (ratio_bits + 105) // 106)
    work = 8 * rows * rows * rows + 16 * rows * rows + output_count
    charge_array(translator, work * rational_scale)
    matrix = [[float(values[row * cols + column]) for column in range(cols)]
              for row in range(rows)]
    factors = _cholesky(matrix, name) if op == "cholesky" else _lu(matrix, name)
    return tuple(
        tuple(_cast_output(value, dtype, name)
              for row in factor for value in row)
        for factor in factors
    )
