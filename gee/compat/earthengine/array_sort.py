"""Bounded sorting for finite typed static Earth Engine Arrays."""
from __future__ import annotations

import math

import numpy as np

from .array_core import (
    MAX_ARRAY_CELLS,
    MAX_ARRAY_RANK,
    StaticArray,
    charge_array,
    require_array,
    wrap_array,
)
from .ir import fail


STATIC_ARRAY_SORT_FUNCTIONS = frozenset({"Array.sort"})


def sort_axis(array_shape, key_shape):
    """Return the key-selected axis, or ``None`` for a one-cell identity.

    Keys follow the documented EE layout: one axis may have multiple entries,
    and every other key axis must be singleton. A zero-length axis is allowed
    for typed empty arrays when it is the only axis that identifies direction.
    """
    if len(array_shape) != len(key_shape):
        fail("Array.sort keys must have the same rank as array")
    if len(array_shape) > MAX_ARRAY_RANK:
        fail("Array.sort supports rank <= 8")

    varying = [axis for axis, length in enumerate(key_shape) if length > 1]
    empty = [axis for axis, length in enumerate(key_shape) if length == 0]
    if empty and varying or len(empty) > 1:
        fail("Array.sort keys must identify one sort axis")
    if empty:
        axis = empty[0]
    elif varying:
        if len(varying) != 1:
            fail("Array.sort keys must identify one sort axis")
        axis = varying[0]
    else:
        if math.prod(array_shape) == math.prod(key_shape) == 1:
            return None
        fail("Array.sort keys must identify a sort axis for multi-cell arrays")

    if any(length != 1 for i, length in enumerate(key_shape) if i != axis):
        fail("Array.sort key axes other than the sort axis must be singleton")
    if array_shape[axis] != key_shape[axis]:
        fail("Array.sort key length must match the array sort-axis length")
    return axis


def _arguments(translator, name, arguments):
    if not isinstance(arguments, dict):
        fail(f"{name} arguments must be a dictionary")
    translator.allowed(arguments, {"array", "keys"})
    if "array" not in arguments:
        fail(f"{name} requires array")


def _validate_values(data, label):
    if data.dtype.kind not in {"i", "u", "f"}:
        fail(f"Array.sort {label} must contain finite real values")
    if data.dtype.kind == "f" and not np.isfinite(data).all():
        fail(f"Array.sort {label} must contain finite values")
    if data.dtype.kind in {"i", "u"} and data.size and np.any(
            (data < -(2**53)) | (data > 2**53)):
        fail(f"Array.sort {label} integers must fit the exact Float64 domain")


def _sort_work(data, keys, axis):
    if axis is None:
        sort_work = 0
    else:
        count = int(keys.shape[axis])
        sort_work = count * math.ceil(math.log2(count)) if count > 1 else count
    # Include finite/exact-domain scans, stable key ordering, the payload gather,
    # wrap_array's validation/copy, and rank bookkeeping before any of them run.
    return sort_work + 3 * int(data.size) + 2 * int(keys.size) + int(data.ndim) + 1


def _static_sort(translator, value, key_value):
    data = require_array(value)
    keys = data if key_value is None else require_array(key_value)
    if (data.ndim > MAX_ARRAY_RANK or data.size > MAX_ARRAY_CELLS
            or any(length > MAX_ARRAY_CELLS for length in data.shape)):
        fail("Array.sort supports rank <= 8 and at most 10000 cells")
    if (keys.ndim > MAX_ARRAY_RANK or keys.size > MAX_ARRAY_CELLS
            or any(length > MAX_ARRAY_CELLS for length in keys.shape)):
        fail("Array.sort keys exceed the rank/cell budget")

    axis = sort_axis(data.shape, keys.shape)
    charge_array(translator, _sort_work(data, keys, axis))
    _validate_values(data, "array")
    _validate_values(keys, "keys")
    if axis is None or data.size == 0:
        return wrap_array(data)

    # Stable ascending order preserves original payload order for equal keys.
    # This is the local tie policy; it has not been compared with Google EE.
    key_values = np.take(keys, range(int(keys.shape[axis])), axis=axis).reshape(-1)
    order = np.argsort(key_values, kind="stable")
    return wrap_array(np.take(data, order, axis=axis))


def invoke_static_sort(translator, name, arguments):
    """Sort a typed StaticArray on its uniquely identified key axis."""
    if name not in STATIC_ARRAY_SORT_FUNCTIONS:
        fail(f"Unsupported static Array operation: {name}")
    _arguments(translator, name, arguments)
    return _static_sort(translator, arguments["array"], arguments.get("keys"))
