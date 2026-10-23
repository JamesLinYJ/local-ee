"""Bounded finite special functions for static Earth Engine Numbers/Arrays."""
from __future__ import annotations

import math

import numpy as np

from .array_core import MAX_ARRAY_CELLS, MAX_ARRAY_RANK, MAX_ARRAY_WORK, StaticArray
from .ir import UnsupportedEEError, fail


_NUMBER_NAMES = frozenset({
    "Number.digamma", "Number.trigamma", "Number.erfInv", "Number.erfcInv",
})
_ARRAY_NAMES = frozenset({
    "Array.digamma", "Array.trigamma", "Array.erfInv", "Array.erfcInv",
})
STATIC_SPECIAL_MATH_FUNCTIONS = _NUMBER_NAMES | _ARRAY_NAMES

_EULER = 0.5772156649015328606
_INVERSE_ITERATIONS = 64
_TAIL_ITERATIONS = 8
_TAIL_TERMS = 12
_WORK_COST = {
    "digamma": 32,
    "trigamma": 32,
    "erfInv": _INVERSE_ITERATIONS + _TAIL_ITERATIONS * _TAIL_TERMS + 2,
    "erfcInv": _INVERSE_ITERATIONS + _TAIL_ITERATIONS * _TAIL_TERMS + 2,
}


def _charge(translator, count, operation):
    work = count * _WORK_COST[operation] + 1
    if work > MAX_ARRAY_WORK or translator.steps + work > MAX_ARRAY_WORK:
        fail(f"{operation} exceeds the 50000-step compilation work budget")
    translator.steps += work


def _positive_digamma(value):
    result = 0.0
    while value < 8.0:
        result -= 1.0 / value
        value += 1.0
    inverse = 1.0 / value
    inverse2 = inverse * inverse
    tail = -inverse2 * (
        1.0 / 12.0 - inverse2 * (
            1.0 / 120.0 - inverse2 * (
                1.0 / 252.0 - inverse2 * (
                    1.0 / 240.0 - inverse2 * (
                        1.0 / 132.0 - inverse2 * 691.0 / 32760.0
                    )
                )
            )
        )
    )
    return result + math.log(value) - 0.5 * inverse + tail


def _positive_trigamma(value):
    result = 0.0
    while value < 8.0:
        inverse = 1.0 / value
        result += inverse * inverse
        value += 1.0
    inverse = 1.0 / value
    inverse2 = inverse * inverse
    return result + (
        inverse + 0.5 * inverse2 + inverse * inverse2 / 6.0
        - inverse * inverse2**2 / 30.0 + inverse * inverse2**3 / 42.0
        - inverse * inverse2**4 / 30.0 + 5.0 * inverse * inverse2**5 / 66.0
        - 691.0 * inverse * inverse2**6 / 2730.0
        + 7.0 * inverse * inverse2**7 / 6.0
        - 3617.0 * inverse * inverse2**8 / 510.0
    )


def _digamma(value):
    if value > 0.0:
        return _positive_digamma(value)
    if value.is_integer():
        fail("digamma is undefined at non-positive integer poles")
    fraction = math.remainder(value, 1.0)
    angle = math.pi * fraction
    sine = math.sin(angle)
    if sine == 0.0:
        fail("digamma exceeds the finite Float64 domain near a pole")
    return _positive_digamma(1.0 - value) - math.pi * math.cos(angle) / sine


def _trigamma(value):
    if value > 0.0:
        return _positive_trigamma(value)
    if value.is_integer():
        fail("trigamma is undefined at non-positive integer poles")
    fraction = math.remainder(value, 1.0)
    sine = math.sin(math.pi * fraction)
    if sine == 0.0:
        fail("trigamma exceeds the finite Float64 domain near a pole")
    ratio = math.pi / sine
    return ratio * ratio - _positive_trigamma(1.0 - value)


def _erf_inverse(value):
    if not -1.0 < value < 1.0:
        fail("erfInv requires input strictly inside (-1, 1)")
    if value == 0.0:
        return value
    magnitude = abs(value)
    if magnitude <= 1e-4:
        square = value * value
        return value * (
            math.sqrt(math.pi) / 2.0
            + square * (
                math.pi**1.5 / 24.0
                + square * 7.0 * math.pi**2.5 / 960.0
            )
        )
    if magnitude > 0.5:
        # Sterbenz subtraction is exact here; direct erfc inversion keeps the
        # upper erf tail from rounding to one during function evaluation.
        return math.copysign(_erfc_inverse(1.0 - magnitude), value)
    low, high = 0.0, 2.0 * magnitude
    target = magnitude
    for _ in range(_INVERSE_ITERATIONS):
        middle = low + (high - low) * 0.5
        if middle == low or middle == high:
            break
        if math.erf(middle) < target:
            low = middle
        else:
            high = middle
    return math.copysign(low + (high - low) * 0.5, value)


