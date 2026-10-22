"""Bounded concatenation and repetition for fixed-shape raster arrays."""
from __future__ import annotations

import math

from .array_core import charge_array
from .ir import Image, Pixel, UnsupportedEEError, fail
from .raster_array_coordinates import constant_pixel_integer
from .raster_array_core import (
    MAX_RASTER_ARRAY_RANK,
    RasterArrayImage,
    check_shape,
    combined_mask,
    wrap_array_image,
)
from .raster_array_values import _array, _result_image


RASTER_CONCATENATION_FUNCTIONS = frozenset({
    "Image.arrayCat",
    "Image.arrayRepeat",
})


def _arguments(translator, name, arguments, required):
    if not isinstance(arguments, dict):
        fail(f"{name} arguments must be a dictionary")
    translator.allowed(arguments, required)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def _array_argument(value, name, parameter):
    label = f"{name} {parameter}"
    array = _array(value, label)
    rank = len(array.shape)
    if not 1 <= rank <= MAX_RASTER_ARRAY_RANK:
        fail(f"{label} requires a rank-1..8 array")
    return array, check_shape(array.shape)


def _axis(value, rank, name):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or isinstance(value, float) and not math.isfinite(value)
            or int(value) != value):
        fail(f"{name} axis must be an integer")
    axis = int(value)
    if not 0 <= axis < rank:
        fail(f"{name} axis must be within the array rank")
    return axis


def _cat(translator, arguments):
    name = "Image.arrayCat"
    _arguments(translator, name, arguments, {"image1", "image2", "axis"})
    left, left_count = _array_argument(arguments["image1"], name, "image1")
    right, right_count = _array_argument(arguments["image2"], name, "image2")
    if len(left.shape) != len(right.shape):
        fail(f"{name} requires arrays with the same rank")
    axis = _axis(arguments["axis"], len(left.shape), name)
    if any(left.shape[index] != right.shape[index]
           for index in range(len(left.shape)) if index != axis):
        fail(f"{name} requires matching non-concatenated dimensions")

    shape = list(left.shape)
    shape[axis] += right.shape[axis]
    shape = tuple(shape)
    output_count = check_shape(shape)
    metadata_work = len(left.image.bands) + len(left.image.props)
    charge_array(translator, left_count + right_count + output_count
                 + 2 * len(shape) + metadata_work)

    outer = math.prod(shape[:axis])
    inner = math.prod(shape[axis + 1:])
    left_axis, right_axis = left.shape[axis], right.shape[axis]
    cells = []
    for block in range(outer):
        left_start = block * left_axis * inner
        right_start = block * right_axis * inner
        cells.extend(left.cells[left_start:left_start + left_axis * inner])
        cells.extend(right.cells[right_start:right_start + right_axis * inner])

    mask = combined_mask(left.mask, right.mask)
    image = _result_image(left, right)
    return wrap_array_image(image, shape, tuple(cells), mask, left.name)


def _repeat_count(translator, value, name):
    if not isinstance(value, Image):
        fail(f"{name} copies must be a one-band constant Image")
    if len(value.bands) != 1:
        fail(f"{name} copies must contain exactly one scalar band")
    if (value.source is not None or value.footprint is not None
            or value.footprint_is_absolute or value.mapped):
        fail(f"{name} copies must be unmasked and have no source or footprint")
    pixel = value.bands[0][1]
    if not isinstance(pixel, Pixel):
        fail(f"{name} copies must be a one-band constant Image")
    try:
        copies = constant_pixel_integer(translator, pixel, f"{name} copies", 1)
    except UnsupportedEEError:
        raise
    except (AttributeError, OverflowError, TypeError, ValueError):
        fail(f"{name} copies must be a finite positive integer constant Image")
    return copies


def _repeat(translator, arguments):
    name = "Image.arrayRepeat"
    _arguments(translator, name, arguments, {"input", "axis", "copies"})
    array, input_count = _array_argument(arguments["input"], name, "input")
    axis = _axis(arguments["axis"], len(array.shape), name)
    copies = _repeat_count(translator, arguments["copies"], name)

    shape = list(array.shape)
    shape[axis] *= copies
    shape = tuple(shape)
    output_count = check_shape(shape)
    metadata_work = len(array.image.bands) + len(array.image.props)
    charge_array(translator, input_count + output_count + copies
                 + len(shape) + metadata_work)

    axis_length = array.shape[axis]
    inner = math.prod(array.shape[axis + 1:])
    block_size = axis_length * inner
    cells = []
    for outer in range(math.prod(array.shape[:axis])):
        start = outer * block_size
        block = array.cells[start:start + block_size]
        for _ in range(copies):
            cells.extend(block)
    return wrap_array_image(array.image, shape, tuple(cells), array.mask, array.name)


def invoke_raster_concatenation(translator, name, arguments):
    """Evaluate one fixed-shape array concatenation or repetition."""
    if name not in RASTER_CONCATENATION_FUNCTIONS:
        fail(f"Unsupported raster array concatenation operation: {name}")
    if name == "Image.arrayCat":
        return _cat(translator, arguments)
    return _repeat(translator, arguments)
