"""Bounded shape-preserving operations for finite static EE Arrays."""
from __future__ import annotations

import math

import numpy as np

from .array_core import (
    MAX_ARRAY_CELLS,
    MAX_ARRAY_RANK,
    charge_array,
    require_array,
    wrap_array,
)
from .ir import fail


ARRAY_LAYOUT_FUNCTIONS = frozenset({
    "Array.slice",
    "Array.project",
    "Array.repeat",
    "Array.cat",
})
MAX_ARRAY_LIST_ITEMS = 1_000


def _integer(value, label, minimum=None):
    # Do not route huge Python ints through math.isfinite: it can overflow while
    # converting them to float, before we can reject them against a budget.
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or isinstance(value, float) and not math.isfinite(value)
            or int(value) != value):
        fail(f"{label} must be an integer")
    result = int(value)
    if minimum is not None and result < minimum:
        fail(f"{label} must be >= {minimum}")
    return result


def _arguments(translator, name, arguments, required, optional):
    if not isinstance(arguments, dict):
        fail(f"{name} arguments must be a dictionary")
    translator.allowed(arguments, required | optional)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def _array(value, label="Array"):
    data = require_array(value)
    if data.ndim > MAX_ARRAY_RANK:
        fail(f"{label} rank exceeds {MAX_ARRAY_RANK}")
    if any(length > MAX_ARRAY_CELLS for length in data.shape):
        fail(f"{label} dimension exceeds {MAX_ARRAY_CELLS}")
    if data.size > MAX_ARRAY_CELLS:
        fail(f"{label} exceeds {MAX_ARRAY_CELLS} cells")
    return data


def _result_cells(shape, label):
    if len(shape) > MAX_ARRAY_RANK:
        fail(f"{label} rank exceeds {MAX_ARRAY_RANK}")
    if any(length < 0 or length > MAX_ARRAY_CELLS for length in shape):
        fail(f"{label} dimension exceeds {MAX_ARRAY_CELLS}")
    cells = math.prod(shape)
    if cells > MAX_ARRAY_CELLS:
        fail(f"{label} exceeds {MAX_ARRAY_CELLS} cells")
    return cells


def _axis(value, rank, label):
    if rank == 0:
        fail(f"{label} requires an Array with at least one axis")
    axis = _integer(value, f"{label} axis", 0)
    if axis >= rank:
        fail(f"{label} axis is outside the array rank")
    return axis


def _slice(translator, arguments):
    _arguments(translator, "Array.slice", arguments, {"array"},
               {"axis", "start", "end", "step"})
    data = _array(arguments["array"])
    axis = _axis(arguments.get("axis", 0), data.ndim, "Array.slice")
    start = _integer(arguments.get("start", 0), "Array.slice start")
    raw_end = arguments.get("end")
    step = _integer(arguments.get("step", 1), "Array.slice step", 1)
    length = data.shape[axis]
    end = length if raw_end is None else _integer(raw_end, "Array.slice end")
    if start < 0:
        start += length
    if end < 0:
        end += length

    # Keep the requested step's origin when a bound lies outside the axis.
    # The API describes the result as positions in [start, end) that are in
    # range, which can differ from clamping start before applying step.
    lower, upper = max(0, start), min(length, end)
    if upper <= lower:
        first, count = 0, 0
    else:
        offset = max(0, (lower - start + step - 1) // step)
        first = start + offset * step
        count = 0 if first >= upper else 1 + (upper - 1 - first) // step
    shape = list(data.shape)
    shape[axis] = count
    cells = _result_cells(shape, "Array.slice result")
    charge_array(translator, cells + count)
    indices = [first + index * step for index in range(count)]
    return wrap_array(np.take(data, indices, axis=axis))


def _project(translator, arguments):
    _arguments(translator, "Array.project", arguments, {"array", "axes"}, set())
    data = _array(arguments["array"])
    axes = arguments["axes"]
    if not isinstance(axes, list) or len(axes) > data.ndim:
        fail("Array.project axes must be a list of valid axes")
    retained = [_integer(axis, "Array.project axis", 0) for axis in axes]
    if any(axis >= data.ndim for axis in retained):
        fail("Array.project axis is outside the array rank")
    if retained != sorted(set(retained)):
        fail("Array.project requires unique axes in ascending order")
    dropped = [axis for axis in range(data.ndim) if axis not in set(retained)]
    if any(data.shape[axis] != 1 for axis in dropped):
        fail("Array.project can drop only singleton axes; zero-length axes are unsupported")
    shape = tuple(data.shape[axis] for axis in retained)
    cells = _result_cells(shape, "Array.project result")
    charge_array(translator, cells + data.ndim)
    projected = np.squeeze(data, axis=tuple(dropped)) if dropped else data
    return wrap_array(projected)


def _repeat(translator, arguments):
    _arguments(translator, "Array.repeat", arguments, {"array"}, {"axis", "copies"})
    data = _array(arguments["array"])
    axis = _axis(arguments.get("axis", 0), data.ndim, "Array.repeat")
    copies = _integer(arguments.get("copies", 2), "Array.repeat copies", 0)
    # Bound the count separately because multiplying a zero-length source axis
    # by an arbitrarily large count would otherwise leave the result shape 0.
    if copies > MAX_ARRAY_CELLS:
        fail(f"Array.repeat copies exceed {MAX_ARRAY_CELLS}")
    shape = list(data.shape)
    shape[axis] *= copies
    cells = _result_cells(shape, "Array.repeat result")
    charge_array(translator, cells + copies)
    if copies == 0:
        result = np.empty(shape, dtype=data.dtype)
    else:
        result = np.concatenate([data] * copies, axis=axis)
    return wrap_array(result)


def _cat(translator, arguments):
    _arguments(translator, "Array.cat", arguments, {"arrays"}, {"axis"})
    values = arguments["arrays"]
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_ARRAY_LIST_ITEMS:
        fail(f"Array.cat arrays must contain 1..{MAX_ARRAY_LIST_ITEMS} static Arrays")
    arrays = [_array(value, "Array.cat input") for value in values]
    rank = arrays[0].ndim
    if any(array.ndim != rank for array in arrays):
        fail("Array.cat inputs must have equal rank")
    axis = _axis(arguments.get("axis", 0), rank, "Array.cat")
    for dimension in range(rank):
        if dimension != axis and any(
                array.shape[dimension] != arrays[0].shape[dimension]
                for array in arrays[1:]):
            fail("Array.cat inputs must match on every non-concatenated axis")
    shape = list(arrays[0].shape)
    shape[axis] = sum(array.shape[axis] for array in arrays)
    cells = _result_cells(shape, "Array.cat result")
    source_cells = sum(array.size for array in arrays)
    if source_cells > MAX_ARRAY_CELLS:
        fail(f"Array.cat inputs exceed {MAX_ARRAY_CELLS} total cells")
    charge_array(translator, cells + len(arrays))
    return wrap_array(np.concatenate(arrays, axis=axis))


def invoke_layout(translator, name, arguments):
    """Evaluate the bounded static Array slice/project/repeat/cat subset."""
    if name not in ARRAY_LAYOUT_FUNCTIONS:
        fail(f"Unsupported static Array layout operation: {name}")
    if name == "Array.slice":
        return _slice(translator, arguments)
    if name == "Array.project":
        return _project(translator, arguments)
    if name == "Array.repeat":
        return _repeat(translator, arguments)
    return _cat(translator, arguments)
