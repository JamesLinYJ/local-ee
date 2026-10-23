"""Bounded shape-exact elementwise Array selection, logic and math."""
from __future__ import annotations

import math

import numpy as np

from .array_core import charge_array, require_array, wrap_array
from .ir import fail


ARRAY_BINARY_FUNCTIONS = frozenset({
    "Array.max", "Array.min", "Array.first", "Array.firstNonZero",
    "Array.first_nonzero", "Array.mod", "Array.pow", "Array.and",
    "Array.or", "Array.eq", "Array.neq", "Array.lt", "Array.lte",
    "Array.gt", "Array.gte",
})

_COMPARISONS = {
    "Array.eq": np.equal,
    "Array.neq": np.not_equal,
    "Array.lt": np.less,
    "Array.lte": np.less_equal,
    "Array.gt": np.greater,
    "Array.gte": np.greater_equal,
}
_EXACT_INTEGER_LIMIT = 2**53


def _power_exact_integer(base, exponent):
    """Compute an integer power without building a value outside Float64 exactness."""
    if exponent == 0:
        return 1
    if base == 0:
        return 0
    if base == 1:
        return 1
    if base == -1:
        return -1 if exponent & 1 else 1

    result = 1
    factor = base
    remaining = exponent
    while remaining:
        if remaining & 1:
            result *= factor
            if abs(result) > _EXACT_INTEGER_LIMIT:
                fail("Array.pow integer result exceeds the exact Float64 domain")
        remaining >>= 1
        if remaining:
            factor *= factor
            if abs(factor) > _EXACT_INTEGER_LIMIT:
                # A remaining set bit will multiply by this oversized factor.
                fail("Array.pow integer result exceeds the exact Float64 domain")
    return result


def _integer_power(left, right):
    results = []
    has_fraction = False
    for base_value, exponent_value in zip(left.flat, right.flat):
        base, exponent = int(base_value), int(exponent_value)
        if exponent >= 0:
            results.append(_power_exact_integer(base, exponent))
            continue
        if base == 0:
            fail("Array.pow zero cannot have a negative exponent")
        result = float(base ** exponent)
        if not math.isfinite(result):
            fail("Array.pow must produce finite real values")
        has_fraction = True
        results.append(result)
    dtype = np.float64 if has_fraction else np.int64
    return np.asarray(results, dtype=dtype).reshape(left.shape)


def invoke_binary(translator, name, arguments):
    """Evaluate one pinned binary algorithm; singleton expansion is never used."""
    if name not in ARRAY_BINARY_FUNCTIONS:
        fail(f"Unsupported static Array binary operation: {name}")
    translator.allowed(arguments, {"left", "right"})
    missing = {"left", "right"} - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")
    left, right = (require_array(arguments[key]) for key in ("left", "right"))
    if left.shape != right.shape:
        fail("Static Array binary operations require the same shape; broadcasting is unsupported")

    if name == "Array.pow" and left.dtype.kind in {"i", "u"} and right.dtype.kind in {"i", "u"}:
        # Integer exponents need at most 54 exponentiation-by-squaring rounds.
        charge_array(translator, int(left.size) * 109 + 1)
        return wrap_array(_integer_power(left, right))

    multiplier = 16 if name == "Array.pow" else 8 if name == "Array.mod" else 4
    charge_array(translator, int(left.size) * multiplier + 1)

    if name == "Array.max":
        result = np.maximum(left, right)
    elif name == "Array.min":
        result = np.minimum(left, right)
    elif name == "Array.first":
        result = left
    elif name in {"Array.firstNonZero", "Array.first_nonzero"}:
        result = np.where(left != 0, left, right)
    elif name in {"Array.and", "Array.or"}:
        left_truth, right_truth = left != 0, right != 0
        condition = left_truth & right_truth if name == "Array.and" else left_truth | right_truth
        result = condition.astype(np.int64)
    elif name in _COMPARISONS:
        if left.dtype.kind in {"i", "u"} and right.dtype.kind in {"i", "u"}:
            first, second = left, right
        else:
            first, second = left.astype(np.float64, copy=False), right.astype(np.float64, copy=False)
        result = _COMPARISONS[name](first, second).astype(np.int64)
    elif name == "Array.mod":
        if np.any(right == 0):
            fail("Array.mod requires nonzero divisors")
        if left.dtype.kind in {"i", "u"} and right.dtype.kind in {"i", "u"}:
            result = np.fmod(left, right)
        else:
            # EE's examples use dividend-sign remainder, unlike Python %.
            first, second = left.astype(np.float64, copy=False), right.astype(np.float64, copy=False)
            with np.errstate(invalid="ignore", divide="ignore"):
                result = np.fmod(first, second)
    else:  # Array.pow with at least one Float64 input.
        first, second = left.astype(np.float64, copy=False), right.astype(np.float64, copy=False)
        if np.any((first == 0) & (second < 0)):
            fail("Array.pow zero cannot have a negative exponent")
        if np.any((first < 0) & (second != np.floor(second))):
            fail("Array.pow negative bases require integer exponents")
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            result = np.power(first, second)
    return wrap_array(result)
