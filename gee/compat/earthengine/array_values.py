"""Bounded static EE arrays; raster array pixels and explicit PixelTypes reject."""
from __future__ import annotations

import math

import numpy as np

from .ir import fail, integer
from .array_core import (
    MAX_ARRAY_CELLS, MAX_ARRAY_RANK, MAX_ARRAY_WORK, StaticArray,
    charge_array as _charge, check_array_values as _shape,
    require_array as _array, require_matrix as _matrix, wrap_array as _wrap,
)
from .array_arithmetic import ARRAY_ARITHMETIC_FUNCTIONS, invoke_arithmetic
from .array_reductions import ARRAY_REDUCTION_FUNCTIONS, invoke_reduction
from .array_layout import ARRAY_LAYOUT_FUNCTIONS, invoke_layout
from .array_matrix_extra import ARRAY_MATRIX_FUNCTIONS, invoke_matrix_extra
from .array_decompositions import ARRAY_DECOMPOSITION_FUNCTIONS, invoke_decomposition

ARRAY_FUNCTIONS = frozenset({
    "Array", "Array.get", "Array.length", "Array.toList", "Array.reshape",
    "Array.transpose", "Array.matrixTranspose", "Array.matrixMultiply",
    "Array.matrixInverse", "Array.matrixSolve", "Array.matrixPseudoInverse",
}) | ARRAY_ARITHMETIC_FUNCTIONS | ARRAY_REDUCTION_FUNCTIONS | ARRAY_LAYOUT_FUNCTIONS | ARRAY_MATRIX_FUNCTIONS | ARRAY_DECOMPOSITION_FUNCTIONS


def _axes(arguments, array):
    axes = [integer(arguments.get(key, default), "Array axis", 0)
            for key, default in (("axis1", 0), ("axis2", 1))]
    if any(axis >= array.ndim for axis in axes):
        fail("Array transpose axis is outside the array rank")
    return axes


def _reshape(translator, array, shape):
    shape = _array(shape)
    if shape.ndim != 1 or not 0 < shape.size <= MAX_ARRAY_RANK:
        fail("Array reshape shape must be a rank-1 array of 1..8 dimensions")
    dimensions = [integer(size.item(), "Array reshape dimension", -1) for size in shape]
    if dimensions.count(-1) > 1 or 0 in dimensions:
        fail("Array reshape requires positive dimensions and at most one -1")
    explicit = math.prod(size for size in dimensions if size != -1)
    if explicit > MAX_ARRAY_CELLS:
        fail("Array reshape exceeds 10000 cells")
    if -1 in dimensions:
        if array.size % explicit:
            fail("Array reshape dimensions do not preserve the cell count")
        dimensions[dimensions.index(-1)] = array.size // explicit
    if math.prod(dimensions) != array.size:
        fail("Array reshape dimensions do not preserve the cell count")
    _charge(translator, array.size + len(dimensions))
    return _wrap(array.reshape(dimensions))


def invoke_array(translator, name, arguments):
    """Evaluate only the explicitly listed pinned static array algorithms."""
    if name not in ARRAY_FUNCTIONS:
        fail(f"Unsupported static Array operation: {name}")
    if name in ARRAY_ARITHMETIC_FUNCTIONS:
        return invoke_arithmetic(translator, name, arguments)
    if name in ARRAY_REDUCTION_FUNCTIONS:
        return invoke_reduction(translator, name, arguments)
    if name in ARRAY_LAYOUT_FUNCTIONS:
        return invoke_layout(translator, name, arguments)
    if name in ARRAY_MATRIX_FUNCTIONS:
        return invoke_matrix_extra(translator, name, arguments)
    if name in ARRAY_DECOMPOSITION_FUNCTIONS:
        return invoke_decomposition(translator, name, arguments)
    a = arguments
    if name == "Array":
        translator.allowed(a, {"values", "pixelType"})
        if a.get("pixelType") is not None:
            fail("Explicit Array PixelType conversion is unsupported")
        value = a["values"]
        if isinstance(value, StaticArray):
            return value
        shape = _shape(value)
        _charge(translator, math.prod(shape))
        return _wrap(value)
    if name in {"Array.matrixMultiply", "Array.matrixSolve"}:
        translator.allowed(a, {"left", "right"})
        left, right = _matrix(a["left"]), _matrix(a["right"])
        if name == "Array.matrixMultiply":
            if left.shape[1] != right.shape[0]:
                fail("Array matrixMultiply inner dimensions must match")
            if left.shape[0] * right.shape[1] > MAX_ARRAY_CELLS:
                fail("Array matrixMultiply result exceeds 10000 cells")
            _charge(translator, left.shape[0] * right.shape[1] * (left.shape[1] + 1))
            if left.dtype.kind == right.dtype.kind == "i":
                # Integer inference must not silently become rounded Float64
                # or wrap at int64. The shared work budget bounds exact sums.
                exact = (left.astype(object) @ right.astype(object)).tolist()
                _shape(exact)
                return _wrap(exact)
            with np.errstate(over="ignore", invalid="ignore"):
                return _wrap(left.astype(np.float64) @ right.astype(np.float64))
        if left.shape[0] != right.shape[0]:
            fail("Array matrixSolve left and right row counts must match")
        if left.shape[0] < left.shape[1]:
            fail("Underdetermined Array matrixSolve is currently unsupported")
        _charge(translator, max(left.shape + right.shape) ** 3 + left.shape[1] * right.shape[1])
        try:
            solution, _, rank, _ = np.linalg.lstsq(left, right, rcond=None)
            if rank != left.shape[1]:
                fail("Rank-deficient Array matrixSolve is currently unsupported")
            return _wrap(solution)
        except np.linalg.LinAlgError:
            fail("Array matrixSolve failed to converge")
    if name in {"Array.matrixInverse", "Array.matrixPseudoInverse"}:
        translator.allowed(a, {"input"})
        array = _matrix(a["input"])
        if name == "Array.matrixInverse" and array.shape[0] != array.shape[1]:
            fail("Array matrixInverse requires a square matrix")
        _charge(translator, max(array.shape) ** 3 + array.size)
        try:
            return _wrap(np.linalg.inv(array) if name == "Array.matrixInverse"
                         else np.linalg.pinv(array))
        except np.linalg.LinAlgError:
            fail("Array matrix inverse is singular or failed to converge")
    allowed = {"array"}
    if name == "Array.get":
        allowed.add("position")
    elif name == "Array.reshape":
        allowed.add("shape")
    elif name in {"Array.transpose", "Array.matrixTranspose"}:
        allowed.update({"axis1", "axis2"})
    translator.allowed(a, allowed)
    array = _array(a["array"])
    if name == "Array.toList":
        if not array.ndim:
            fail("Rank-0 Array.toList is currently unsupported")
        _charge(translator, array.size)
        return array.tolist()
    if name == "Array.length":
        _charge(translator, array.ndim)
        return _wrap(np.array(array.shape, dtype=np.int64))
    if name == "Array.get":
        position = a["position"]
        if not isinstance(position, list) or len(position) != array.ndim:
            fail("Array get position must specify one index per dimension")
        indices = tuple(integer(index, "Array position", 0) for index in position)
        if any(index >= length for index, length in zip(indices, array.shape)):
            fail("Array get position is outside the array bounds")
        return array[indices].item()
    if name == "Array.reshape":
        return _reshape(translator, array, a["shape"])
    _charge(translator, array.size)
    return _wrap(np.swapaxes(array, *_axes(a, array)))
