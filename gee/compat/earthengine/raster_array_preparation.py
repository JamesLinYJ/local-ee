"""Dimensions and fixed padding for bounded raster-array images."""
from __future__ import annotations

import math
import struct
from dataclasses import replace

from .array_core import charge_array
from .ir import Image, Pixel, const, fail
from .raster_array_bands import (
    MAX_ARRAY_BAND_CELLS,
    RasterArrayBands,
    _require_bundle,
)
from .raster_array_core import (
    MAX_RASTER_ARRAY_AXIS,
    MAX_RASTER_ARRAY_RANK,
    RasterArrayImage,
    check_shape,
    masked_scalar,
    wrap_array_image,
)
from .raster_array_preparation_precision import raster_array_precision_flags
from .raster_array_preparation_grid import bind_pad_value_to_grid
from .raster_array_values import _array


RASTER_ARRAY_PREPARATION_FUNCTIONS = frozenset({
    "Image.arrayDimensions",
    "Image.arrayPad",
})
RASTER_ARRAY_PREPARATION_ARGUMENTS = {
    "Image.arrayDimensions": (frozenset({"input"}), frozenset()),
    "Image.arrayPad": (frozenset({"image", "lengths"}), frozenset({"pad"})),
}
_MAX_IMAGE_BANDS = 10_000
_MAX_EXACT_INTEGER = 2**53


def _arguments(translator, name, arguments, required, optional=()):
    if not isinstance(arguments, dict):
        fail(f"{name} arguments must be a dictionary")
    translator.allowed(arguments, set(required) | set(optional))
    missing = set(required) - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def _method_arguments(translator, name, arguments):
    required, optional = RASTER_ARRAY_PREPARATION_ARGUMENTS[name]
    _arguments(translator, name, arguments, required, optional)


def _dimension_scalar(array):
    """Return the per-band rank under the array's whole-value mask."""
    return masked_scalar(array, const(len(array.shape)), array.name).bands[0][1]


def _dimension(translator, value):
    if isinstance(value, RasterArrayImage):
        array = _array(value, "Image.arrayDimensions input")
        charge_array(translator, len(array.cells) + len(array.shape) + len(array.name) + 1)
        return replace(
            array.image,
            bands=[(array.name, _dimension_scalar(array))],
        )

    if isinstance(value, RasterArrayBands):
        bundle = _require_bundle(translator, value, "Image.arrayDimensions")
        work = sum(
            len(array.cells) + len(array.shape) + len(array.name) + 1
            for array in bundle.arrays
        )
        charge_array(translator, work)
        bands = [
            (array.name, _dimension_scalar(array))
            for array in bundle.arrays
        ]
        return replace(bundle.image, bands=bands)

    if not isinstance(value, Image):
        fail("Image.arrayDimensions input must be an Image")
    if type(value.bands) is not list or len(value.bands) > _MAX_IMAGE_BANDS:
        fail("Image.arrayDimensions input must have at most 10000 scalar bands")

    work = len(value.bands)
    for item in value.bands:
        if (type(item) is not tuple or len(item) != 2
                or type(item[0]) is not str or not isinstance(item[1], Pixel)):
            fail("Image.arrayDimensions requires named scalar image bands")
        work += len(item[0]) + 3
    charge_array(translator, work)

    output = []
    for name, pixel in value.bands:
        valid = Pixel("not", (Pixel("is_nodata", (pixel,), True),), True)
        dimension = Pixel("if", (valid, const(0), const(None)))
        output.append((name, dimension))
    return replace(value, bands=output)


def _lengths(translator, value, rank):
    if type(value) not in (list, tuple) or len(value) != rank:
        fail("Image.arrayPad lengths must contain one integer for each input axis")

    charge_array(translator, rank + 1)
    result = []
    for axis, length in enumerate(value):
        if (type(length) not in (int, float) or isinstance(length, bool)
                or isinstance(length, float)
                and (not math.isfinite(length) or not length.is_integer())
                or length < 0):
            fail(f"Image.arrayPad length at axis {axis} must be a nonnegative integer")
        if length > MAX_RASTER_ARRAY_AXIS:
            fail("Image.arrayPad output axes cannot exceed 64")
        result.append(int(length))
    return tuple(result)


