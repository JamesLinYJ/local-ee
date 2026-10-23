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


def validate_distance_kernel_provenance(
    translator, weights, x: int, y: int, metric, radius,
) -> None:
    """Prove that optional KernelSpec metadata matches a raw distance kernel.

    The metadata is useful only when both the metric and original radius are
    retained and the complete matrix is exactly the corresponding constructor
    output. This prevents arbitrary fixed or transformed weights from being
    treated as a distance metric by a downstream image operation.
    """
    if type(metric) is not str or metric not in {"euclidean", "manhattan", "chebyshev"}:
        fail("KernelSpec has an unsupported distance-kernel metric")
    if (type(radius) is not float or not math.isfinite(radius)
            or radius < 0.0 or radius > 16.0):
        fail("KernelSpec has an invalid distance-kernel radius")
    extent = math.ceil(radius)
    width = height = 2 * extent + 1
    if (type(weights) is not tuple or len(weights) != height
            or any(type(row) is not tuple or len(row) != width for row in weights)
            or x != extent or y != extent):
        fail("KernelSpec distance-kernel provenance does not match its dimensions or focus")

    cells = width * height
    _charge(translator, 2 + 3 * cells, "Distance Kernel provenance validation")
    for row_index, row in enumerate(weights):
        dy = row_index - extent
        for column_index, weight in enumerate(row):
            dx = column_index - extent
            expected = _distance(metric, dx, dy)
            if type(weight) is not float or weight.hex() != expected.hex():
                fail("KernelSpec distance-kernel provenance does not match its weights")


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
    # Negative zero has the same nonnegative radius semantics as zero. Store
    # the canonical positive-zero value required by the distance wire spec.
    provenance_radius = 0.0 if radius == 0.0 else radius
    carries_provenance = not normalize and magnitude == 1.0
    return _finish(
        translator, rows, extent, extent, normalize, magnitude,
        distance_metric=metric if carries_provenance else None,
        distance_radius=provenance_radius if carries_provenance else None,
    )
