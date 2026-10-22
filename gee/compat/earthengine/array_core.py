"""Shared finite Array representation, validators and resource accounting."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math

import numpy as np

from .ir import fail


MAX_ARRAY_CELLS = 10_000
MAX_ARRAY_RANK = 8
MAX_ARRAY_WORK = 50_000


def finite_float_sum(values, divisor=1):
    """Preserve finite cancellation when fsum's intermediate sum overflows.

    Inputs are bounded by MAX_ARRAY_CELLS. Binary64 fractions have power-of-two
    denominators of at most 1074 bits, so this rare fallback remains bounded.
    Divide before conversion to keep a representable mean of an enormous sum.
    """
    numbers = [float(value) for value in values]
    if len(numbers) > MAX_ARRAY_CELLS or not all(math.isfinite(x) for x in numbers):
        fail("Static Array sum requires bounded finite values")
    try:
        result = math.fsum(numbers) / divisor
    except OverflowError:
        exact = sum((Fraction.from_float(x) for x in numbers), Fraction()) / divisor
        try:
            result = float(exact)
        except OverflowError:
            fail("Static Array statistic exceeds the finite Float64 domain")
    if not math.isfinite(result):
        fail("Static Array statistic exceeds the finite Float64 domain")
    return result


@dataclass(frozen=True)
class StaticArray:
    """Typed array value, distinct from the ordinary EE List representation."""

    data: np.ndarray

    def to_value(self):
        return self.data.tolist()


def check_array_values(value, depth=0, count=None):
    count = [0] if count is None else count
    if depth > MAX_ARRAY_RANK:
        fail("Static Array rank exceeds 8")
    if isinstance(value, list):
        if not value:
            fail("Empty Array values require an unsupported explicit PixelType")
        if len(value) > MAX_ARRAY_CELLS:
            fail("Static Array exceeds 10000 cells")
        shapes = [check_array_values(child, depth + 1, count) for child in value]
        if any(shape != shapes[0] for shape in shapes[1:]):
            fail("Array values must form a rectangular numeric array")
        return (len(value), *shapes[0])
    if type(value) not in (int, float):
        fail("Array values must be finite real numbers")
    if isinstance(value, int) and abs(value) > 2**53:
        fail("Static Array integers outside the exact Float64 domain are unsupported")
    if not math.isfinite(value):
        fail("Array values must be finite real numbers")
    count[0] += 1
    if count[0] > MAX_ARRAY_CELLS:
        fail("Static Array exceeds 10000 cells")
    return ()


def wrap_array(value):
    result = np.asarray(value)
    if (result.size > MAX_ARRAY_CELLS or result.ndim > MAX_ARRAY_RANK
            or any(length > MAX_ARRAY_CELLS for length in result.shape)):
        fail("Static Array result exceeds the cell/rank budget")
    if result.dtype.kind not in {"i", "u", "f"} or not np.isfinite(result).all():
        fail("Static Array computation must produce finite real numbers")
    if result.dtype.kind in {"i", "u"} and np.any((result < -(2**53)) | (result > 2**53)):
        fail("Static Array integer result exceeds the exact Float64 domain")
    result = result.copy()
    result.flags.writeable = False
    return StaticArray(result)


def require_array(value):
    if not isinstance(value, StaticArray):
        fail("Expected a static ee.Array, not a List or raster array")
    return value.data


def require_matrix(value):
    array = require_array(value)
    if array.ndim != 2:
        fail("Static matrix operations currently require rank-2 arrays")
    if not array.size:
        fail("Empty matrices are currently unsupported")
    return array


def charge_array(translator, work):
    if work < 0 or work > MAX_ARRAY_WORK or translator.steps + work > MAX_ARRAY_WORK:
        fail("Static Array operation exceeds the compilation work budget")
    translator.steps += work
