"""Bounded dtype casts for finite, static Earth Engine Arrays."""
from __future__ import annotations

import numpy as np

from .array_core import (
    MAX_ARRAY_CELLS,
    MAX_ARRAY_RANK,
    charge_array,
    require_array,
    wrap_array,
)
from .ir import fail


ARRAY_CAST_ALIAS_MAP = {
    "Array.byte": "Array.toByte",
    "Array.int": "Array.toInt",
    "Array.int8": "Array.toInt8",
    "Array.int16": "Array.toInt16",
    "Array.int32": "Array.toInt32",
    "Array.int64": "Array.toInt64",
    "Array.long": "Array.toLong",
    "Array.short": "Array.toShort",
    "Array.uint8": "Array.toUint8",
    "Array.uint16": "Array.toUint16",
    "Array.uint32": "Array.toUint32",
    "Array.float": "Array.toFloat",
    "Array.double": "Array.toDouble",
}

_TARGETS = {
    "Array.toByte": np.dtype(np.uint8),
    "Array.toInt": np.dtype(np.int32),
    "Array.toInt8": np.dtype(np.int8),
    "Array.toInt16": np.dtype(np.int16),
    "Array.toInt32": np.dtype(np.int32),
    "Array.toInt64": np.dtype(np.int64),
    "Array.toLong": np.dtype(np.int64),
    "Array.toShort": np.dtype(np.int16),
    "Array.toUint8": np.dtype(np.uint8),
    "Array.toUint16": np.dtype(np.uint16),
    "Array.toUint32": np.dtype(np.uint32),
    "Array.toFloat": np.dtype(np.float32),
    "Array.toDouble": np.dtype(np.float64),
}

ARRAY_CAST_FUNCTIONS = frozenset(_TARGETS) | frozenset(ARRAY_CAST_ALIAS_MAP)

_EXACT_INTEGER_LIMIT = 2**53


def _validate_source(array: np.ndarray, name: str) -> None:
    if array.dtype.kind not in {"i", "u", "f"}:
        fail(f"{name} input must contain finite real numbers, not booleans")
    if (array.ndim > MAX_ARRAY_RANK or array.size > MAX_ARRAY_CELLS
            or any(length > MAX_ARRAY_CELLS for length in array.shape)):
        fail(f"{name} input exceeds the static Array rank/cell budget")
    if not np.isfinite(array).all():
        fail(f"{name} input must contain finite real numbers")
    if array.dtype.kind in {"i", "u"} and np.any(
            (array < -_EXACT_INTEGER_LIMIT) | (array > _EXACT_INTEGER_LIMIT)):
        fail(f"{name} input integers exceed the exact Float64 domain")


def _cast_integer(array: np.ndarray, dtype: np.dtype, name: str) -> np.ndarray:
    limits = np.iinfo(dtype)
    # EE's documented Array.byte conversion rounds to the nearest integer,
    # with half ties toward positive infinity, then saturates to its range.
    # Keep the same bounded integer conversion policy for the typed aliases.
    values = array.astype(np.float64, copy=False)
    floored = np.floor(values)
    rounded = floored + ((values - floored) >= 0.5)
    bounded = np.clip(rounded, limits.min, limits.max)
    if np.any(np.abs(bounded) > _EXACT_INTEGER_LIMIT):
        fail(f"{name} result exceeds the exact Float64 integer domain")
    return bounded.astype(dtype)


def invoke_array_cast(translator, name: str, arguments: dict):
    """Cast a static Array element-wise while preserving its shape and dtype.

    Byte rounding and saturation follow the Array.byte reference. The same
    policy for other integer targets, including half ties toward positive
    infinity, is an explicit unverified local inference. Float32 rejects
    overflow instead of producing infinity. Returned integers stay in the
    shared exact-Float64 domain.
    """
    if name not in ARRAY_CAST_FUNCTIONS:
        fail(f"Unsupported static Array cast: {name}")
    target_name = ARRAY_CAST_ALIAS_MAP.get(name, name)
    target = _TARGETS[target_name]
    translator.allowed(arguments, {"input"})
    if "input" not in arguments:
        fail(f"{name} requires input")

    array = require_array(arguments["input"])
    if (array.ndim > MAX_ARRAY_RANK or array.size > MAX_ARRAY_CELLS
            or any(length > MAX_ARRAY_CELLS for length in array.shape)):
        fail(f"{name} input exceeds the static Array rank/cell budget")
    charge_array(translator, int(array.size) * 3 + 1)
    _validate_source(array, name)

    if target.kind in {"i", "u"}:
        result = _cast_integer(array, target, name)
    elif target == np.dtype(np.float32):
        with np.errstate(over="ignore", invalid="ignore"):
            result = array.astype(target)
        if not np.isfinite(result).all():
            fail(f"{name} must produce finite Float32 values")
    else:
        result = array.astype(target, copy=True)

    if result.shape != array.shape:
        fail(f"{name} must preserve the input Array shape")
    return wrap_array(result)
