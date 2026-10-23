"""Shared IR helpers for bounded native per-pixel matrix operations."""
from __future__ import annotations

import math

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


RASTER_MATRIX_NATIVE_FUNCTIONS = frozenset({
    "Image.matrixInverse",
    "Image.matrixPseudoInverse",
})
_CASTS = frozenset({"to_float", "to_double"})
_MAX_LITERAL_NODES = 500


def _cast_chain_is_literal(translator, pixel, name, known):
    """Classify a top-cast cell without treating malformed/cyclic input as dynamic."""
    active = set()
    visited = []
    node = pixel
    while isinstance(node, Pixel) and node.op in _CASTS:
        cached = known.get(id(node))
        if cached is not None and cached[0] is node:
            for value in visited:
                known[id(value)] = (value, cached[1])
            return cached[1]
        charge_array(translator, 1)
        identity = id(node)
        if identity in active:
            fail(f"{name} coefficients cannot contain cyclic Pixel expressions")
        active.add(identity)
        visited.append(node)
        if len(known) + len(active) > _MAX_LITERAL_NODES:
            fail(f"{name} constant coefficients exceed the static expression budget")
        if type(node.args) is not tuple or len(node.args) != 1 or node.boolean:
            fail(f"{name} coefficients allow only unary numeric casts")
        child = node.args[0]
        if not isinstance(child, Pixel):
            fail(f"{name} coefficients require Pixel-valued cast inputs")
        node = child
    if not isinstance(node, Pixel) or node.op != "constant":
        for value in visited:
            known[id(value)] = (value, False)
        return False
    charge_array(translator, 1)
    if type(node.args) is not tuple or len(node.args) != 1 or node.boolean:
        fail(f"{name} coefficients must be finite non-boolean constants")
    if id(node) not in known and len(known) + len(active) >= _MAX_LITERAL_NODES:
        fail(f"{name} constant coefficients exceed the static expression budget")
    for value in visited:
        known[id(value)] = (value, True)
    known[id(node)] = (node, True)
    return True


def matrix_literal_values(translator, cells, name):
    """Return cast-evaluated literals or None for actual pixel expressions.

    The caller first enforces one explicit top-level cast per input array.
    Cast-chain cycles, malformed casts, non-finite constants and static-work
    overflow stay errors; only a well-formed non-constant Pixel is dynamic.
    """
    if type(cells) is not tuple or not cells:
        fail(f"{name} requires nonempty matrix cells")
    charge_array(translator, 2 * len(cells) + 4)
    known = {}
    literal = []
    literal_flags = []
    for pixel in cells:
        if _cast_chain_is_literal(translator, pixel, name, known):
            literal.append(pixel)
            literal_flags.append(True)
        else:
            literal_flags.append(False)
    literal_nodes = scan_literal_cells(tuple(literal), name)
    charge_array(translator, literal_nodes + 2 * len(cells))
    values = literal_cells(tuple(literal), name) if literal else ()
    results = [None] * len(cells)
    for index, value in zip((i for i, marker in enumerate(literal_flags) if marker), values):
        results[index] = value
    return tuple(results)


def _constant_descriptor(value):
    from gee.integer_values_spec import constant_operand

    try:
        return constant_operand(value)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        fail(f"Raster matrix constant is invalid: {error}")