def _pad_value(value, double_precision):
    if type(value) not in (int, float) or isinstance(value, bool):
        fail("Image.arrayPad pad must be a finite real number")
    if type(value) is int and abs(value) > _MAX_EXACT_INTEGER:
        fail("Image.arrayPad integer pad is outside the exact Float64 domain")
    if type(value) is float and not math.isfinite(value):
        fail("Image.arrayPad pad must be a finite real number")
    operation = "to_double" if double_precision else "to_float"
    if operation == "to_float":
        try:
            converted = struct.unpack("!f", struct.pack("!f", value))[0]
        except (OverflowError, struct.error):
            fail("Image.arrayPad pad overflows finite Float32")
        if not math.isfinite(converted):
            fail("Image.arrayPad pad overflows finite Float32")
    if abs(value) > _MAX_EXACT_INTEGER:
        fail("Image.arrayPad pad exceeds the local finite raster constant range")
    return Pixel(operation, (const(value),))


def _pad_cells(shape, output_shape, cells, pad):
    if shape == output_shape:
        return tuple(cells)

    output = []
    output_count = math.prod(output_shape)
    for flat_index in range(output_count):
        remaining = flat_index
        coordinates = [0] * len(output_shape)
        for axis in range(len(output_shape) - 1, -1, -1):
            coordinates[axis] = remaining % output_shape[axis]
            remaining //= output_shape[axis]

        if all(coordinate < size for coordinate, size in zip(coordinates, shape)):
            input_index = 0
            for coordinate, size in zip(coordinates, shape):
                input_index = input_index * size + coordinate
            output.append(cells[input_index])
        else:
            output.append(pad)
    return tuple(output)


def _pad(translator, arguments):
    name = "Image.arrayPad"
    _method_arguments(translator, name, arguments)
    image = arguments["image"]
    if isinstance(image, RasterArrayImage):
        arrays = (_array(image, f"{name} image"),)
        bundle = None
    elif isinstance(image, RasterArrayBands):
        bundle = _require_bundle(translator, image, name)
        arrays = tuple(
            _array(array, f"{name} image band") for array in bundle.arrays
        )
    else:
        fail(f"{name} image must contain only fixed-shape array bands")

    shape = arrays[0].shape
    if not 1 <= len(shape) <= MAX_RASTER_ARRAY_RANK:
        fail(f"{name} supports rank-1..8 array images")
    if any(array.shape != shape for array in arrays):
        fail(f"{name} requires every array band to have the same dimensions")
    target = _lengths(translator, arguments["lengths"], len(shape))
    output_shape = tuple(max(current, desired)
                         for current, desired in zip(shape, target))
    output_count = check_shape(output_shape)
    output_total = output_count * len(arrays)
    if output_total > MAX_ARRAY_BAND_CELLS:
        fail(f"{name} result exceeds 64 total array cells")

    double_precisions = raster_array_precision_flags(translator, arrays, name)
    pad_values = tuple(
        _pad_value(arguments.get("pad", 0.0), precision)
        for precision in double_precisions
    )
    if output_shape != shape:
        pad_values = tuple(
            bind_pad_value_to_grid(translator, array, pad, name)
            for array, pad in zip(arrays, pad_values)
        )
    input_total = sum(len(array.cells) for array in arrays)
    label_work = sum(len(array.name) for array in arrays)
    bundle_work = 0
    if bundle is not None:
        bundle_work = (
            len(arrays) + len(arrays) * len(output_shape) + label_work
            + output_total
        )
    copy_work = (
        output_total + input_total + 3 * len(shape) + label_work + bundle_work
    )
    # Reserve all output slots and per-cell padding work before materializing
    # the padded row-major tuples. The independent 500-node graph cap remains
    # enforced by Graph.node when the resulting Pixel expressions are compiled.
    charge_array(translator, copy_work)

    padded = tuple(
        wrap_array_image(
            array.image,
            output_shape,
            _pad_cells(array.shape, output_shape, array.cells, pad),
            array.mask,
            array.name,
        )
        for array, pad in zip(arrays, pad_values)
    )
    if bundle is None:
        return padded[0]
    # The output arrays are already validated and charged above. Constructing
    # the bundle directly avoids a second copy after allocating padded cells.
    return RasterArrayBands(bundle.image, padded)


def invoke_raster_array_preparation(translator, name, arguments):
    """Evaluate the fixed-rank array shape queries and append-only padding."""
    if name not in RASTER_ARRAY_PREPARATION_FUNCTIONS:
        fail(f"Unsupported raster array preparation operation: {name}")
    if name == "Image.arrayDimensions":
        _method_arguments(translator, name, arguments)
        return _dimension(translator, arguments["input"])
    return _pad(translator, arguments)
