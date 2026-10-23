"""Bounded pixel-distance Earth Engine Kernel constructors."""
from __future__ import annotations

import math

from .ir import fail
from .kernel_shapes import _units
from .kernel_values import (
    MAX_KERNEL_CELLS,
    MAX_KERNEL_HEIGHT,
    MAX_KERNEL_WIDTH,
    _boolean,
    _charge,
    _finish,
    _number,
)


DISTANCE_KERNEL_FUNCTIONS = frozenset({
    "Kernel.euclidean", "Kernel.manhattan", "Kernel.chebyshev",
})


def _distance(metric: str, dx: int, dy: int) -> float:
    if metric == "euclidean":
        return math.hypot(dx, dy)
    if metric == "manhattan":
        return float(abs(dx) + abs(dy))
    if metric == "chebyshev":
        return float(max(abs(dx), abs(dy)))
    fail(f"Unsupported Earth Engine distance Kernel metric: {metric}")


def invoke_distance_kernel(translator, name: str, arguments: dict):
    """Build a fixed pixel matrix of Euclidean, Manhattan, or Chebyshev distances."""
    if name not in DISTANCE_KERNEL_FUNCTIONS:
        fail(f"Unsupported Earth Engine distance Kernel: {name}")
    translator.allowed(arguments, {"radius", "units", "normalize", "magnitude"})
    if "radius" not in arguments:
        fail(f"{name} requires radius")
    radius = _number(arguments["radius"], f"{name} radius")
    if radius < 0.0:
        fail(f"{name} radius must be non-negative")
    _units(translator, arguments)
    normalize = _boolean(arguments.get("normalize", False), f"{name} normalize")
    magnitude = _number(arguments.get("magnitude", 1.0), f"{name} magnitude")

    # Local finite-kernel policy: radius selects an odd square extent using
    # ceil(radius); every cell in that square carries its distance, including
    # corner values greater than radius. The public integer-radius examples
    # show this square footprint but do not define fractional-radius behavior.
    extent = math.ceil(radius)
    width = height = 2 * extent + 1
    cells = width * height
    if (width > MAX_KERNEL_WIDTH or height > MAX_KERNEL_HEIGHT
            or cells > MAX_KERNEL_CELLS):
        fail(f"{name} exceeds the 33 by 33 pixel Kernel limit")

    _charge(translator, 2 + 3 * cells, f"{name} distance matrix generation")
    metric = name.removeprefix("Kernel.")
    rows = [
        [_distance(metric, dx, dy)
         for dx in range(-extent, extent + 1)]
        for dy in range(-extent, extent + 1)
    ]
    return _finish(translator, rows, extent, extent, normalize, magnitude)
