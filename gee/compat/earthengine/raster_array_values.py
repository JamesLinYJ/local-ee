"""Fixed-shape raster-array operations over the shared Earth Engine IR."""
from __future__ import annotations

import numpy as np

from .array_core import StaticArray, charge_array
from .ir import Image, Pixel, as_image, const, fail, integer
from .raster_array_core import (
    RasterArrayImage,
    check_shape,
    combined_mask,
    masked_scalar,
    wrap_array_image,
)


_ARITHMETIC = {
    "Image.add": "add",
    "Image.subtract": "subtract",
    "Image.multiply": "multiply",
    "Image.divide": "divide",
}

RASTER_ARRAY_VALUE_FUNCTIONS = frozenset({
    "Image.constant",
    "Image.toArray",
    "Image.matrixMultiply",
    "Image.arrayLength",
    "Image.arrayLengths",
}) | frozenset(_ARITHMETIC)


def _array(value, label: str = "input") -> RasterArrayImage:
    if not isinstance(value, RasterArrayImage):
        fail(f"{label} must be a single-band fixed-shape RasterArrayImage")
    count = check_shape(value.shape)
    if (not isinstance(value.image, Image) or not isinstance(value.cells, tuple)
            or len(value.cells) != count or any(not isinstance(p, Pixel) for p in value.cells)):
        fail("Malformed RasterArrayImage layout")
    if (not isinstance(value.mask, Pixel)
            or not (value.mask.boolean or value.mask.op == "constant" and value.mask.args == (None,))
            or not isinstance(value.name, str)):
        fail("Malformed RasterArrayImage mask or band name")
    return value


def _contains_static_array(value) -> bool:
    if isinstance(value, StaticArray):
        return True
    return isinstance(value, (list, tuple)) and any(_contains_static_array(item) for item in value)


def _constant_array(translator, value: StaticArray) -> RasterArrayImage:
    data = np.asarray(value.data)
    shape = tuple(data.shape)
    count = check_shape(shape)
    if data.dtype.kind not in {"i", "u", "f"} or not np.isfinite(data).all():
        fail("Image.constant StaticArray values must be finite real numbers")
    if data.dtype.kind in {"i", "u"} and np.any((data < -(2**53)) | (data > 2**53)):
        fail("Image.constant StaticArray integers must fit the exact Float64 domain")
    charge_array(translator, count)
    cells = tuple(const(item.item()) for item in data.flat)
    return wrap_array_image(Image([], {}), shape, cells, const(True), "constant")


def _to_array(translator, arguments) -> RasterArrayImage:
    translator.allowed(arguments, {"image", "axis"})
    value = arguments["image"]
    axis = integer(arguments.get("axis", 0), "Image.toArray axis", 0)
    if isinstance(value, RasterArrayImage):
        array = _array(value)
        rank = len(array.shape)
        if axis > rank:
            fail("Image.toArray axis must not exceed the array rank")
        if axis < rank:
            charge_array(translator, max(1, len(array.cells)))
            return array
        shape = (*array.shape, 1)
        count = check_shape(shape)
        charge_array(translator, count + rank)
        return wrap_array_image(array.image, shape, array.cells, array.mask, array.name)

    image = as_image(value)
    if not image.bands:
        fail("Image.toArray requires at least one scalar input band")
    shape = (len(image.bands),)
    count = check_shape(shape)
    if axis != 0:
        fail("Image.toArray axis for scalar input bands must be 0")
    charge_array(translator, count * 2)
    cells = tuple(pixel for _, pixel in image.bands)
    valid = tuple(
        Pixel("not", (Pixel("is_nodata", (pixel,), True),), True)
        for pixel in cells
    )
    return wrap_array_image(image, shape, cells, combined_mask(*valid), "array")


def _result_image(left: RasterArrayImage, right: RasterArrayImage) -> Image:
    return Image(
        bands=list(left.image.bands),
        props=dict(left.image.props),
        source=left.image.source or right.image.source,
        mapped=left.image.mapped or right.image.mapped,
        inherit_props=left.image.inherit_props,
        copied_props=left.image.copied_props,
        footprint=left.image.footprint,
        footprint_is_absolute=left.image.footprint_is_absolute,
    )


