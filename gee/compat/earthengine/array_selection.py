"""Finite static implementations of selected Earth Engine Array operations."""
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


ARRAY_SELECTION_FUNCTIONS = frozenset({
    "Array.bitsToArray",
    "Array.cut",
    "Array.mask",
})

_EXACT_INTEGER_LIMIT = 2**53
_SIGNED_BIT_WIDTH = 64
_UINT64_MASK = (1 << _SIGNED_BIT_WIDTH) - 1


def _arguments(translator, name, arguments, required):
    if not isinstance(arguments, dict):
        fail(f"{name} arguments must be a dictionary")
    translator.allowed(arguments, required)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def _array(value, name):
    data = require_array(value)
    if data.ndim > MAX_ARRAY_RANK:
        fail(f"{name} rank exceeds {MAX_ARRAY_RANK}")
    if any(length > MAX_ARRAY_CELLS for length in data.shape):
        fail(f"{name} dimension exceeds {MAX_ARRAY_CELLS}")
    if data.size > MAX_ARRAY_CELLS:
        fail(f"{name} exceeds {MAX_ARRAY_CELLS} cells")
    if data.dtype.kind not in {"i", "u", "f"}:
        fail(f"{name} must contain finite real numbers")
    return data


def _validate_values(data, name):
    if data.dtype.kind == "f":
        if not np.isfinite(data).all():
            fail(f"{name} must contain finite real numbers")
        return
    for value in data.flat:
        if abs(int(value)) > _EXACT_INTEGER_LIMIT:
            fail(f"{name} integers must fit the exact Float64 domain")


def _integer(value, name):
    if (isinstance(value, (bool, np.bool_))
            or not isinstance(value, (int, float))
            or isinstance(value, float) and not math.isfinite(value)
            or int(value) != value):
        fail(f"{name} must be an integer")
    return int(value)


def _number_integer(value):
    if isinstance(value, (bool, np.bool_)):
        fail("Array.bitsToArray input must be an integer Number")
    if isinstance(value, np.generic):
        value = value.item()
    if type(value) is int:
        integer = value
    elif type(value) is float and math.isfinite(value) and value.is_integer():
        integer = int(value)
    else:
        fail("Array.bitsToArray input must be a finite integer Number")
    if abs(integer) > _EXACT_INTEGER_LIMIT:
        fail("Array.bitsToArray input exceeds the exact Float64 integer domain")
    return integer


def _bits_to_array(translator, arguments):
    _arguments(translator, "Array.bitsToArray", arguments, {"input"})
    value = _number_integer(arguments["input"])
    if value < 0:
        # The official example for -1 is 64 one-bits. This applies the same
        # signed 64-bit two's-complement representation to other negatives.
        bit_value = value & _UINT64_MASK
        width = _SIGNED_BIT_WIDTH
    else:
        width = max(1, value.bit_length())
        bit_value = value

    # Reserve bit construction, output validation and the owned result copy
    # before creating the output buffer.
    charge_array(translator, 3 * width + 1)
    bits = [
        (bit_value >> (width - offset - 1)) & 1
        for offset in range(width)
    ]
    return wrap_array(np.asarray(bits, dtype=np.int64))


def _cut(translator, arguments):
    _arguments(translator, "Array.cut", arguments, {"array", "position"})
    data = _array(arguments["array"], "Array.cut input")
    positions = arguments["position"]
    if not isinstance(positions, list) or len(positions) != data.ndim:
        fail("Array.cut position must contain one integer for each array axis")

    selected = [_integer(value, "Array.cut position") for value in positions]
    result_shape = []
    slices = []
    for axis, (position, length) in enumerate(zip(selected, data.shape)):
        if position == -1:
            result_shape.append(length)
            slices.append(slice(None))
        elif position < 0:
            fail("Array.cut positions must be non-negative or -1")
        elif position >= length:
            fail(f"Array.cut position is outside axis {axis}")
        else:
            result_shape.append(1)
            slices.append(slice(position, position + 1))

    result_cells = math.prod(result_shape) if result_shape else 1
    if result_cells > MAX_ARRAY_CELLS:
        fail(f"Array.cut result exceeds {MAX_ARRAY_CELLS} cells")
    # A value scan plus wrap_array's result scan and detached copy are charged
    # before touching array contents or producing a view.
    charge_array(translator, int(data.size) + 2 * result_cells + data.ndim + 1)
    _validate_values(data, "Array.cut input")
    return wrap_array(data[tuple(slices)])


def _mask(translator, arguments):
    _arguments(translator, "Array.mask", arguments, {"input", "mask"})
    data = _array(arguments["input"], "Array.mask input")
    mask = _array(arguments["mask"], "Array.mask mask")
    if data.shape != mask.shape:
        fail("Array.mask currently requires an exactly matching mask shape")

    if data.size == 0:
        selection_axis = None
    else:
        varying_axes = [axis for axis, length in enumerate(data.shape) if length > 1]
        if data.ndim == 1:
            selection_axis = 0
        elif len(varying_axes) == 1:
            selection_axis = varying_axes[0]
        else:
            fail(
                "Array.mask requires a rank-1 array or a same-shape array with "
                "one varying axis"
            )

    # Reserve the worst-case output: selection can keep every input value. The
    # work covers one scan each for values and mask, one gather, then
    # wrap_array's result scan and detached copy. Precharge before scanning or
    # allocating indices.
    maximum_output_cells = int(data.size) if selection_axis is not None else 0
    charge_array(
        translator,
        int(data.size) + int(mask.size) + 3 * maximum_output_cells + data.ndim + 1,
    )
    _validate_values(data, "Array.mask input")

    if selection_axis is None:
        _validate_values(mask, "Array.mask mask")
        return wrap_array(data)

    kept = []
    for index, value in enumerate(mask.flat):
        if mask.dtype.kind == "f":
            if not math.isfinite(float(value)):
                fail("Array.mask mask must contain finite real numbers")
        elif abs(int(value)) > _EXACT_INTEGER_LIMIT:
            fail("Array.mask mask integers must fit the exact Float64 domain")
        if value != 0:
            kept.append(index)

    output_shape = list(data.shape)
    output_shape[selection_axis] = len(kept)
    output_cells = math.prod(output_shape)
    if output_cells > MAX_ARRAY_CELLS:
        fail(f"Array.mask result exceeds {MAX_ARRAY_CELLS} cells")
    # The exact-shape subset only selects along the one varying axis, so its
    # flat mask positions are also the gather indices on that axis.
    return wrap_array(np.take(data, kept, axis=selection_axis))


def invoke_array_selection(translator, name, arguments):
    """Evaluate bitsToArray, cut, or mask for bounded finite static values."""
    if name not in ARRAY_SELECTION_FUNCTIONS:
        fail(f"Unsupported static Array selection operation: {name}")
    if name == "Array.bitsToArray":
        return _bits_to_array(translator, arguments)
    if name == "Array.cut":
        return _cut(translator, arguments)
    return _mask(translator, arguments)
