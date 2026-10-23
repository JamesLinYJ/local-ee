"""Pixel-unit shape masks for bounded Earth Engine Kernel constructors."""
from __future__ import annotations

import math

from .ir import fail
from .kernel_values import (
    MAX_KERNEL_CELLS, MAX_KERNEL_HEIGHT, MAX_KERNEL_WIDTH,
    _boolean, _charge, _finish, _number,
)


_SHAPE_FUNCTIONS = {
    "Kernel.circle", "Kernel.square", "Kernel.rectangle", "Kernel.plus",
    "Kernel.cross", "Kernel.diamond", "Kernel.octagon",
}


def _units(translator, arguments) -> None:
    units = arguments.get("units", "pixels")
    if type(units) is not str:
        fail("Kernel units must be the string 'pixels'")
    _charge(translator, 1 + len(units), "Kernel units validation")
    if units == "meters":
        fail("Kernel units='meters' require dynamic projection scaling and are unsupported locally")
    if units != "pixels":
        fail(f"Unsupported Kernel units: {units!r}; only 'pixels' are supported")


def _radius(value, label: str) -> tuple[float, int]:
    radius = _number(value, label)
    if radius < 0:
        fail(f"{label} must be non-negative")
    extent = math.ceil(radius)
    if extent * 2 + 1 > MAX_KERNEL_WIDTH:
        fail(f"{label} exceeds the 33 by 33 pixel Kernel limit")
    return radius, extent


def _shape(name: str, dx: int, dy: int, x_radius: float,
           y_radius: float) -> bool:
    ax, ay = abs(dx), abs(dy)
    if name == "Kernel.rectangle":
        return ax <= x_radius and ay <= y_radius
    if name == "Kernel.square":
        return max(ax, ay) <= x_radius
    if name == "Kernel.circle":
        return dx * dx + dy * dy <= x_radius * x_radius
    if name == "Kernel.plus":
        return (dx == 0 or dy == 0) and ax <= x_radius and ay <= x_radius
    if name == "Kernel.cross":
        return ax == ay and ax <= x_radius
    if name == "Kernel.diamond":
        return ax + ay <= x_radius
    # Matches Google's radius-3 example: square corners are clipped along
    # the 2*max(|x|,|y|)+min(|x|,|y|) <= 2*r+1 boundary.
    if name == "Kernel.octagon":
        return 2 * max(ax, ay) + min(ax, ay) <= 2 * x_radius + 1
    fail(f"Unsupported Earth Engine Kernel shape: {name}")


def invoke_kernel_shape(translator, name: str, arguments: dict):
    if name not in _SHAPE_FUNCTIONS:
        fail(f"Unsupported Earth Engine Kernel shape: {name}")
    if name == "Kernel.rectangle":
        translator.allowed(arguments, {"xRadius", "yRadius", "units", "normalize", "magnitude"})
        if "xRadius" not in arguments or "yRadius" not in arguments:
            fail("Kernel.rectangle requires xRadius and yRadius")
        x_radius, x_extent = _radius(arguments["xRadius"], "Kernel.rectangle xRadius")
        y_radius, y_extent = _radius(arguments["yRadius"], "Kernel.rectangle yRadius")
    else:
        translator.allowed(arguments, {"radius", "units", "normalize", "magnitude"})
        if "radius" not in arguments:
            fail(f"{name} requires radius")
        x_radius, x_extent = _radius(arguments["radius"], f"{name} radius")
        y_radius, y_extent = x_radius, x_extent
    _units(translator, arguments)
    normalize = _boolean(arguments.get("normalize", True), f"{name} normalize")
    magnitude = _number(arguments.get("magnitude", 1.0), f"{name} magnitude")

    width, height = 2 * x_extent + 1, 2 * y_extent + 1
    cells = width * height
    if cells > MAX_KERNEL_CELLS or width > MAX_KERNEL_WIDTH or height > MAX_KERNEL_HEIGHT:
        fail(f"{name} exceeds the 33 by 33 pixel Kernel limit")
    _charge(translator, 2 + 3 * cells, f"{name} mask generation")
    weights = [
        [1.0 if _shape(name, column - x_extent, row - y_extent,
                       x_radius, y_radius) else 0.0
         for column in range(width)]
        for row in range(height)
    ]
    return _finish(translator, weights, x_extent, y_extent, normalize, magnitude)
