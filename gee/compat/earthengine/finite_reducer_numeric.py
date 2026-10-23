"""Bounded numerical kernels for finite scalar Reducer leaves."""
from __future__ import annotations

import math

from .aggregate_statistics_numeric import numeric_dispersion
from .ir import fail


MAX_NUMERIC_REDUCER_VALUES = 1_000
_MAX_WORK = 50_000
_MAX_EXACT_INTEGER = 2**53

NUMERIC_REDUCER_OUTPUTS = {
    "minMax": ("min", "max"),
    "product": ("product",),
    "stdDev": ("stdDev",),
    "variance": ("variance",),
    "sampleVariance": ("variance",),
}

# Per-value accounting covers the input scan, scalar validation and numeric
# kernel. Dispersion reserves the largest path, including its scaled fallback
# and intermediate vectors. The complete charge is made before materializing
# any converted values or outputs.
_WORK_PER_VALUE = {
    "minMax": 4,
    "product": 6,
    "stdDev": 20,
    "variance": 20,
    "sampleVariance": 20,
}


def _charge(translator, work: int) -> None:
    if work < 0 or work > _MAX_WORK or translator.steps + work > _MAX_WORK:
        fail("Numeric reducer exceeds the shared 50000-step compilation work budget")
    translator.steps += work


def _number(value) -> float:
    if type(value) is int:
        if value.bit_length() > 54 or value < -_MAX_EXACT_INTEGER or value > _MAX_EXACT_INTEGER:
            fail("Numeric reducer inputs exceed the finite exact Float64 domain")
        return float(value)
    if type(value) is not float:
        fail("Numeric reducer inputs must be finite numbers or null")
    if not math.isfinite(value):
        fail("Numeric reducer inputs exceed the finite exact Float64 domain")
    return value


def _checked_numbers(values) -> list[float]:
    numbers = []
    for value in values:
        if value is not None:
            numbers.append(_number(value))
    return numbers


def _product(numbers: list[float]) -> float:
    if not numbers:
        return 1.0

    negative = False
    has_zero = False
    for value in numbers:
        negative ^= math.copysign(1.0, value) < 0
        if value == 0.0:
            has_zero = True
    if has_zero:
        return math.copysign(0.0, -1.0 if negative else 1.0)

    # Keep the running significand normalized and accumulate binary exponents
    # separately. Direct multiplication can overflow or underflow early even
    # when later factors bring the final product back into range.
    significand = 1.0
    exponent = 0
    for value in numbers:
        factor, factor_exponent = math.frexp(abs(value))
        significand *= factor
        significand, adjustment = math.frexp(significand)
        exponent += factor_exponent + adjustment
    try:
        result = math.ldexp(significand, exponent)
    except OverflowError:
        fail("Numeric reducer product exceeds the finite Float64 range")
    if not math.isfinite(result):
        fail("Numeric reducer product exceeds the finite Float64 range")
    return -result if negative else result


def _dispersion(name: str, numbers: list[float]):
    if name == "stdDev":
        result = numeric_dispersion(
            numbers, sample=False, standard_deviation=True,
        )
    elif name == "variance":
        result = numeric_dispersion(
            numbers, sample=False, standard_deviation=False,
        )
    else:
        result = numeric_dispersion(
            numbers, sample=True, standard_deviation=False,
        )
    if result is not None and not math.isfinite(result):
        fail(f"Numeric reducer {name} exceeds the finite Float64 range")
    return result


def reduce_numeric_leaf(translator, name, values) -> list[tuple[str, float | None]]:
    """Evaluate one supported scalar reducer on at most 1000 finite List values.

    Nulls are skipped. Non-null inputs must be finite Python numeric scalars;
    booleans and integers outside the exact Float64 domain are rejected.
    """
    if name not in NUMERIC_REDUCER_OUTPUTS:
        fail(f"Unsupported finite numeric reducer: {name}")
    if type(values) is not list or len(values) > MAX_NUMERIC_REDUCER_VALUES:
        fail("Numeric reducer requires at most 1000 inline values")

    output_names = NUMERIC_REDUCER_OUTPUTS[name]
    output_work = sum(1 + len(output_name) for output_name in output_names)
    _charge(translator, 1 + _WORK_PER_VALUE[name] * len(values) + output_work)

    numbers = _checked_numbers(values)
    if name == "minMax":
        result = (min(numbers), max(numbers)) if numbers else (None, None)
    elif name == "product":
        result = (_product(numbers),)
    else:
        result = (_dispersion(name, numbers),)
    return list(zip(output_names, result))