def _binary_arrays(translator, name, arguments) -> RasterArrayImage:
    translator.allowed(arguments, {"image1", "image2"})
    left = _array(arguments["image1"], "Image.image1")
    right = _array(arguments["image2"], "Image.image2")
    if left.shape != right.shape:
        fail(f"{name} requires RasterArrayImages with identical shapes")
    count = check_shape(left.shape)
    charge_array(translator, count * 2)
    mask = combined_mask(left.mask, right.mask)
    cells = tuple(Pixel(_ARITHMETIC[name], (a, b)) for a, b in zip(left.cells, right.cells))
    return wrap_array_image(_result_image(left, right), left.shape, cells, mask, left.name)


def _matrix_multiply(translator, arguments) -> RasterArrayImage:
    translator.allowed(arguments, {"image1", "image2"})
    left = _array(arguments["image1"], "Image.matrixMultiply image1")
    right = _array(arguments["image2"], "Image.matrixMultiply image2")
    if len(left.shape) != 2 or len(right.shape) != 2:
        fail("Image.matrixMultiply requires rank-2 RasterArrayImages")
    rows, inner = left.shape
    right_inner, columns = right.shape
    if inner != right_inner:
        fail("Image.matrixMultiply inner dimensions must match")
    shape = (rows, columns)
    count = check_shape(shape)
    charge_array(translator, count * (2 * inner - 1))
    mask = combined_mask(left.mask, right.mask)
    cells = []
    for row in range(rows):
        for column in range(columns):
            products = [
                Pixel("multiply", (left.cells[row * inner + k], right.cells[k * columns + column]))
                for k in range(inner)
            ]
            result = products[0]
            for product in products[1:]:
                result = Pixel("add", (result, product))
            cells.append(result)
    return wrap_array_image(
        _result_image(left, right), shape, tuple(cells), mask, left.name,
    )


def _array_length(translator, arguments) -> Image:
    translator.allowed(arguments, {"input", "axis"})
    array = _array(arguments["input"])
    if "axis" not in arguments:
        fail("Image.arrayLength requires an axis")
    axis = integer(arguments["axis"], "Image.arrayLength axis", 0)
    if axis >= len(array.shape):
        fail("Image.arrayLength axis is outside the array rank")
    check_shape(array.shape)
    charge_array(translator, 1)
    return masked_scalar(array, const(array.shape[axis]))


def _array_lengths(translator, arguments) -> RasterArrayImage:
    translator.allowed(arguments, {"input"})
    array = _array(arguments["input"])
    check_shape(array.shape)
    rank = len(array.shape)
    if rank == 0:
        fail("Image.arrayLengths cannot represent the lengths of a rank-0 array")
    shape = (rank,)
    count = check_shape(shape)
    charge_array(translator, count + len(array.cells))
    cells = tuple(const(length) for length in array.shape)
    return wrap_array_image(array.image, shape, cells, array.mask, array.name)


def invoke_raster_value(translator, name, arguments):
    """Handle the explicitly supported fixed-shape raster-array algorithms."""
    if name not in RASTER_ARRAY_VALUE_FUNCTIONS:
        fail(f"Unsupported raster Array operation: {name}")

    if name == "Image.constant":
        translator.allowed(arguments, {"value"})
        value = arguments["value"]
        if isinstance(value, StaticArray):
            return _constant_array(translator, value)
        if _contains_static_array(value) or isinstance(value, (list, tuple)) and any(
            isinstance(item, (list, tuple)) for item in value
        ):
            fail("Image.constant accepts one StaticArray; lists of arrays are unsupported")
        return as_image(value)

    if name == "Image.toArray":
        return _to_array(translator, arguments)
    if name == "Image.matrixMultiply":
        return _matrix_multiply(translator, arguments)
    if name == "Image.arrayLength":
        return _array_length(translator, arguments)
    if name == "Image.arrayLengths":
        return _array_lengths(translator, arguments)

    # Preserve existing scalar Image behavior when dispatch routes these names
    # here, while requiring both operands for the new array behavior.
    if name in _ARITHMETIC:
        if any(isinstance(arguments.get(key), RasterArrayImage) for key in ("image1", "image2")):
            return _binary_arrays(translator, name, arguments)
        from .image_ops import invoke_image

        return invoke_image(translator, name, arguments)

    fail(f"Unsupported raster Array operation: {name}")
