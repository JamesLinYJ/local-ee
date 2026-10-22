"""Bounded shape reinterpretation for fixed-shape raster array images."""
from __future__ import annotations

import math

from .array_core import charge_array
from .ir import Image, Pixel, const, fail, integer
from .raster_array_coordinates import constant_pixel_integer
from .raster_array_core import (
    MAX_RASTER_ARRAY_CELLS,
    MAX_RASTER_ARRAY_RANK,
    MAX_RASTER_ARRAY_AXIS,
    RasterArrayImage,
    check_shape,
    wrap_array_image,
)


RASTER_RESHAPE_FUNCTIONS = frozenset({"Image.arrayReshape"})


def _array(value, label):
    if not isinstance(value, RasterArrayImage):
        fail(f"{label} requires a single-band fixed-shape RasterArrayImage")
    count = check_shape(value.shape)
    if (not isinstance(value.image, Image) or not isinstance(value.cells, tuple)
            or len(value.cells) != count
            or any(not isinstance(cell, Pixel) for cell in value.cells)
            or not isinstance(value.mask, Pixel)
            or not (value.mask.boolean or value.mask.op == "constant"
                    and value.mask.args == (None,))
            or not isinstance(value.name, str)):
        fail(f"{label} received a malformed RasterArrayImage")
    return count


def _reshape(translator, arguments):
    name = "Image.arrayReshape"
    if not isinstance(arguments, dict):
        fail(f"{name} arguments must be a dictionary")
    translator.allowed(arguments, {"image", "lengths", "dimensions"})
    missing = {"image", "lengths", "dimensions"} - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")

    array = arguments["image"]
    input_cells = _array(array, name)
    lengths = arguments["lengths"]
    _array(lengths, f"{name} lengths")
    dimensions = integer(arguments["dimensions"], f"{name} dimensions", 1)
    if dimensions > MAX_RASTER_ARRAY_RANK:
        fail(f"{name} dimensions must be between 1 and 8")
    if len(lengths.shape) != 1 or lengths.shape != (dimensions,):
        fail(f"{name} lengths must be a rank-1 array with one value per dimension")

    # A single global shape is sound only when every pixel has a usable lengths
    # vector. Dynamic or NoData masks are not evidence that those values exist.
    if lengths.mask != const(True):
        fail(f"{name} lengths must have a provably valid, unmasked array mask")

    requested = tuple(
        constant_pixel_integer(
            translator, cell, f"{name} length at axis {axis}"
        )
        for axis, cell in enumerate(lengths.cells)
    )
    inferred = [axis for axis, size in enumerate(requested) if size == -1]
    if len(inferred) > 1:
        fail(f"{name} allows at most one inferred dimension")
    if any(size != -1 and not 1 <= size <= MAX_RASTER_ARRAY_AXIS
           for size in requested):
        fail(f"{name} axis lengths must be positive and no greater than 64, or -1")

    if inferred:
        axis = inferred[0]
        known_product = math.prod(size for size in requested if size != -1)
        if (known_product > MAX_RASTER_ARRAY_CELLS
                or input_cells % known_product != 0):
            fail(f"{name} inferred dimension must divide the input array cell count")
        inferred_size = input_cells // known_product
        if not 1 <= inferred_size <= MAX_RASTER_ARRAY_AXIS:
            fail(f"{name} inferred dimension is outside the supported range 1..64")
        shape = tuple(inferred_size if index == axis else size
                      for index, size in enumerate(requested))
    else:
        shape = requested

    output_cells = check_shape(shape)
    if output_cells != input_cells:
        fail(f"{name} output shape must preserve the input array cell count")

    # The row-major cells are reinterpreted without changing their values,
    # dtype casts, image metadata, or the input array's validity mask.
    charge_array(translator, output_cells + dimensions)
    return wrap_array_image(array.image, shape, array.cells, array.mask, array.name)


def invoke_raster_reshape(translator, name, arguments):
    """Evaluate the supported bounded Image.arrayReshape operation."""
    if name not in RASTER_RESHAPE_FUNCTIONS:
        fail(f"Unsupported raster array reshape operation: {name}")
    return _reshape(translator, arguments)