def _log_erfc_tail(value):
    inverse2 = 1.0 / (value * value)
    term = 1.0
    series = 1.0
    derivative_sum = 0.0
    for order in range(1, _TAIL_TERMS + 1):
        term *= -(2.0 * order - 1.0) * inverse2 / 2.0
        series += term
        derivative_sum -= 2.0 * order * term / value
    log_erfc = (
        -value * value - math.log(value) - 0.5 * math.log(math.pi)
        + math.log(series)
    )
    derivative = -2.0 * value - 1.0 / value + derivative_sum / series
    return log_erfc, derivative


def _positive_erfc_inverse(value):
    if value < math.erfc(8.0):
        target = math.log(value)
        result = math.sqrt(-target)
        for _ in range(_TAIL_ITERATIONS):
            log_value, derivative = _log_erfc_tail(result)
            updated = result - (log_value - target) / derivative
            if updated == result:
                break
            result = updated
        return result

    low, high = 0.0, 8.0
    for _ in range(_INVERSE_ITERATIONS):
        middle = low + (high - low) * 0.5
        if middle == low or middle == high:
            break
        if math.erfc(middle) > value:
            low = middle
        else:
            high = middle
    return low + (high - low) * 0.5


def _erfc_inverse(value):
    if not 0.0 < value < 2.0:
        fail("erfcInv requires input strictly inside (0, 2)")
    if value == 1.0:
        return 0.0
    if 0.5 <= value <= 1.5:
        # Sterbenz subtraction is exact near one, while direct erfc comparisons
        # quantize tiny roots onto a broad plateau. Here erfInv stays on its
        # well-conditioned central branch, so this cannot recurse via erfcInv.
        return _erf_inverse(1.0 - value)
    negative = value > 1.0
    tail = 2.0 - value if negative else value
    result = _positive_erfc_inverse(tail)
    return -result if negative else result


def _apply(operation, value):
    try:
        result = {
            "digamma": _digamma,
            "trigamma": _trigamma,
            "erfInv": _erf_inverse,
            "erfcInv": _erfc_inverse,
        }[operation](value)
    except UnsupportedEEError:
        raise
    except (ArithmeticError, ValueError):
        fail(f"{operation} requires a finite result in its real domain")
    if not math.isfinite(result):
        fail(f"{operation} must produce a finite Float64 result")
    return result


def _number(value, operation):
    if (type(value) not in (int, float)
            or type(value) is int and abs(value) > 2**53
            or type(value) is float and not math.isfinite(value)):
        fail(f"{operation} requires a finite static Number with exact Float64 integers")
    return float(value)


def _array(value, operation):
    if type(value) is not StaticArray or not isinstance(value.data, np.ndarray):
        fail(f"{operation} requires a finite static ee.Array")
    array = value.data
    if (array.ndim > MAX_ARRAY_RANK or array.size > MAX_ARRAY_CELLS
            or any(length > MAX_ARRAY_CELLS for length in array.shape)):
        fail(f"{operation} input exceeds the static Array rank or cell limit")
    if array.dtype.kind not in {"i", "u", "f"}:
        fail(f"{operation} requires finite real Array values")
    return array


def _validate_array(array, operation):
    if array.dtype.kind in {"i", "u"}:
        for item in array.flat:
            if abs(int(item)) > 2**53:
                fail(f"{operation} Array integers must fit the exact Float64 domain")
    else:
        for item in array.flat:
            if not math.isfinite(float(item)):
                fail(f"{operation} requires finite real Array values")


def invoke_static_special_math(translator, name, arguments):
    """Evaluate a pinned Number/Array special function on finite static values.

    Digamma and trigamma use bounded recurrence plus asymptotic expansion and
    reflection. Inverse error functions use bounded direct-function bisection.
    The Float64 result and domain policy are local; Google numerical parity is
    not implied.
    """
    if name not in STATIC_SPECIAL_MATH_FUNCTIONS:
        fail(f"Unsupported static special function: {name}")
    translator.allowed(arguments, {"input"})
    if "input" not in arguments:
        fail(f"{name} requires input")
    operation = name.split(".", 1)[1]

    if name in _NUMBER_NAMES:
        value = _number(arguments["input"], name)
        _charge(translator, 1, operation)
        return _apply(operation, value)

    array = _array(arguments["input"], name)
    _charge(translator, int(array.size), operation)
    _validate_array(array, name)
    result = np.empty(array.shape, dtype=np.float64)
    for index, item in enumerate(array.flat):
        result.flat[index] = _apply(operation, float(item))
    result.flags.writeable = False
    return StaticArray(result)
