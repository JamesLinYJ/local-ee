"""Independent scalar references for Image RGB/HSV and curve formulas."""
from __future__ import annotations

import colorsys
from fractions import Fraction


def rgb_to_hsv(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """Use Python's independent standard-library color-space reference."""
    if any(not 0.0 <= value <= 1.0 for value in rgb):
        return float("nan"), float("nan"), float("nan")
    return colorsys.rgb_to_hsv(*rgb)


def hsv_to_rgb(hsv: tuple[float, float, float]) -> tuple[float, float, float]:
    """Use Python's independent standard-library hue-sector implementation."""
    if any(not 0.0 <= value <= 1.0 for value in hsv):
        return float("nan"), float("nan"), float("nan")
    return colorsys.hsv_to_rgb(*hsv)


def _fraction(value: int | float) -> Fraction:
    return Fraction(value) if type(value) is int else Fraction.from_float(value)


def interpolate(value: int | float, x: tuple[float, ...],
                y: tuple[float, ...], behavior: str) -> float | None:
    """Evaluate piecewise linear interpolation exactly before binary64 output."""
    vx = _fraction(value)
    fx = tuple(_fraction(item) for item in x)
    fy = tuple(_fraction(item) for item in y)
    if vx < fx[0]:
        if behavior == "clamp":
            return float(fy[0])
        if behavior == "input":
            return float(vx)
        if behavior == "mask":
            return None
        index = 0
    elif vx > fx[-1]:
        if behavior == "clamp":
            return float(fy[-1])
        if behavior == "input":
            return float(vx)
        if behavior == "mask":
            return None
        index = len(fx) - 2
    else:
        index = next(
            (slot for slot in range(len(fx) - 1) if vx <= fx[slot + 1]),
            len(fx) - 2,
        )
    ratio = (vx - fx[index]) / (fx[index + 1] - fx[index])
    result = fy[index] * (1 - ratio) + fy[index + 1] * ratio
    return float(result)


def polynomial(value: int | float, coefficients: tuple[float, ...]) -> float:
    """Evaluate ascending coefficients with exact rational arithmetic."""
    x = _fraction(value)
    result = Fraction(0)
    power = Fraction(1)
    for coefficient in coefficients:
        result += _fraction(coefficient) * power
        power *= x
    return float(result)
