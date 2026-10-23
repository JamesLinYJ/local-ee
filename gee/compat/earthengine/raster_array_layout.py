"""Bounded layout operations for fixed-shape raster array images."""
from __future__ import annotations

import itertools
import math

from .array_core import charge_array
from .ir import Image, Pixel, fail
from .raster_array_coordinates import constant_image_integer, constant_pixel_integer
from .raster_array_core import (
    RasterArrayImage,
    check_shape,
    flatten_image,
    masked_scalar,
    wrap_array_image,
)


RASTER_ARRAY_LAYOUT_FUNCTIONS = frozenset({
    "Image.arrayFlatten",
    "Image.arrayProject",
    "Image.arrayTranspose",
    "Image.matrixTranspose",
    "Image.arraySlice",
    "Image.arrayGet",
})


def _arguments(translator, name, arguments, required, optional=()):
    if not isinstance(arguments, dict):
        fail(f"{name} arguments must be a dictionary")
    translator.allowed(arguments, set(required) | set(optional))
    missing = set(required) - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def _integer(value, label, minimum=None):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or isinstance(value, float) and not math.isfinite(value)
            or int(value) != value):
        fail(f"{label} must be an integer")
    result = int(value)
    if minimum is not None and result < minimum:
        fail(f"{label} must be >= {minimum}")
    return result


def _array(value, label):
    if not isinstance(value, RasterArrayImage):
        fail(f"{label} requires a fixed-shape raster array image")
    count = check_shape(value.shape)
    if (not isinstance(value.image, Image) or not isinstance(value.cells, tuple)
            or len(value.cells) != count
            or any(not isinstance(cell, Pixel) for cell in value.cells)
            or not isinstance(value.mask, Pixel) or not isinstance(value.name, str)):
        fail(f"{label} received an invalid raster array image")
    return value


def _axis(value, rank, label):
    axis = _integer(value, f"{label} axis", 0)
    if axis >= rank:
        fail(f"{label} axis is outside the array rank")
    return axis


