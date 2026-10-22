"""Bounded argmax for typed static arrays and fixed-shape raster arrays."""
from __future__ import annotations

import math

from .array_core import MAX_ARRAY_CELLS, MAX_ARRAY_RANK, StaticArray, charge_array, require_array
from .ir import Image, Pixel, const, fail
from .raster_array_core import (
    MAX_RASTER_ARRAY_RANK,
    RasterArrayImage,
    check_shape,
    wrap_array_image,
)


STATIC_ARGMAX_FUNCTIONS = frozenset({"Array.argmax"})
RASTER_ARGMAX_FUNCTIONS = frozenset({"Image.arrayArgmax"})


def _arguments(translator, name, arguments):
    if not isinstance(arguments, dict):
        fail(f"{name} arguments must be a dictionary")
    translator.allowed(arguments, {"array" if name == "Array.argmax" else "image"})
    required = "array" if name == "Array.argmax" else "image"
    if required not in arguments:
        fail(f"{name} requires {required}")


def _static_argmax(translator, value):
    data = require_array(value)
    if data.ndim > MAX_ARRAY_RANK or data.size > MAX_ARRAY_CELLS:
        fail("Array.argmax supports rank <= 8 and at most 10000 cells")
    if data.dtype.kind not in {"i", "u", "f"}:
        fail("Array.argmax requires a finite numeric typed Array")

    # One pass checks finite/exact-domain values and selects the first maximum.
    # Charge before touching the array or materializing its output list.
    charge_array(translator, 2 * int(data.size) + int(data.ndim) + 1)
    if data.size == 0:
        return None

    flat = data.flat
    best = flat[0].item()
    if data.dtype.kind == "f" and not math.isfinite(best):
        fail("Array.argmax requires finite Array values")
    if data.dtype.kind in {"i", "u"} and abs(best) > 2**53:
        fail("Array.argmax integer values must fit the exact Float64 domain")
    best_index = 0
    for index in range(1, int(data.size)):
        candidate = flat[index].item()
        if data.dtype.kind == "f" and not math.isfinite(candidate):
            fail("Array.argmax requires finite Array values")
        if data.dtype.kind in {"i", "u"} and abs(candidate) > 2**53:
            fail("Array.argmax integer values must fit the exact Float64 domain")
        if candidate > best:
            best = candidate
            best_index = index

    coordinates = [0] * int(data.ndim)
    remainder = best_index
    for axis in range(int(data.ndim) - 1, -1, -1):
        coordinates[axis] = remainder % int(data.shape[axis])
        remainder //= int(data.shape[axis])
    return coordinates


def invoke_static_argmax(translator, name, arguments):
    """Return row-major first-maximum coordinates for a typed StaticArray."""
    if name not in STATIC_ARGMAX_FUNCTIONS:
        fail(f"Unsupported static Array operation: {name}")
    _arguments(translator, name, arguments)
    value = arguments["array"]
    if not isinstance(value, StaticArray):
        fail("Array.argmax requires a typed static ee.Array")
    return _static_argmax(translator, value)


def _raster_argmax(translator, value):
    if not isinstance(value, RasterArrayImage):
        fail("Image.arrayArgmax requires a fixed-shape RasterArrayImage")
    if not isinstance(value.image, Image):
        fail("Image.arrayArgmax requires valid image metadata")
    count = check_shape(value.shape)
    rank = len(value.shape)
    if not 1 <= rank <= MAX_RASTER_ARRAY_RANK:
        fail("Image.arrayArgmax supports rank-1..8 RasterArrayImages")
    if not isinstance(value.cells, tuple) or len(value.cells) != count:
        fail("Image.arrayArgmax requires row-major cells matching the array shape")
    if (not isinstance(value.mask, Pixel)
            or not (value.mask.boolean or value.mask.op == "constant"
                    and value.mask.args == (None,))
            or not isinstance(value.name, str)):
        fail("Image.arrayArgmax requires a valid array mask and band name")

    # Cover cell/type scans, comparison and coordinate-selection nodes, casts,
    # and output layout before constructing any Pixel expressions or lists.
    metadata_work = len(value.image.bands) + len(value.image.props) + len(value.name)
    charge_array(
        translator,
        count * (2 * rank + 4) + rank * rank + 2 * rank + metadata_work,
    )

    for pixel in value.cells:
        if (not isinstance(pixel, Pixel) or pixel.op != "to_float"
                or len(pixel.args) != 1 or not isinstance(pixel.args[0], Pixel)
                or pixel.boolean):
            fail("Image.arrayArgmax requires explicit top-level toFloat() for every array cell")

    best = value.cells[0]
    coordinates = [const(0) for _ in range(rank)]
    strides = [math.prod(value.shape[axis + 1:]) for axis in range(rank)]
    for flat_index in range(1, count):
        candidate = value.cells[flat_index]
        better = Pixel("gt", (candidate, best), True)
        best = Pixel("if", (better, candidate, best))
        for axis, stride in enumerate(strides):
            coordinate = (flat_index // stride) % value.shape[axis]
            coordinates[axis] = Pixel(
                "if", (better, const(coordinate), coordinates[axis]),
            )

    cells = tuple(Pixel("to_float", (coordinate,)) for coordinate in coordinates)
    return wrap_array_image(value.image, (rank,), cells, value.mask, value.name)


def invoke_raster_argmax(translator, name, arguments):
    """Build Float32 coordinate Pixels for a fixed-shape array image."""
    if name not in RASTER_ARGMAX_FUNCTIONS:
        fail(f"Unsupported raster Array operation: {name}")
    _arguments(translator, name, arguments)
    return _raster_argmax(translator, arguments["image"])
