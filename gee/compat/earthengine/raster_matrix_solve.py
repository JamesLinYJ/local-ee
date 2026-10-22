"""Finite per-pixel least-squares solve for fixed-shape raster arrays.

The design coefficients are evaluated after their explicit Float32 cast chain.
NumPy's Float32 ``lstsq(..., rcond=None)`` rank cutoff and local output rounding
are bounded policies, not evidence of EJML or GEE numerical parity.
"""
from __future__ import annotations

import math
import struct

import numpy as np

from .array_core import charge_array
from .ir import Pixel, const, fail
from .raster_array_core import (
    MAX_RASTER_ARRAY_CELLS,
    combined_mask,
    check_shape,
    wrap_array_image,
)
from .raster_array_values import _array, _result_image


RASTER_MATRIX_FUNCTIONS = frozenset({"Image.matrixSolve"})


def _required(arguments, name, parameter):
    if parameter not in arguments:
        fail(f"{name} requires the {parameter} argument")
    return arguments[parameter]


def _is_float32_cell(pixel):
    return (isinstance(pixel, Pixel) and pixel.op == "to_float"
            and len(pixel.args) == 1 and isinstance(pixel.args[0], Pixel)
            and not pixel.boolean)


def _scan_constant_cell(pixel, seen_nodes, name):
    """Validate a cast-only literal chain and return newly visited node count."""
    if not _is_float32_cell(pixel):
        fail(f"{name} cells must each have an explicit top-level toFloat()")
    active = set()
    node = pixel
    new_nodes = 0
    while isinstance(node, Pixel) and node.op in {"to_float", "to_double"}:
        if id(node) in active:
            fail(f"{name} coefficients cannot contain cyclic Pixel expressions")
        if id(node) in seen_nodes:
            seen_nodes.update(active)
            if len(seen_nodes) > 500:
                fail(f"{name} constant coefficients exceed the static expression budget")
            return len(active)
        if len(node.args) != 1 or node.boolean:
            fail(f"{name} coefficients allow only unary numeric casts")
        active.add(id(node))
        new_nodes += 1
        node = node.args[0]
    if not isinstance(node, Pixel) or node.op != "constant" or len(node.args) != 1:
        fail(f"{name} coefficients must be literal constants with optional casts")
    leaf_is_new = id(node) not in seen_nodes
    if leaf_is_new:
        if node.boolean or type(node.args[0]) not in (int, float):
            fail(f"{name} coefficients must be finite non-boolean numbers")
        new_nodes += 1
    seen_nodes.update(active)
    seen_nodes.add(id(node))
    if len(seen_nodes) > 500:
        fail(f"{name} constant coefficients exceed the static expression budget")
    return new_nodes


def _float32(value, name):
    if type(value) not in (int, float):
        fail(f"{name} coefficients must be finite non-boolean numbers")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        fail(f"{name} coefficients must fit the Float64 domain")
    if not math.isfinite(number):
        fail(f"{name} coefficients must be finite")
    try:
        result = struct.unpack("!f", struct.pack("!f", number))[0]
    except (OverflowError, struct.error):
        fail(f"{name} coefficients overflow Float32")
    if not math.isfinite(result):
        fail(f"{name} coefficients overflow Float32")
    return result


def _literal_float32_cell(pixel, name, memo):
    casts = []
    seen = set()
    node = pixel
    cached = False
    number = None
    while isinstance(node, Pixel) and node.op in {"to_float", "to_double"}:
        if id(node) in seen:
            fail(f"{name} coefficients cannot contain cyclic Pixel expressions")
        if len(node.args) != 1 or node.boolean:
            fail(f"{name} coefficients allow only unary numeric casts")
        previous = memo.get(id(node))
        if previous is not None and previous[0] is node:
            number = previous[1]
            cached = True
            break
        seen.add(id(node))
        casts.append(node)
        node = node.args[0]
    if not cached:
        if (not isinstance(node, Pixel) or node.op != "constant" or len(node.args) != 1
                or node.boolean):
            fail(f"{name} coefficients must be literal constants with optional casts")
        previous = memo.get(id(node))
        if previous is not None and previous[0] is node:
            number = previous[1]
        else:
            value = node.args[0]
            if type(value) not in (int, float):
                fail(f"{name} coefficients must be finite non-boolean numbers")
            try:
                number = float(value)
            except (OverflowError, TypeError, ValueError):
                fail(f"{name} coefficients must fit the Float64 domain")
            if not math.isfinite(number):
                fail(f"{name} coefficients must be finite")
            memo[id(node)] = (node, number)
    for cast_pixel in reversed(casts):
        if cast_pixel.op == "to_float":
            number = _float32(number, name)
        else:
            number = float(number)
            if not math.isfinite(number):
                fail(f"{name} coefficients must remain finite after toDouble()")
        memo[id(cast_pixel)] = (cast_pixel, number)
    return number


def _preflight(translator, name, m, n, k, literal_nodes):
    # Includes the least-squares kernel, Float32 copies, literal-chain scan,
    # and bounded Pixel multiplication/addition/cast output construction.
    work = (
        8 * m * n * n + 4 * m * m * n + 3 * m * n + m * m
        + 2 * m * n * k + 2 * n * k + 32 + 2 * literal_nodes
    )
    charge_array(translator, work)


def invoke_raster_matrix(translator, name, arguments):
    """Lower an array-valued Image.matrixSolve to bounded pixel expressions."""
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

    constant_nodes = set()
    literal_nodes = 0
    for pixel in left.cells:
        literal_nodes += _scan_constant_cell(pixel, constant_nodes, name)
    for pixel in right.cells:
        if not _is_float32_cell(pixel):
            fail("Image.matrixSolve image2 cells require explicit top-level toFloat()")

    _preflight(translator, name, m, n, k, literal_nodes)

    try:
        literal_cache = {}
        design_values = [
            _literal_float32_cell(pixel, name, literal_cache) for pixel in left.cells
        ]
        design = np.asarray(design_values, dtype=np.float32).reshape((m, n))
        identity = np.eye(m, dtype=np.float32)
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            pseudo_inverse, _, rank, _ = np.linalg.lstsq(design, identity, rcond=None)
    except np.linalg.LinAlgError:
        fail("Image.matrixSolve Float32 least-squares solve failed to converge")
    if rank < n:
        fail("Image.matrixSolve Float32 design matrix must have full column rank")
    with np.errstate(over="ignore", invalid="ignore"):
        pseudo_inverse = np.asarray(pseudo_inverse, dtype=np.float32)
    if pseudo_inverse.shape != (n, m) or not np.isfinite(pseudo_inverse).all():
        fail("Image.matrixSolve must produce a finite Float32 pseudoinverse")

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

    mask = combined_mask(left.mask, right.mask)
    return wrap_array_image(
        _result_image(left, right), (n, k), tuple(cells), mask, left.name,
    )
