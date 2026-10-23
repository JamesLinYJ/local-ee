"""Fixed-shape raster Cholesky and LU factorization lowering."""
from __future__ import annotations

from .array_core import charge_array
from .ir import Image, Pixel, const, fail
from .raster_array_bands import wrap_array_bands
from .raster_array_core import (
    MAX_RASTER_ARRAY_CELLS,
    wrap_array_image,
)
from .raster_array_precision import require_cast_cells
from .raster_array_values import _array


RASTER_MATRIX_DECOMPOSITION_FUNCTIONS = frozenset({
    "Image.matrixCholeskyDecomposition",
    "Image.matrixLUDecomposition",
})


def _metadata_image(array):
    image = array.image
    return Image(
        [], dict(image.props), image.source, image.mapped, image.inherit_props,
        image.copied_props, image.footprint, image.footprint_is_absolute,
    )


def _required(arguments, name):
    if "image" not in arguments:
        fail(f"{name} requires the image argument")
    return arguments["image"]


def _constant_cells(values, dtype):
    return tuple(Pixel(dtype, (const(value),)) for value in values)


def _arrays(translator, array, op, dtype, producer=None, folded=None):
    n = array.shape[0]
    factor_names = ("L", "U", "P") if op == "lu" else ("L",)
    factors = []
    offset = 0
    image = array.image if op == "cholesky" else _metadata_image(array)
    for factor_index, name in enumerate(factor_names):
        if folded is not None:
            cells = _constant_cells(folded[factor_index], dtype)
        else:
            count = n * n
            cells = tuple(
                Pixel(dtype, (Pixel("matrix_element", (producer, index)),))
                for index in range(offset, offset + count)
            )
        factors.append(wrap_array_image(
            image, (n, n), cells, array.mask, name,
        ))
        offset += n * n
    if op == "cholesky":
        return factors[0]
    return wrap_array_bands(translator, image, factors)


def _build_dynamic(translator, name, op, array, dtype, values):
    from .raster_matrix_native import _constant_descriptor
    from gee.matrix_values_spec import prepare_matrix_values_spec

    dynamic = []
    operands = []
    for pixel, value in zip(array.cells, values):
        if value is not None:
            operands.append(_constant_descriptor(value))
        else:
            dynamic.append(pixel)
            operands.append({"band": len(dynamic) - 1})
    try:
        spec = prepare_matrix_values_spec(op, array.shape[0], array.shape[1], 0, operands)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        fail(f"{name} native matrix specification is invalid: {error}")
    output_count = len(array.cells) * (3 if op == "lu" else 1)
    charge_array(
        translator,
        2 * len(spec) + 4 * len(array.cells) + 3 * output_count + 16,
    )
    producer = Pixel("matrix_values", (tuple(dynamic), spec))
    return _arrays(translator, array, op, dtype, producer=producer)


def invoke_raster_matrix_decomposition(translator, name, arguments):
    """Lower one matrix factorization to fixed array-valued output bands."""
    if name not in RASTER_MATRIX_DECOMPOSITION_FUNCTIONS:
        fail(f"Unsupported raster matrix decomposition: {name}")
    translator.allowed(arguments, {"image"})
    array = _array(_required(arguments, name), f"{name} image")
    if len(array.shape) != 2:
        fail(f"{name} requires a rank-2 RasterArrayImage")
    rows, cols = array.shape
    if rows != cols:
        fail(f"{name} requires a square matrix")
    if not 1 <= rows <= 8:
        fail(f"{name} supports matrix axes in1..8")
    op = "cholesky" if name.endswith("CholeskyDecomposition") else "lu"
    output_count = rows * cols * (3 if op == "lu" else 1)
    if output_count > MAX_RASTER_ARRAY_CELLS:
        fail(f"{name} combined factor outputs exceed the shared64-cell limit")

    charge_array(translator, 2 * len(array.cells) + 8)
    dtype = require_cast_cells(array, name, "matrix")
    from .raster_matrix_native import matrix_literal_values

    values = tuple(matrix_literal_values(translator, array.cells, name))
    if all(value is not None for value in values):
        if array.mask.op != "constant" or array.mask.args != (True,):
            fail(f"{name} cannot fold a masked source-free constant matrix")
        from .raster_matrix_factor_constants import fold_constant_factors

        folded = fold_constant_factors(translator, name, op, rows, cols, values, dtype)
        return _arrays(translator, array, op, dtype, folded=folded)
    return _build_dynamic(translator, name, op, array, dtype, values)
