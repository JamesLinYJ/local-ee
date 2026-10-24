"""Bounded Image.interpolate and Image.polynomial scalar IR builders."""
from __future__ import annotations

import math
from fractions import Fraction

from .image_color_ir import (
    choose,
    finite_number_list,
    logical,
    mask_invalid,
    number,
    predicate,
    preflight_work,
    replace_bands,
    require_image,
    scalar,
)
from .ir import Pixel, fail


IMAGE_CURVE_FUNCTIONS = frozenset({"Image.interpolate", "Image.polynomial"})
IMAGE_CURVE_REQUIRED_ARGUMENTS = {
    "Image.interpolate": frozenset({"image", "x", "y"}),
    "Image.polynomial": frozenset({"image", "coefficients"}),
}
IMAGE_CURVE_OPTIONAL_ARGUMENTS = {
    "Image.interpolate": frozenset({"behavior"}),
    "Image.polynomial": frozenset(),
}
_MAX_CURVE_POINTS = 16
_MAX_POLYNOMIAL_COEFFICIENTS = 64
_BEHAVIORS = frozenset({"extrapolate", "clamp", "input", "mask"})


def _polynomial(translator, value: Pixel, coefficients: tuple[float, ...]) -> Pixel:
    if len(coefficients) == 1:
        # Degree zero still depends on the source pixel's mask and finite-value
        # policy. Multiplication by zero anchors the constant to that lineage.
        return number(
            translator, "add",
            number(translator, "multiply", value, scalar(0.0)),
            scalar(coefficients[0]),
        )
    output = scalar(coefficients[-1])
    for coefficient in reversed(coefficients[:-1]):
        output = number(
            translator, "add",
            number(translator, "multiply", value, output),
            scalar(coefficient),
        )
    return output


def _finite_width(left: float, right: float) -> float:
    """Return the exact knot distance if it is representable as a Float64."""
    width = Fraction.from_float(right) - Fraction.from_float(left)
    try:
        encoded = float(width)
    except OverflowError:
        encoded = math.inf
    if not math.isfinite(encoded) or encoded <= 0:
        fail("Image.interpolate knot intervals must have finite positive Float64 widths")
    return encoded


def _segment(translator, value: Pixel, x0: float, y0: float,
             x1: float, y1: float) -> Pixel:
    # A normalized position and weighted endpoints avoid the avoidable
    # (y1-y0) overflow of slope/intercept forms for opposite large ordinates.
    width = _finite_width(x0, x1)
    position = number(
        translator, "divide",
        number(translator, "subtract", value, scalar(x0)), scalar(width),
    )
    left = number(
        translator, "multiply", scalar(y0),
        number(translator, "subtract", scalar(1.0), position),
    )
    right = number(translator, "multiply", scalar(y1), position)
    return number(translator, "add", left, right)


def _piecewise(translator, value: Pixel, x: tuple[float, ...],
               y: tuple[float, ...]) -> Pixel:
    segments = [
        _segment(translator, value, x[index], y[index], x[index + 1], y[index + 1])
        for index in range(len(x) - 1)
    ]
    result = segments[-1]
    # Working backwards gives each interval one comparison and preserves the
    # shared y value at every exact breakpoint.
    for index in range(len(segments) - 2, -1, -1):
        before_next_knot = predicate(
            translator, "lte", value, scalar(x[index + 1]),
        )
        result = choose(translator, before_next_knot, segments[index], result)
    return result


def _interpolate(translator, value: Pixel, x: tuple[float, ...],
                 y: tuple[float, ...], behavior: str) -> Pixel:
    intervals = len(x) - 1
    # Charge a conservative scalar-expression estimate before constructing any
    # knot-dependent Pixel objects; every arithmetic/select helper also charges
    # its concrete canonical spec against this same shared budget.
    estimate = intervals * (6 * 160) + max(0, intervals - 1) * (160 + 224)
    if behavior != "extrapolate":
        estimate += 2 * 224 + 2 * 160 + (160 if behavior == "mask" else 0)
    preflight_work(translator, estimate, "Image.interpolate")

    value_in_range = _piecewise(translator, value, x, y)
    if behavior == "extrapolate":
        return value_in_range
    if behavior == "mask":
        inside = logical(
            translator, "and",
            predicate(translator, "gte", value, scalar(x[0])),
            predicate(translator, "lte", value, scalar(x[-1])),
        )
        return mask_invalid(inside, value_in_range)
    below = predicate(translator, "lt", value, scalar(x[0]))
    above = predicate(translator, "gt", value, scalar(x[-1]))
    low_value = scalar(y[0]) if behavior == "clamp" else value
    high_value = scalar(y[-1]) if behavior == "clamp" else value
    return choose(
        translator, below, low_value,
        choose(translator, above, high_value, value_in_range),
    )


def invoke_image_curves(translator, name: str, arguments: dict):
    """Build bounded piecewise interpolation or ascending-coefficient polynomials."""
    if name not in IMAGE_CURVE_FUNCTIONS:
        fail(f"Unsupported Image curve operation: {name}")
    image = require_image(
        translator, name, arguments,
        set(IMAGE_CURVE_REQUIRED_ARGUMENTS[name]),
        set(IMAGE_CURVE_OPTIONAL_ARGUMENTS[name]),
        max_bands=10_000,
    )
    if name == "Image.polynomial":
        coefficients = finite_number_list(
            translator, arguments["coefficients"],
            "Image.polynomial coefficients", minimum=1,
            maximum=_MAX_POLYNOMIAL_COEFFICIENTS,
        )
        operations_per_band = 2 if len(coefficients) == 1 else 2 * (len(coefficients) - 1)
        preflight_work(
            translator, operations_per_band * 160 * len(image.bands), name,
        )
        bands = [
            (band_name, _polynomial(translator, pixel, coefficients))
            for band_name, pixel in image.bands
        ]
        return replace_bands(image, bands)

    x = finite_number_list(
        translator, arguments["x"], "Image.interpolate x",
        minimum=2, maximum=_MAX_CURVE_POINTS,
    )
    y = finite_number_list(
        translator, arguments["y"], "Image.interpolate y",
        minimum=2, maximum=_MAX_CURVE_POINTS,
    )
    if len(x) != len(y):
        fail("Image.interpolate x and y must have equal lengths")
    if any(right <= left for left, right in zip(x, x[1:])):
        fail("Image.interpolate x values must be strictly increasing")
    # Validate every interval before building or charging any segment graph.
    for left, right in zip(x, x[1:]):
        _finite_width(left, right)
    behavior = arguments.get("behavior", "extrapolate")
    # The official optional parameter defaults to extrapolate. The pinned SDK
    # omits an explicit None during serialization, so direct None follows that
    # same default; all non-null values must be one of the four documented names.
    if behavior is None:
        behavior = "extrapolate"
    if type(behavior) is not str or behavior not in _BEHAVIORS:
        fail("Image.interpolate behavior must be extrapolate, clamp, input, or mask")
    band_name, value = image.bands[0]
    output = _interpolate(translator, value, x, y, behavior)
    return replace_bands(image, [(band_name, output)])
