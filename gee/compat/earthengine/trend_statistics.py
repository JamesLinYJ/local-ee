"""Scaled arithmetic and Sen slope for finite two-column observations."""
from __future__ import annotations

import math

from .ir import fail


Scaled = tuple[float, int]


def _from_float(value: float) -> Scaled:
    return (0.0, 0) if value == 0.0 else math.frexp(value)


def _normalize(mantissa: float, exponent: int) -> Scaled:
    if mantissa == 0.0:
        return (0.0, 0)
    fraction, adjustment = math.frexp(mantissa)
    return fraction, exponent + adjustment


def _add(left: Scaled, right: Scaled) -> Scaled:
    if left[0] == 0.0:
        return right
    if right[0] == 0.0:
        return left
    exponent = max(left[1], right[1])
    total = math.ldexp(left[0], left[1] - exponent)
    total += math.ldexp(right[0], right[1] - exponent)
    return _normalize(total, exponent)


def _subtract(left: Scaled, right: Scaled) -> Scaled:
    return _add(left, (-right[0], right[1]))


def _multiply(left: Scaled, right: Scaled) -> Scaled:
    return _normalize(left[0] * right[0], left[1] + right[1])


def _divide(left: Scaled, right: Scaled) -> Scaled:
    if right[0] == 0.0:
        fail("Reducer.sensSlope encountered an undefined x difference")
    return _normalize(left[0] / right[0], left[1] - right[1])


def _key(value: Scaled):
    mantissa, exponent = value
    if mantissa < 0.0:
        return (0, -exponent, -abs(mantissa))
    if mantissa == 0.0:
        return (1, 0, 0.0)
    return (2, exponent, abs(mantissa))


def _median(values: list[Scaled]) -> Scaled:
    values.sort(key=_key)
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    total = _add(values[middle - 1], values[middle])
    return _normalize(total[0] / 2.0, total[1])


def _as_float(value: Scaled, label: str) -> float:
    try:
        result = math.ldexp(value[0], value[1])
    except OverflowError:
        fail(f"Reducer.sensSlope {label} exceeds the finite Float64 range")
    if not math.isfinite(result):
        fail(f"Reducer.sensSlope {label} exceeds the finite Float64 range")
    return result


def sens_slope(x: list[float], y: list[float]) -> tuple[float, float] | None:
    """Return median pair slope and median point intercept, or None if undefined."""
    if len(x) < 2:
        return None
    scaled_x = [_from_float(value) for value in x]
    scaled_y = [_from_float(value) for value in y]
    slopes: list[Scaled] = []
    for left in range(len(x) - 1):
        for right in range(left + 1, len(x)):
            dx = _subtract(scaled_x[right], scaled_x[left])
            if dx[0] == 0.0:
                continue
            dy = _subtract(scaled_y[right], scaled_y[left])
            slopes.append(_divide(dy, dx))
    if not slopes:
        return None
    slope = _median(slopes)
    intercepts = [
        _subtract(value_y, _multiply(slope, value_x))
        for value_x, value_y in zip(scaled_x, scaled_y)
    ]
    offset = _median(intercepts)
    return _as_float(slope, "slope"), _as_float(offset, "offset")
