"""Bounded focus-aligned addition and quarter-turn Kernel transforms."""
from __future__ import annotations

import math

from .ir import fail
from .kernel_values import (
    MAX_KERNEL_CELLS,
    MAX_KERNEL_HEIGHT,
    KernelSpec,
    MAX_KERNEL_WIDTH,
    _boolean,
    _charge,
    _finish,
    _integer,
    validate_kernel,
)


KERNEL_TRANSFORM_FUNCTIONS = frozenset({"Kernel.rotate", "Kernel.add"})


def _rotate(translator, arguments):
    translator.allowed(arguments, {"kernel", "rotations"})
    if "kernel" not in arguments or "rotations" not in arguments:
        fail("Kernel.rotate requires kernel and rotations")
    kernel = validate_kernel(translator, arguments["kernel"])
    rotations = _integer(arguments["rotations"], "Kernel.rotate rotations") % 4
    if rotations == 0:
        _charge(translator, 1, "Kernel.rotate")
        return kernel

    cells = kernel.width * kernel.height
    _charge(translator, 2 + rotations * (3 * cells) + 2 * cells,
            "Kernel.rotate matrix transformation")
    rows = [list(row) for row in kernel.weights]
    width, height = kernel.width, kernel.height
    focus_x, focus_y = kernel.x, kernel.y
    for _ in range(rotations):
        rotated = [[0.0] * height for _ in range(width)]
        for y, row in enumerate(rows):
            for x, weight in enumerate(row):
                rotated[x][height - 1 - y] = weight
        rows = rotated
        focus_x, focus_y = height - 1 - focus_y, focus_x
        width, height = height, width
    return KernelSpec(tuple(tuple(row) for row in rows), focus_x, focus_y)


def _add(translator, arguments):
    translator.allowed(arguments, {"kernel1", "kernel2", "normalize"})
    if "kernel1" not in arguments or "kernel2" not in arguments:
        fail("Kernel.add requires kernel1 and kernel2")
    normalize = _boolean(arguments.get("normalize", False), "Kernel.add normalize")
    first = validate_kernel(translator, arguments["kernel1"])
    second = validate_kernel(translator, arguments["kernel2"])

    first_min_x, first_max_x = -first.x, first.width - 1 - first.x
    second_min_x, second_max_x = -second.x, second.width - 1 - second.x
    first_min_y, first_max_y = -first.y, first.height - 1 - first.y
    second_min_y, second_max_y = -second.y, second.height - 1 - second.y
    min_x, max_x = min(first_min_x, second_min_x), max(first_max_x, second_max_x)
    min_y, max_y = min(first_min_y, second_min_y), max(first_max_y, second_max_y)
    width, height = max_x - min_x + 1, max_y - min_y + 1
    cells = width * height
    if (width > MAX_KERNEL_WIDTH or height > MAX_KERNEL_HEIGHT
            or cells > MAX_KERNEL_CELLS):
        fail("Kernel.add aligned result exceeds the 33 by 33, 1089-cell limit")
    focus_x, focus_y = -min_x, -min_y
    if not (0 <= focus_x <= 32 and 0 <= focus_y <= 32):
        fail("Kernel.add aligned focus offsets must be within 32 pixels")

    first_cells = first.width * first.height
    second_cells = second.width * second.height
    _charge(translator, 2 + 3 * (first_cells + second_cells) + 2 * cells,
            "Kernel.add alignment and accumulation")
    values = [[0.0] * width for _ in range(height)]
    for kernel in (first, second):
        for y, row in enumerate(kernel.weights):
            out_y = y - kernel.y - min_y
            for x, weight in enumerate(row):
                out_x = x - kernel.x - min_x
                result = values[out_y][out_x] + weight
                if not math.isfinite(result):
                    fail("Kernel.add weights exceed the finite Float64 domain")
                values[out_y][out_x] = result

    if normalize and any(value < 0.0 for row in values for value in row):
        fail(
            "Kernel.add normalize=true with signed weights is unsupported locally: "
            "official method pages say sum to 1, while the convolution guide says sum 0"
        )
    return _finish(translator, values, focus_x, focus_y, normalize)


def invoke_kernel_transform(translator, name, arguments):
    if name == "Kernel.rotate":
        return _rotate(translator, arguments)
    if name == "Kernel.add":
        return _add(translator, arguments)
    fail(f"Unsupported Earth Engine Kernel transform: {name}")