def native_matrix_result(
        translator, api_name, op, left_value, right_value=None, *,
        literal_values=None):
    """Build one shared producer and row-major typed output component Pixels."""
    left = _array(left_value, f"{api_name} value" if right_value is None else f"{api_name} image1")
    right = None if right_value is None else _array(right_value, f"{api_name} image2")
    if len(left.shape) != 2 or right is not None and len(right.shape) != 2:
        fail(f"{api_name} requires rank-2 RasterArrayImages")
    rows, cols = left.shape
    left_dtype = require_cast_cells(left, api_name, "matrix")
    inputs = list(left.cells)
    dtype = left_dtype
    rhs_cols = 0
    if op == "solve":
        if right is None:
            fail("Image.matrixSolve requires image1 and image2")
        right_dtype = require_cast_cells(right, api_name, "image2")
        if right.shape[0] != rows:
            fail("Image.matrixSolve image2 must have the same row count as image1")
        rhs_cols = right.shape[1]
        inputs.extend(right.cells)
        if right_dtype == "to_double":
            dtype = "to_double"
    if (not 1 <= rows <= 8 or not 1 <= cols <= 8
            or op == "inverse" and rows != cols):
        if op == "inverse":
            fail("Image.matrixInverse requires a square matrix with axes in1..8")
        fail(f"{api_name} supports rank-2 matrices with axes in1..8")
    if op == "solve" and not 1 <= rhs_cols <= 8:
        fail("Image.matrixSolve supports1..8 right-hand-side columns")
    output_shape = (cols, rhs_cols if op == "solve" else rows)
    if (len(inputs) > MAX_RASTER_ARRAY_CELLS
            or check_shape(output_shape) > MAX_RASTER_ARRAY_CELLS):
        fail(f"{api_name} input and output arrays must each fit the shared64-cell limit")

    if literal_values is None:
        literal_values = matrix_literal_values(translator, tuple(inputs), api_name)
    elif (type(literal_values) is not tuple or len(literal_values) != len(inputs)
          or any(value is not None and type(value) not in (int, float)
                 for value in literal_values)):
        fail(f"{api_name} native matrix literal scan is malformed")
    dynamic = []
    operands = []
    # Inspect every input cell before constructing a spec or output expression.
    # A dynamic operand receives one unique, ordered band reference, even when
    # the same Pixel object appears in more than one matrix position.
    for pixel, value in zip(inputs, literal_values):
        if value is not None:
            operands.append(_constant_descriptor(value))
        else:
            dynamic.append(pixel)
            operands.append({"band": len(dynamic) - 1})
    if not dynamic:
        fail(f"{api_name} needs a real raster source for native matrix execution")

    from gee.matrix_values_spec import prepare_matrix_values_spec

    try:
        spec = prepare_matrix_values_spec(op, rows, cols, rhs_cols, operands)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        fail(f"{api_name} native matrix specification is invalid: {error}")
    output_count = check_shape(output_shape)
    # Reserve copied descriptors/spec bytes, the shared producer tuple and all
    # component wrappers before the Pixel graph can merge any source cubes.
    charge_array(translator, 2 * len(spec) + 4 * len(inputs) + 3 * output_count + 16)

    from .raster_array_core import combined_mask

    mask = left.mask if right is None else combined_mask(left.mask, right.mask)
    image = left.image if right is None else _result_image(left, right)
    producer = Pixel("matrix_values", (tuple(dynamic), spec))
    cells = tuple(
        Pixel(dtype, (Pixel("matrix_element", (producer, index)),))
        for index in range(output_count)
    )
    return wrap_array_image(image, output_shape, cells, mask, left.name)


def fold_constant_matrix(translator, api_name, op, rows, cols, values, dtype):
    """Fold fully valid constants with the native scale/rank cutoff policy."""
    import numpy as np

    if type(values) is not tuple or len(values) != rows * cols:
        fail(f"{api_name} static input shape is malformed")
    charge_array(translator, 3 * rows * cols + 16 + rows * cols * cols + 8 * rows * rows)
    matrix_dtype = np.float64 if dtype == "to_double" else np.float32
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        # Array casts happen before the native kernel widens its working cells
        # to Float64. Preserve that input rounding and use the same normalized
        # matrix and Commons-Math numerical-rank cutoff as the process.
        matrix = np.asarray(values, dtype=matrix_dtype).astype(np.float64).reshape((rows, cols))
        scale = float(np.max(np.abs(matrix)))
        if not np.isfinite(matrix).all() or not math.isfinite(scale):
            fail(f"{api_name} constant matrix must contain finite cast values")
        if scale == 0.0:
            if op == "inverse":
                fail(f"{api_name} zero constant matrix is singular")
            result = np.zeros((cols, rows), dtype=np.float64)
        else:
            normalized = matrix / scale
            try:
                u, singular, vh = np.linalg.svd(normalized, full_matrices=False)
            except np.linalg.LinAlgError as error:
                fail(f"{api_name} constant matrix decomposition failed: {error}")
            # Commons Math evaluates max(m,n) * s_max * EPS. Because the
            # nonzero input is normalized to max-absolute 1, s_max >= 1 and
            # this first term also dominates any sqrt(SAFE_MIN) threshold floor.
            cutoff = (max(rows, cols) * float(singular[0])) * np.finfo(np.float64).eps
            rank = int(np.count_nonzero(singular > cutoff))
            if op == "inverse" and rank < cols:
                fail(f"{api_name} constant matrix is singular at the native rank cutoff")
            if rank == 0:
                result = np.zeros((cols, rows), dtype=np.float64)
            else:
                normalized_pseudo = (vh[:rank, :].T / singular[:rank]) @ u[:, :rank].T
                result = normalized_pseudo / scale
    if result.shape != (cols, rows):
        fail(f"{api_name} constant matrix produced an invalid output shape")
    if not np.isfinite(result).all():
        fail(f"{api_name} constant matrix must produce finite output values")
    if dtype == "to_float":
        with np.errstate(over="ignore", invalid="ignore"):
            result = result.astype(np.float32)
        if not np.isfinite(result).all():
            fail(f"{api_name} constant result must be finite after the Float32 output cast")
    values_out = tuple(
        Pixel(dtype, (const(float(value)),)) for value in result.flat
    )
    return tuple(values_out), tuple(result.shape)
