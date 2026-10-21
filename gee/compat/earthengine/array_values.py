"""Bounded static EE arrays; raster array pixels and explicit PixelTypes reject."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .ir import fail, integer


MAX_ARRAY_CELLS = 10_000
MAX_ARRAY_RANK = 8
MAX_ARRAY_WORK = 50_000
ARRAY_FUNCTIONS = frozenset({
    "Array", "Array.get", "Array.length", "Array.toList", "Array.reshape",
    "Array.transpose", "Array.matrixTranspose", "Array.matrixMultiply",
    "Array.matrixInverse", "Array.matrixSolve", "Array.matrixPseudoInverse",
})


@dataclass(frozen=True)
class StaticArray:
    """Typed array value, distinct from the ordinary EE List representation."""

    data: np.ndarray

    def to_value(self):
        return self.data.tolist()


def _shape(value, depth=0, count=None):
    count = [0] if count is None else count
    if depth > MAX_ARRAY_RANK:
        fail("Static Array rank exceeds 8")
    if isinstance(value, list):
        if not value:
            fail("Empty Array values require an unsupported explicit PixelType")
        if len(value) > MAX_ARRAY_CELLS:
            fail("Static Array exceeds 10000 cells")
        shapes = [_shape(child, depth + 1, count) for child in value]
        if any(shape != shapes[0] for shape in shapes[1:]):
            fail("Array values must form a rectangular numeric array")
        return (len(value), *shapes[0])
    if type(value) not in (int, float):
        fail("Array values must be finite real numbers")
    if isinstance(value, int) and abs(value) > 2**53:
        fail("Static Array integers outside the exact Float64 domain are unsupported")
    if not math.isfinite(value):
        fail("Array values must be finite real numbers")
    count[0] += 1
    if count[0] > MAX_ARRAY_CELLS:
        fail("Static Array exceeds 10000 cells")
    return ()


def _wrap(value):
    result = np.asarray(value)
    if result.size > MAX_ARRAY_CELLS or result.ndim > MAX_ARRAY_RANK:
        fail("Static Array result exceeds the cell/rank budget")
    if not np.isfinite(result).all():
        fail("Static Array computation must produce finite real numbers")
    result = result.copy()
    result.flags.writeable = False
    return StaticArray(result)


def _array(value):
    if not isinstance(value, StaticArray):
        fail("Expected a static ee.Array, not a List or raster array")
    return value.data


def _charge(translator, work):
    if work > MAX_ARRAY_WORK or translator.steps + work > 50_000:
        fail("Static Array operation exceeds the compilation work budget")
    translator.steps += work


def _axes(arguments, array):
    axes = [integer(arguments.get(key, default), "Array axis", 0)
            for key, default in (("axis1", 0), ("axis2", 1))]
    if any(axis >= array.ndim for axis in axes):
        fail("Array transpose axis is outside the array rank")
    return axes


def _matrix(value):
    array = _array(value)
    if array.ndim != 2:
        fail("Static matrix operations currently require rank-2 arrays")
    return array


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
