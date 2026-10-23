"""Bounded static identity, vector dot product and Array padding."""
from __future__ import annotations

import math

import numpy as np

from .array_core import (
    MAX_ARRAY_CELLS,
    MAX_ARRAY_RANK,
    charge_array,
    finite_float_sum,
    require_array,
    wrap_array,
)
from .ir import fail


ARRAY_VECTOR_FUNCTIONS = frozenset({
    "Array.identity",
    "Array.dotProduct",
    "Array.pad",
})
_EXACT_INTEGER_LIMIT = 2**53


def _arguments(translator, name, arguments, required, optional=()):
    if not isinstance(arguments, dict):
        fail(f"{name} arguments must be a dictionary")
    translator.allowed(arguments, set(required) | set(optional))
    missing = set(required) - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def _integer(value, label, minimum=0, maximum=MAX_ARRAY_CELLS):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"{label} must be an integer")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            fail(f"{label} must be an integer")
        if value < minimum or value > maximum:
            fail(f"{label} must be between {minimum} and {maximum}")
        result = int(value)
    else:
        result = value
        if result < minimum or result > maximum:
            fail(f"{label} must be between {minimum} and {maximum}")
    return result


def _array(value, label):
    data = require_array(value)
    if data.ndim > MAX_ARRAY_RANK:
        fail(f"{label} rank exceeds {MAX_ARRAY_RANK}")
    if any(length > MAX_ARRAY_CELLS for length in data.shape):
        fail(f"{label} dimension exceeds {MAX_ARRAY_CELLS}")
    if data.size > MAX_ARRAY_CELLS:
        fail(f"{label} exceeds {MAX_ARRAY_CELLS} cells")
    if data.dtype.kind not in {"i", "u", "f"}:
        fail(f"{label} must contain finite real numbers")
    return data


def _validate_values(data, label):
    for value in data.flat:
        if data.dtype.kind in {"i", "u"}:
            if abs(int(value)) > _EXACT_INTEGER_LIMIT:
                fail(f"{label} integer is outside the exact Float64 domain")
        elif not math.isfinite(float(value)):
            fail(f"{label} must contain finite real numbers")


def _identity(translator, arguments):
    _arguments(translator, "Array.identity", arguments, {"size"})
    size = _integer(arguments["size"], "Array.identity size")
    cells = size * size
    if cells > MAX_ARRAY_CELLS:
        fail("Array.identity result exceeds 10000 cells")
    charge_array(translator, cells * 2 + 1)
    return wrap_array(np.eye(size, dtype=np.int64))


def _dot_product(translator, arguments):
    _arguments(translator, "Array.dotProduct", arguments, {"array1", "array2"})
    left = _array(arguments["array1"], "Array.dotProduct input")
    right = _array(arguments["array2"], "Array.dotProduct input")
    if left.ndim != 1 or right.ndim != 1:
        fail("Array.dotProduct requires rank-1 arrays")
    if left.shape != right.shape:
        fail("Array.dotProduct requires vectors with equal lengths")

    count = int(left.size)
    charge_array(translator, count * 4 + 1)
    _validate_values(left, "Array.dotProduct")
    _validate_values(right, "Array.dotProduct")
    if left.dtype.kind in {"i", "u"} and right.dtype.kind in {"i", "u"}:
        result = sum(
            (int(a) * int(b) for a, b in zip(left.flat, right.flat)),
            0,
        )
        if abs(result) > _EXACT_INTEGER_LIMIT:
            fail("Array.dotProduct integer result exceeds the exact Float64 domain")
        return result

    products = []
    for a, b in zip(left.flat, right.flat):
        product = float(a) * float(b)
        if not math.isfinite(product):
            fail("Array.dotProduct product exceeds the finite Float64 domain")
        products.append(product)
    return finite_float_sum(products)


def _pad_value(value):
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("Array.pad value must be a finite real number")
    if isinstance(value, int):
        if abs(value) > _EXACT_INTEGER_LIMIT:
            fail("Array.pad integer is outside the exact Float64 domain")
        return value
    if not math.isfinite(value):
        fail("Array.pad value must be a finite real number")
    return value


def _pad(translator, arguments):
    _arguments(translator, "Array.pad", arguments, {"array", "lengths"}, {"pad"})
    data = _array(arguments["array"], "Array.pad input")
    lengths = arguments["lengths"]
    if not isinstance(lengths, list) or len(lengths) != data.ndim:
        fail("Array.pad lengths must contain one integer for each array axis")
    target = tuple(
        _integer(length, "Array.pad length")
        for length in lengths
    )
    shape = tuple(
        max(current, requested)
        for current, requested in zip(data.shape, target)
    )
    cells = math.prod(shape) if shape else 1
    if cells > MAX_ARRAY_CELLS:
        fail("Array.pad result exceeds 10000 cells")
    pad_value = _pad_value(arguments.get("pad"))
    charge_array(translator, int(data.size) + cells * 2 + data.ndim + 1)
    _validate_values(data, "Array.pad input")

    try:
        dtype = np.result_type(data.dtype, np.asarray(pad_value).dtype)
        result = np.full(shape, pad_value, dtype=dtype)
    except (OverflowError, TypeError, ValueError):
        fail("Array.pad result cannot preserve the input and pad value types")
    source = tuple(slice(0, length) for length in data.shape)
    result[source] = data
    return wrap_array(result)


def invoke_array_vector(translator, name, arguments):
    """Evaluate only the pinned, finite static Array vector operations."""
    if name not in ARRAY_VECTOR_FUNCTIONS:
        fail(f"Unsupported static Array vector operation: {name}")
    if name == "Array.identity":
        return _identity(translator, arguments)
    if name == "Array.dotProduct":
        return _dot_product(translator, arguments)
    return _pad(translator, arguments)