def _flatten(translator, arguments):
    name = "Image.arrayFlatten"
    _arguments(translator, name, arguments, {"image", "coordinateLabels"}, {"separator"})
    array = _array(arguments["image"], name)
    labels = arguments["coordinateLabels"]
    separator = arguments.get("separator", "_")
    if not isinstance(separator, str):
        fail("Image.arrayFlatten separator must be a string")
    rank = len(array.shape)
    if rank == 0:
        fail("Image.arrayFlatten does not support rank-zero array pixels")
    if not isinstance(labels, list) or len(labels) != rank:
        fail("Image.arrayFlatten coordinateLabels must contain one label list per axis")
    for axis, (axis_labels, length) in enumerate(zip(labels, array.shape)):
        if (not isinstance(axis_labels, list) or len(axis_labels) != length
                or any(not isinstance(label, str) for label in axis_labels)):
            fail(f"Image.arrayFlatten labels for axis {axis} must be {length} strings")

    # Bound both the number of output bands and their combined names before
    # building the Cartesian product. The final axis varies fastest (row-major).
    band_count = check_shape(array.shape)
    name_chars = 0
    for axis_labels, length in zip(labels, array.shape):
        name_chars += sum(map(len, axis_labels)) * (band_count // length)
    name_chars += len(separator) * (rank - 1) * band_count
    charge_array(translator, band_count + name_chars)
    names = [separator.join(parts) for parts in itertools.product(*labels)]
    if len(set(names)) != len(names):
        fail("Image.arrayFlatten produced duplicate band names")
    return flatten_image(array, names)


def _project(translator, arguments):
    name = "Image.arrayProject"
    _arguments(translator, name, arguments, {"input", "axes"})
    array = _array(arguments["input"], name)
    axes = arguments["axes"]
    if not isinstance(axes, list) or len(axes) > len(array.shape):
        fail("Image.arrayProject axes must be a list of valid axes")
    retained = [_integer(axis, "Image.arrayProject axis", 0) for axis in axes]
    if any(axis >= len(array.shape) for axis in retained):
        fail("Image.arrayProject axis is outside the array rank")
    if retained != sorted(set(retained)):
        fail("Image.arrayProject requires unique axes in ascending order")
    retained_set = set(retained)
    if any(size != 1 for axis, size in enumerate(array.shape) if axis not in retained_set):
        fail("Image.arrayProject can drop only singleton axes")
    shape = tuple(array.shape[axis] for axis in retained)
    cells = check_shape(shape)
    charge_array(translator, cells + len(array.shape))
    # Dropped dimensions are all singleton and retained axes stay in their
    # original order, so row-major cell order is unchanged.
    return wrap_array_image(array.image, shape, array.cells, array.mask, array.name)


def _transpose(translator, arguments, name="Image.arrayTranspose"):
    _arguments(translator, name, arguments, {"input"}, {"axis1", "axis2"})
    array = _array(arguments["input"], name)
    axis1 = _axis(arguments.get("axis1", 0), len(array.shape), name)
    axis2 = _axis(arguments.get("axis2", 1), len(array.shape), name)
    shape = list(array.shape)
    shape[axis1], shape[axis2] = shape[axis2], shape[axis1]
    shape = tuple(shape)
    cells_count = check_shape(shape)
    charge_array(translator, cells_count + len(shape))
    if axis1 == axis2:
        cells = array.cells
    else:
        old_shape = array.shape
        new_cells = []
        for linear in range(cells_count):
            remainder = linear
            coordinates = [0] * len(shape)
            for axis in range(len(shape) - 1, -1, -1):
                coordinates[axis] = remainder % shape[axis]
                remainder //= shape[axis]
            coordinates[axis1], coordinates[axis2] = coordinates[axis2], coordinates[axis1]
            source_index = 0
            for coordinate, length in zip(coordinates, old_shape):
                source_index = source_index * length + coordinate
            new_cells.append(array.cells[source_index])
        cells = tuple(new_cells)
    return wrap_array_image(array.image, shape, cells, array.mask, array.name)


def _slice(translator, arguments):
    name = "Image.arraySlice"
    _arguments(translator, name, arguments, {"input"}, {"axis", "start", "end", "step"})
    array = _array(arguments["input"], name)
    axis = _axis(arguments.get("axis", 0), len(array.shape), name)
    raw_start = arguments.get("start")
    raw_end = arguments.get("end")
    start = 0 if raw_start is None else constant_image_integer(translator, raw_start, f"{name} start")
    end = (array.shape[axis] if raw_end is None else
           constant_image_integer(translator, raw_end, f"{name} end"))
    step = _integer(arguments.get("step", 1), f"{name} step", 1)
    length = array.shape[axis]
    if start < 0:
        start += length
    if end < 0:
        end += length

    # Preserve the requested step origin while discarding out-of-range values,
    # matching the fixed Array.slice semantics used in this compiler.
    lower, upper = max(0, start), min(length, end)
    if upper <= lower:
        count = 0
        first = 0
    else:
        offset = max(0, (lower - start + step - 1) // step)
        first = start + offset * step
        count = 0 if first >= upper else 1 + (upper - 1 - first) // step
    if count == 0:
        fail("Image.arraySlice derived an empty array, which is unsupported")
    shape = list(array.shape)
    shape[axis] = count
    shape = tuple(shape)
    cells_count = check_shape(shape)
    charge_array(translator, cells_count + count)

    # Row-major storage is a sequence of `outer` blocks, each with `inner`
    # contiguous cells per source coordinate on the sliced axis.
    outer = math.prod(array.shape[:axis])
    inner = math.prod(array.shape[axis + 1:])
    cells = []
    for block in range(outer):
        for position in range(count):
            source = (block * length + first + position * step) * inner
            cells.extend(array.cells[source:source + inner])
    return wrap_array_image(array.image, shape, tuple(cells), array.mask, array.name)


def _get(translator, arguments):
    name = "Image.arrayGet"
    _arguments(translator, name, arguments, {"image", "position"})
    array = _array(arguments["image"], name)
    position = arguments["position"]
    if not isinstance(position, Image):
        fail("Image.arrayGet position must be a scalar-band Image")
    if len(position.bands) != len(array.shape):
        fail("Image.arrayGet position needs one scalar band per array axis")
    coordinates = []
    for axis, (_, pixel) in enumerate(position.bands):
        coordinate = constant_pixel_integer(
            translator,
            pixel,
            f"Image.arrayGet position axis {axis}",
            0,
        )
        if coordinate >= array.shape[axis]:
            fail(f"Image.arrayGet position axis {axis} is outside the array shape")
        coordinates.append(coordinate)
    linear = 0
    for coordinate, length in zip(coordinates, array.shape):
        linear = linear * length + coordinate
    charge_array(translator, len(array.shape) + 1)
    return masked_scalar(array, array.cells[linear], array.name)


def invoke_raster_layout(translator, name, arguments):
    """Evaluate one bounded Image array layout operation."""
    if name not in RASTER_ARRAY_LAYOUT_FUNCTIONS:
        fail(f"Unsupported raster array layout operation: {name}")
    if name == "Image.arrayFlatten":
        return _flatten(translator, arguments)
    if name == "Image.arrayProject":
        return _project(translator, arguments)
    if name in {"Image.arrayTranspose", "Image.matrixTranspose"}:
        return _transpose(translator, arguments, name)
    if name == "Image.arraySlice":
        return _slice(translator, arguments)
    return _get(translator, arguments)
