"""Bounded matrix layout and scalar properties for raster-array Images.

Trace, determinant, and the scaled Frobenius norm use explicit local Float32
or Float64 staging so literals and source-backed values share one rounding
path. This is a bounded implementation policy, not a claim of GEE numeric
parity.
"""
from __future__ import annotations

from itertools import permutations
import math

from .array_core import charge_array
from .ir import Pixel, const, fail
from .raster_array_core import masked_scalar, wrap_array_image
from .raster_array_precision import require_cast_cells
from .raster_array_values import _array


RASTER_MATRIX_PROPERTY_FUNCTIONS = frozenset({
    "Image.matrixDiagonal",
    "Image.matrixToDiag",
    "Image.matrixTrace",
    "Image.matrixDeterminant",
    "Image.matrixFnorm",
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


def _cast(dtype, pixel):
    return Pixel(dtype, (pixel,))


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
    # A Double zero depends on the first input cell so it keeps that cell's
    # NoData/Infinity behavior while abs canonicalizes negative zero. Each
    # arithmetic stage gets an explicit typed cast, and the expression is
    # shared across all off-diagonal cells.
    first_is_double = bool(array.cells and array.cells[0].op == "to_double")
    zero_count = output_cells - rows
    extra_zero_work = 3 if first_is_double and zero_count else 0
    # Cover the output layout scan, typed zero construction/casts, and input
    # cell validation. The additional shared Double zero stages are charged
    # before their Pixels are constructed.
    charge_array(
        translator,
        len(array.cells) + 3 * output_cells + rows + 8 + extra_zero_work,
    )
    dtype = require_cast_cells(array, name, "matrix")
    double_zero = None
    if dtype == "to_double" and zero_count:
        magnitude = _cast(dtype, Pixel("absolute", (array.cells[0],)))
        double_zero = _cast(dtype, Pixel("multiply", (magnitude, const(0))))

    cells = tuple(
        array.cells[row] if row == column else (
            double_zero if double_zero is not None else _cast(dtype, const(0))
        )
        for row in range(rows)
        for column in range(rows)
    )
    return wrap_array_image(array.image, (rows, rows), cells, array.mask, array.name)


def _trace(translator, name, arguments):
    array, rows, columns = _matrix(translator, name, arguments)
    if rows != columns or not 1 <= rows <= 8:
        fail(f"{name} supports square matrices of size 1 through 8")
    charge_array(translator, len(array.cells) + 3 * rows + 8)
    dtype = require_cast_cells(array, name, "matrix")
    result = array.cells[0]
    for index in range(1, rows):
        result = _cast(dtype, Pixel("add", (result, array.cells[index * columns + index])))
    return masked_scalar(array, _cast(dtype, result), array.name)


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
    # multiply/add stages and their explicit typed casts before creating IR.
    pair_checks = rows * (rows - 1) // 2
    per_term = 2 * (rows - 1) + pair_checks + rows + 2
    charge_array(translator, len(array.cells) + terms * per_term + 16)
    dtype = require_cast_cells(array, name, "matrix")

    result = None
    for order in permutations(range(rows)):
        product = array.cells[order[0]]
        for row in range(1, rows):
            product = _cast(dtype, Pixel(
                "multiply", (product, array.cells[row * columns + order[row]])
            ))
        if result is None:
            result = product
            continue
        operation = "subtract" if _inversion_parity(order) else "add"
        result = _cast(dtype, Pixel(operation, (result, product)))
    return masked_scalar(array, _cast(dtype, result), array.name)


def _frobenius_norm(translator, name, arguments):
    array, rows, columns = _matrix(translator, name, arguments)
    if rows < 1 or columns < 1:
        fail(f"{name} requires a nonempty rank-2 array")
    # Each cell contributes an absolute value, ratio, and square; the maximum,
    # sum, square root, final scaling, and explicit casts are also charged.
    charge_array(translator, 14 * len(array.cells) + 16)
    dtype = require_cast_cells(array, name, "matrix")

    magnitudes = [
        _cast(dtype, Pixel("absolute", (pixel,))) for pixel in array.cells
    ]
    scale = magnitudes[0]
    for magnitude in magnitudes[1:]:
        scale = _cast(dtype, Pixel("max2", (scale, magnitude)))

    ratios = [
        _cast(dtype, Pixel("divide", (pixel, scale))) for pixel in array.cells
    ]
    squares = [
        _cast(dtype, Pixel("multiply", (ratio, ratio))) for ratio in ratios
    ]
    total = squares[0]
    for square in squares[1:]:
        total = _cast(dtype, Pixel("add", (total, square)))
    root = _cast(dtype, Pixel("sqrt", (total,)))
    result = _cast(dtype, Pixel("multiply", (scale, root)))
    return masked_scalar(array, result, array.name)


def invoke_raster_matrix_property(translator, name, arguments):
    """Handle the five fixed-signature raster matrix property algorithms."""
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
    if name == "Image.matrixDeterminant":
        return _determinant(translator, name, arguments)
    return _frobenius_norm(translator, name, arguments)
