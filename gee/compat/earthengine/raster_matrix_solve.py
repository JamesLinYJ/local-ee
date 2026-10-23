"""Finite per-pixel least-squares solve for fixed-shape raster arrays."""
from __future__ import annotations

import numpy as np

from .array_core import charge_array
from .ir import Pixel, const, fail
from .raster_array_core import (
    MAX_RASTER_ARRAY_CELLS,
    combined_mask,
    check_shape,
    wrap_array_image,
)
from .raster_array_precision import require_cast_cells
from .raster_array_values import _array, _result_image
from .raster_matrix_literals import literal_cells, scan_literal_cells


RASTER_MATRIX_FUNCTIONS = frozenset({"Image.matrixSolve"})
_MAX_EXACT_CONSTANT = 2**53


def _required(arguments, name, parameter):
    if parameter not in arguments:
        fail(f"{name} requires the {parameter} argument")
    return arguments[parameter]


def _top_cast_is_double(array):
    first = array.cells[0]
    return (isinstance(first, Pixel) and first.op == "to_double"
            and not first.boolean)


def _preflight(translator, name, m, n, k, literal_nodes, promote_double):
    # Reserve the solve, bounded literal handling, and output expression before
    # NumPy allocates a factorization or any pixel expressions are constructed.
    work = (
        8 * m * n * n + 4 * m * m * n + 3 * m * n + m * m
        + 2 * m * n * k + 2 * n * k + 32 + 2 * literal_nodes
    )
    if promote_double:
        # One shared typed constant per design coefficient marks every product
        # as Double without duplicating a cast for each response column.
        work += m * n
        # Reserve the constant-column scan and worst-case overflow guard,
        # centered response copy, differences, anchors, and adjustment.
        work += m * n + 6 * m * k + 8 * k + 8
    charge_array(translator, work)


def _solve(design, identity):
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        pseudo_inverse, _, rank, _ = np.linalg.lstsq(design, identity, rcond=None)
    return pseudo_inverse, rank


def _double_pseudoinverse(pseudo_inverse, shape, name):
    values = np.asarray(pseudo_inverse, dtype=np.float64)
    if values.shape != shape or not np.isfinite(values).all():
        fail(f"{name} must produce a finite Float64 pseudoinverse")
    if np.any(np.abs(values) > _MAX_EXACT_CONSTANT):
        fail(f"{name} Float64 pseudoinverse coefficients must fit the +/-2^53 constant range")
    return values


def _float32_pseudoinverse(pseudo_inverse, shape, name):
    with np.errstate(over="ignore", invalid="ignore"):
        values = np.asarray(pseudo_inverse, dtype=np.float32)
    if values.shape != shape or not np.isfinite(values).all():
        fail(f"{name} must produce a finite Float32 pseudoinverse")
    return values


def _double_solution_cells(pseudo_inverse, right, m, n, k):
    coefficients = tuple(
        Pixel("to_double", (const(float(pseudo_inverse[row, source_row]),),))
        for row in range(n)
        for source_row in range(m)
    )
    cells = []
    for row in range(n):
        for column in range(k):
            terms = [
                Pixel("multiply", (
                    coefficients[row * m + source_row],
                    right.cells[source_row * k + column],
                ))
                for source_row in range(m)
            ]
            result = terms[0]
            for term in terms[1:]:
                result = Pixel("add", (result, term))
            cells.append(result)
    return tuple(cells)


def _constant_predictor_column(values, m, n):
    """Find a nonzero constant column in the cast-evaluated literal design."""
    for column in range(n):
        constant = values[column]
        if constant != 0.0 and all(
                values[row * n + column] == constant for row in range(1, m)):
            return column, constant
    return None


def _double_centered_solution_cells(
        pseudo_inverse, right, m, n, k, constant_column, constant_value,
        right_cast):
    """Solve against RHS differences, then restore the constant predictor."""
    if right_cast == "to_double":
        anchors = tuple(right.cells[column] for column in range(k))
    else:
        # Preserve nested Float32 rounding, then promote just each shared
        # anchor; the subtraction inherits Double precision from that anchor.
        anchors = tuple(
            Pixel("to_double", (right.cells[column],)) for column in range(k)
        )

    # Scale magnitudes by 2^-1024, then compare with a value just below 0.5.
    # If any response value is too large, the zeroed anchor below preserves
    # the original P*y path and avoids an overflowing y-y0 subtraction.
    magnitude_scale = const(2.0 ** -1024)
    safe_limit = const(0.5 - 2.0 ** -53)
    guarded_anchors = []
    for column in range(k):
        magnitudes = [
            Pixel("absolute", (right.cells[row * k + column],))
            for row in range(m)
        ]
        largest = magnitudes[0]
        for magnitude in magnitudes[1:]:
            largest = Pixel("max2", (largest, magnitude))
        if right_cast != "to_double":
            largest = Pixel("to_double", (largest,))
        scaled = Pixel("multiply", (largest, magnitude_scale))
        safe = Pixel("lte", (scaled, safe_limit), True)
        enabled = Pixel("to_double", (safe,))
        guarded_anchors.append(Pixel("multiply", (anchors[column], enabled)))
    anchors = tuple(guarded_anchors)

    centered = tuple(
        Pixel("subtract", (
            right.cells[row * k + column], anchors[column],
        ))
        for row in range(m)
        for column in range(k)
    )
    coefficients = tuple(
        Pixel("to_double", (const(float(pseudo_inverse[row, source_row]),),))
        for row in range(n)
        for source_row in range(m)
    )

    inverse_constant = 1.0 / constant_value
    if np.isfinite(inverse_constant) and abs(inverse_constant) <= _MAX_EXACT_CONSTANT:
        scale = Pixel("to_double", (const(float(inverse_constant),),))
        adjustment = "multiply"
    else:
        # A small source constant may have a reciprocal outside the exact
        # constant range. Divide by the finite source value instead.
        scale = Pixel("to_double", (const(float(constant_value),),))
        adjustment = "divide"

    cells = []
    for row in range(n):
        for column in range(k):
            terms = [
                Pixel("multiply", (
                    coefficients[row * m + source_row],
                    centered[source_row * k + column],
                ))
                for source_row in range(m)
            ]
            result = terms[0]
            for term in terms[1:]:
                result = Pixel("add", (result, term))
            if row == constant_column:
                anchor_term = Pixel(adjustment, (anchors[column], scale))
                result = Pixel("add", (result, anchor_term))
            cells.append(result)
    return tuple(cells)


