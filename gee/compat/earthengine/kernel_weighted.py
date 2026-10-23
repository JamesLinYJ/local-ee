"""Bounded finite Gaussian and directional Earth Engine Kernel values."""
from __future__ import annotations

import math
import sys

from .ir import fail
from .kernel_shapes import _units
from .kernel_values import (
    MAX_KERNEL_CELLS,
    MAX_KERNEL_WIDTH,
    _boolean,
    _charge,
    _finish,
    _number,
)


_EDGE_WEIGHTS = {
    "Kernel.laplacian4": (
        (0.0, 1.0, 0.0),
        (1.0, -4.0, 1.0),
        (0.0, 1.0, 0.0),
    ),
    "Kernel.laplacian8": (
        (1.0, 1.0, 1.0),
        (1.0, -8.0, 1.0),
        (1.0, 1.0, 1.0),
    ),
    "Kernel.sobel": (
        (-1.0, 0.0, 1.0),
        (-2.0, 0.0, 2.0),
        (-1.0, 0.0, 1.0),
    ),
    "Kernel.prewitt": (
        (1.0, 0.0, -1.0),
        (1.0, 0.0, -1.0),
        (1.0, 0.0, -1.0),
    ),
    "Kernel.roberts": (
        (1.0, 0.0),
        (0.0, -1.0),
    ),
    "Kernel.compass": (
        (1.0, 1.0, -1.0),
        (1.0, -2.0, -1.0),
        (1.0, 1.0, -1.0),
    ),
    "Kernel.kirsch": (
        (5.0, -3.0, -3.0),
        (5.0, 0.0, -3.0),
        (5.0, -3.0, -3.0),
    ),
}
WEIGHTED_KERNEL_FUNCTIONS = frozenset({"Kernel.gaussian", *_EDGE_WEIGHTS})
_LOG_FLOAT64_MAX = math.log(sys.float_info.max)


def _gaussian(translator, arguments):
    translator.allowed(arguments, {"radius", "sigma", "units", "normalize", "magnitude"})
    if "radius" not in arguments:
        fail("Kernel.gaussian requires radius")
    radius = _number(arguments["radius"], "Kernel.gaussian radius")
    if radius < 0:
        fail("Kernel.gaussian radius must be non-negative")
    sigma = _number(arguments.get("sigma", 1.0), "Kernel.gaussian sigma")
    if sigma <= 0:
        fail("Kernel.gaussian sigma must be positive")
    _units(translator, arguments)
    normalize = _boolean(arguments.get("normalize", True), "Kernel.gaussian normalize")
    magnitude = _number(arguments.get("magnitude", 1.0), "Kernel.gaussian magnitude")

    # Match the existing pixel-shape extent convention: ceil(radius), then
    # retain integer samples on or inside the declared radius on each axis.
    extent = math.ceil(radius)
    if extent * 2 + 1 > MAX_KERNEL_WIDTH:
        fail("Kernel.gaussian exceeds the 33 by 33 pixel Kernel limit")
    width = height = 2 * extent + 1
    cells = width * height
    if cells > MAX_KERNEL_CELLS:
        fail("Kernel.gaussian exceeds 1089 cells")
    _charge(translator, 2 + 3 * cells, "Kernel.gaussian sample generation")

    rows = []
    for dy in range(-extent, extent + 1):
        row = []
        for dx in range(-extent, extent + 1):
            if abs(dx) > radius or abs(dy) > radius:
                row.append(0.0)
                continue
            # Ratios may overflow to infinity for tiny finite sigma; exp(-inf)
            # is the correct zero tail limit.
            x_ratio = dx / sigma
            y_ratio = dy / sigma
            distance = x_ratio * x_ratio + y_ratio * y_ratio
            log_shape = -0.5 * distance
            if normalize:
                # The continuous-density prefactor cancels during finite-grid
                # normalization, avoiding overflow for very small sigma.
                row.append(math.exp(log_shape))
                continue
            if magnitude == 0.0:
                row.append(math.copysign(0.0, magnitude))
                continue
            log_density = -math.log(2.0 * math.pi) - 2.0 * math.log(sigma) + log_shape
            log_weight = log_density + math.log(abs(magnitude))
            if log_weight > _LOG_FLOAT64_MAX:
                fail("Kernel.gaussian density weight exceeds the finite Float64 domain")
            value = math.exp(log_weight)
            row.append(math.copysign(value, magnitude))
        rows.append(row)
    return _finish(translator, rows, extent, extent, normalize,
                   magnitude if normalize else 1.0)


def _edge(translator, name, arguments):
    translator.allowed(arguments, {"magnitude", "normalize"})
    normalize = _boolean(arguments.get("normalize", False), f"{name} normalize")
    magnitude = _number(arguments.get("magnitude", 1.0), f"{name} magnitude")
    if normalize:
        fail(
            f"{name} normalize=true is unsupported locally: official method pages say sum to 1, "
            "while the convolution guide says signed kernels normalize to sum 0 without defining weights"
        )
    weights = _EDGE_WEIGHTS[name]
    return _finish(translator, weights, len(weights[0]) // 2, len(weights) // 2,
                   False, magnitude)


def invoke_weighted_kernel(translator, name, arguments):
    if name == "Kernel.gaussian":
        return _gaussian(translator, arguments)
    if name in _EDGE_WEIGHTS:
        return _edge(translator, name, arguments)
    fail(f"Unsupported weighted Earth Engine Kernel: {name}")
