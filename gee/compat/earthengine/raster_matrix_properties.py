"""Bounded matrix layout and scalar properties for raster-array Images.

Trace and determinant use explicit local Float32 staging.  That keeps literal
pixel expressions and source-backed callbacks on the same rounding path; it is
a bounded implementation policy, not a claim of GEE numeric parity.
"""
from __future__ import annotations

from itertools import permutations
import math

from .array_core import charge_array
from .ir import Pixel, const, fail
from .raster_array_core import masked_scalar, wrap_array_image
from .raster_array_values import _array


RASTER_MATRIX_PROPERTY_FUNCTIONS = frozenset({
    "Image.matrixDiagonal",
    "Image.matrixToDiag",
    "Image.matrixTrace",
    "Image.matrixDeterminant",
})


def _required(arguments, name):
    if "value" not in arguments:
        fail(f"{name} requires the value argument")
    return arguments["value"]


def _matrix(translator, name, arguments):
    translator.allowed(arguments, {"value"})
    array = _array(_required(arguments, name), f"{name} value")
    if len(array.shape) != 2:
        fail(f"{name} requires a rank-2 RasterArrayImage")
    rows, columns = array.shape
    return array, rows, columns


def _require_float32_cells(array, name):
    if any(pixel.op != "to_float" or len(pixel.args) != 1
           or not isinstance(pixel.args[0], Pixel) or pixel.boolean
           for pixel in array.cells):
        fail(f"{name} requires explicit top-level toFloat() for every matrix cell")


def _float32(pixel):
    return Pixel("to_float", (pixel,))


def _diagonal(translator, name, arguments):
    array, rows, columns = _matrix(translator, name, arguments)
    length = min(rows, columns)
    charge_array(translator, len(array.cells) + length + 8)
    cells = tuple(array.cells[index * columns + index] for index in range(length))
    return wrap_array_image(array.image, (length, 1), cells, array.mask, array.name)


def _to_diagonal(translator, name, arguments):
    array, rows, columns = _matrix(translator, name, arguments)
    if columns != 1:
        fail(f"{name} requires a single-column matrix")
    if rows > 8:
        fail(f"{name} supports a single-column matrix with at most 8 rows")
    output_cells = rows * rows
    # Cover the output layout scan and both Pixels per off-diagonal Float32
    # zero, in addition to validating the input cell casts.
    charge_array(translator, len(array.cells) + 3 * output_cells + rows + 8)
    _require_float32_cells(array, name)
    cells = tuple(
        array.cells[row] if row == column else _float32(const(0))
        for row in range(rows)
        for column in range(rows)
    )
    return wrap_array_image(array.image, (rows, rows), cells, array.mask, array.name)


def _trace(translator, name, arguments):
    array, rows, columns = _matrix(translator, name, arguments)
    if rows != columns or not 1 <= rows <= 8:
        fail(f"{name} supports square matrices of size 1 through 8")
    charge_array(translator, len(array.cells) + 3 * rows + 8)
    _require_float32_cells(array, name)
    result = array.cells[0]
    for index in range(1, rows):
        result = _float32(Pixel("add", (result, array.cells[index * columns + index])))
    return masked_scalar(array, _float32(result), array.name)


def _inversion_parity(order):
    return sum(
        order[left] > order[right]
        for left in range(len(order))
        for right in range(left + 1, len(order))
    ) & 1


def _determinant(translator, name, arguments):
    array, rows, columns = _matrix(translator, name, arguments)
    if rows != columns or not 1 <= rows <= 4:
        fail(f"{name} supports square matrices of size 1 through 4")
    terms = math.factorial(rows)
    # Cover input checks, permutation indexing/parity comparisons, all
    # multiply/add stages and their explicit Float32 casts before creating IR.
    pair_checks = rows * (rows - 1) // 2
    per_term = 2 * (rows - 1) + pair_checks + rows + 2
    charge_array(translator, len(array.cells) + terms * per_term + 16)
    _require_float32_cells(array, name)

    result = None
    for order in permutations(range(rows)):
        product = array.cells[order[0]]
        for row in range(1, rows):
            product = _float32(Pixel(
                "multiply", (product, array.cells[row * columns + order[row]])
            ))
        if result is None:
            result = product
            continue
        operation = "subtract" if _inversion_parity(order) else "add"
        result = _float32(Pixel(operation, (result, product)))
    return masked_scalar(array, _float32(result), array.name)


def invoke_raster_matrix_property(translator, name, arguments):
    """Handle the four fixed-signature raster matrix property algorithms."""
    if name not in RASTER_MATRIX_PROPERTY_FUNCTIONS:
        fail(f"Unsupported raster matrix property operation: {name}")
    if not isinstance(arguments, dict):
        fail("Raster matrix algorithm arguments must be an object")
    if name == "Image.matrixDiagonal":
        return _diagonal(translator, name, arguments)
    if name == "Image.matrixToDiag":
        return _to_diagonal(translator, name, arguments)
    if name == "Image.matrixTrace":
        return _trace(translator, name, arguments)
    return _determinant(translator, name, arguments)