def _float32_solution_cells(pseudo_inverse, right, m, n, k):
    cells = []
    for row in range(n):
        for column in range(k):
            terms = [
                Pixel("multiply", (
                    const(float(pseudo_inverse[row, source_row])),
                    right.cells[source_row * k + column],
                ))
                for source_row in range(m)
            ]
            result = terms[0]
            for term in terms[1:]:
                result = Pixel("add", (result, term))
            cells.append(Pixel("to_float", (result,)))
    return tuple(cells)


def invoke_raster_matrix(translator, name, arguments):
    """Lower bounded raster ``Image.matrixSolve`` calls to pixel expressions."""
    if name not in RASTER_MATRIX_FUNCTIONS:
        fail(f"Unsupported raster matrix operation: {name}")
    translator.allowed(arguments, {"image1", "image2"})
    left = _array(_required(arguments, name, "image1"), "Image.matrixSolve image1")
    right = _array(_required(arguments, name, "image2"), "Image.matrixSolve image2")
    if len(left.shape) != 2 or len(right.shape) != 2:
        fail("Image.matrixSolve currently requires rank-2 RasterArrayImages")

    m, n = left.shape
    right_rows, k = right.shape
    if not 1 <= m <= 8 or not 1 <= n <= 4 or m < n:
        fail("Image.matrixSolve supports 1<=m<=8, 1<=n<=4, and m>=n")
    if right_rows != m or not 1 <= k <= 4:
        fail("Image.matrixSolve image2 must have shape (m,k), with 1<=k<=4")
    if len(left.cells) + len(right.cells) > MAX_RASTER_ARRAY_CELLS:
        fail("Image.matrixSolve input arrays exceed the shared 64-cell limit")
    check_shape((n, k))

    literal_nodes = scan_literal_cells(left.cells, name)
    promote_double = _top_cast_is_double(left) or _top_cast_is_double(right)
    _preflight(translator, name, m, n, k, literal_nodes, promote_double)

    left_cast = require_cast_cells(left, name, "image1")
    right_cast = require_cast_cells(right, name, "image2")
    promote_double = left_cast == "to_double" or right_cast == "to_double"
    design_values = literal_cells(left.cells, name)

    if promote_double:
        design = np.asarray(design_values, dtype=np.float64).reshape((m, n))
        constant_predictor = _constant_predictor_column(design_values, m, n)
        identity = np.eye(m, dtype=np.float64)
        try:
            pseudo_inverse, rank = _solve(design, identity)
        except np.linalg.LinAlgError:
            fail("Image.matrixSolve Float64 least-squares solve failed to converge")
        if rank < n:
            fail("Image.matrixSolve Float64 design matrix must have full column rank")
        pseudo_inverse = _double_pseudoinverse(pseudo_inverse, (n, m), name)
        if constant_predictor is None:
            cells = _double_solution_cells(pseudo_inverse, right, m, n, k)
        else:
            constant_column, constant_value = constant_predictor
            cells = _double_centered_solution_cells(
                pseudo_inverse, right, m, n, k, constant_column,
                constant_value, right_cast,
            )
    else:
        # Keep the established Float32 NumPy input, identity, pseudoinverse,
        # per-pixel expression and final output cast exactly as before.
        design = np.asarray(design_values, dtype=np.float32).reshape((m, n))
        identity = np.eye(m, dtype=np.float32)
        try:
            pseudo_inverse, rank = _solve(design, identity)
        except np.linalg.LinAlgError:
            fail("Image.matrixSolve Float32 least-squares solve failed to converge")
        if rank < n:
            fail("Image.matrixSolve Float32 design matrix must have full column rank")
        pseudo_inverse = _float32_pseudoinverse(pseudo_inverse, (n, m), name)
        cells = _float32_solution_cells(pseudo_inverse, right, m, n, k)

    mask = combined_mask(left.mask, right.mask)
    return wrap_array_image(
        _result_image(left, right), (n, k), cells, mask, left.name,
    )
