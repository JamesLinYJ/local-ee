"""Precharged exact rank of a bounded source-free binary64 matrix."""
from __future__ import annotations

import math

from .array_core import charge_array
from .ir import fail


def exact_constant_rank(translator, values, rows, cols):
    """Distinguish true null directions without a floating rank tolerance.

    Multiply all dyadic values by one common power of two. Integer minors
    bound stored and temporary integers in fraction-free Bareiss elimination;
    charge limb-squared arithmetic before constructing its integer matrix.
    This estimate does not claim a strict Python BigInteger CPU-time bound.
    """
    count = rows * cols
    charge_array(translator, 2 * count + 8)
    ratios = [float(value).as_integer_ratio() for value in values]
    common_power = max(denominator.bit_length() - 1 for _numerator, denominator in ratios)
    width = max((abs(numerator).bit_length() + common_power
                 - (denominator.bit_length() - 1)
                 for numerator, denominator in ratios if numerator), default=1)
    inner = min(rows, cols)
    minor_bits = inner * width + math.factorial(inner).bit_length()
    prior_bits = (inner - 1) * width + math.factorial(inner - 1).bit_length()
    checked_bits = max(minor_bits, 2 * prior_bits + 1, width)
    if checked_bits > 32_768:
        fail("Source-free SVD exact rank exceeds the rational bit bound")
    limbs = (checked_bits + 63) // 64
    updates = sum((rows - k - 1) * (cols - k - 1) for k in range(inner - 1))
    charge_array(translator, 8 * updates * limbs * limbs + count * (inner + limbs))
    matrix = [[numerator << (common_power - (denominator.bit_length() - 1))
               for numerator, denominator in ratios[row * cols:(row + 1) * cols]]
              for row in range(rows)]
    rank, previous = 0, 1
    while rank < inner:
        pivot = next(((row, col) for row in range(rank, rows)
                      for col in range(rank, cols) if matrix[row][col]), None)
        if pivot is None:
            break
        pivot_row, pivot_col = pivot
        matrix[rank], matrix[pivot_row] = matrix[pivot_row], matrix[rank]
        for row in matrix:
            row[rank], row[pivot_col] = row[pivot_col], row[rank]
        divisor = matrix[rank][rank]
        for row in range(rank + 1, rows):
            for col in range(rank + 1, cols):
                numerator = divisor * matrix[row][col] - matrix[row][rank] * matrix[rank][col]
                quotient, remainder = divmod(numerator, previous)
                if remainder:
                    fail("Source-free SVD exact-rank division was not integral")
                matrix[row][col] = quotient
            matrix[row][rank] = 0
        previous = divisor
        rank += 1
    return rank
