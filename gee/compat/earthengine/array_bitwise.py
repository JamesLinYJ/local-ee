"""Bounded, exact integer operations for finite static Earth Engine Arrays."""
from __future__ import annotations

import math
import operator

import numpy as np

from .array_core import (
    MAX_ARRAY_CELLS,
    MAX_ARRAY_RANK,
    charge_array,
    require_array,
    wrap_array,
)
from .ir import fail


ARRAY_BITWISE_ALIAS_MAP = {
    "Array.bitwise_and": "Array.bitwiseAnd",
    "Array.bitwise_not": "Array.bitwiseNot",
    "Array.bitwise_or": "Array.bitwiseOr",
    "Array.bitwise_xor": "Array.bitwiseXor",
    "Array.left_shift": "Array.leftShift",
    "Array.right_shift": "Array.rightShift",
}

_CANONICAL_FUNCTIONS = frozenset({
    "Array.bitCount",
    "Array.bitwiseAnd",
    "Array.bitwiseNot",
    "Array.bitwiseOr",
    "Array.bitwiseXor",
    "Array.leftShift",
    "Array.rightShift",
})
ARRAY_BITWISE_FUNCTIONS = _CANONICAL_FUNCTIONS | frozenset(ARRAY_BITWISE_ALIAS_MAP)

_EXACT_INTEGER_LIMIT = 2**53
_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1
_UINT64_MASK = (1 << 64) - 1
_SIGNED_WIDTHS = (8, 16, 32, 64)
_BINARY_OPERATORS = {
    "Array.bitwiseAnd": operator.and_,
    "Array.bitwiseOr": operator.or_,
    "Array.bitwiseXor": operator.xor,
}


def _canonical_name(name: str) -> str:
    return ARRAY_BITWISE_ALIAS_MAP.get(name, name)


def _validate_array(array: np.ndarray, name: str, side: str) -> None:
    if array.dtype.kind not in {"i", "u", "f"}:
        fail(f"{name} {side} must contain finite real numbers")
    if array.ndim > MAX_ARRAY_RANK or array.size > MAX_ARRAY_CELLS:
        fail(f"{name} {side} exceeds the static Array rank/cell budget")
    if array.size == 0:
        fail(f"{name} {side} cannot be empty")


def _exact_integer(value, name: str, side: str) -> int:
    if isinstance(value, (bool, np.bool_)):
        fail(f"{name} {side} values must be integers, not booleans")
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, int):
        result = value
    elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
        result = int(value)
    else:
        fail(f"{name} {side} values must be finite integers")
    if abs(result) > _EXACT_INTEGER_LIMIT:
        fail(f"{name} {side} values exceed the exact Float64 integer domain")
    if not _INT64_MIN <= result <= _INT64_MAX:
        fail(f"{name} {side} values must fit signed 64-bit integers")
    return result


def _integer_values(array: np.ndarray, name: str, side: str) -> list[int]:
    return [_exact_integer(value, name, side) for value in array.flat]


def _wrap_exact_result(values: list[int], shape: tuple[int, ...], name: str):
    if any(abs(value) > _EXACT_INTEGER_LIMIT for value in values):
        fail(f"{name} result exceeds the exact Float64 integer domain")
    if any(not _INT64_MIN <= value <= _INT64_MAX for value in values):
        fail(f"{name} result exceeds the signed 64-bit integer range")
    return wrap_array(np.asarray(values, dtype=np.int64).reshape(shape))


def _charge(translator, size: int) -> None:
    # One complete bounded pass covers exact-integer validation, the operation,
    # and result range checks before any per-cell result list is allocated.
    charge_array(translator, size * 5)


def _bitwise_not(value: int) -> int:
    for width in _SIGNED_WIDTHS:
        low, high = -(1 << (width - 1)), (1 << (width - 1)) - 1
        if low <= value <= high:
            # Python's signed complement has the same result as complementing
            # inside this smallest containing signed width.
            return ~value
    raise AssertionError("the validated signed-64 range must fit a signed width")


def invoke_array_bitwise(translator, name: str, arguments: dict):
    """Evaluate one supported Array bitwise algorithm on static finite values.

    Binary AND/OR/XOR and left shifts accept only nonnegative values because
    the pinned API does not define a shared signed width for those results.
    Right shifts are explicitly signed and use arithmetic two's-complement
    shifting. NOT follows the documented smallest containing signed type.
    Every returned integer must remain in the exact Float64 integer domain.
    """
    if name not in ARRAY_BITWISE_FUNCTIONS:
        fail(f"Unsupported static Array bitwise operation: {name}")
    name = _canonical_name(name)

    unary = name in {"Array.bitCount", "Array.bitwiseNot"}
    allowed = {"input"} if unary else {"left", "right"}
    translator.allowed(arguments, allowed)
    missing = allowed - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")

    if unary:
        array = require_array(arguments["input"])
        _validate_array(array, name, "input")
        _charge(translator, int(array.size))
        values = _integer_values(array, name, "input")
        if name == "Array.bitCount":
            result = [(value & _UINT64_MASK).bit_count() for value in values]
        else:
            result = [_bitwise_not(value) for value in values]
        return _wrap_exact_result(result, array.shape, name)

    left = require_array(arguments["left"])
    right = require_array(arguments["right"])
    _validate_array(left, name, "left")
    _validate_array(right, name, "right")
    if name in _BINARY_OPERATORS and left.shape != right.shape:
        fail("Static Array bitwise binary operations require the same shape")
    if name not in _BINARY_OPERATORS and right.shape not in {(), left.shape}:
        fail(f"{name} requires a scalar shift count or an array with the same shape")

    _charge(translator, int(left.size))
    left_values = _integer_values(left, name, "left")
    right_values = _integer_values(right, name, "right")
    if name in _BINARY_OPERATORS:
        if any(value < 0 for value in left_values + right_values):
            fail(f"{name} with negative operands is not verified")
        operation = _BINARY_OPERATORS[name]
        result = [operation(first, second)
                  for first, second in zip(left_values, right_values)]
        return _wrap_exact_result(result, left.shape, name)

    if right.shape == ():
        right_values *= math.prod(left.shape) if left.shape else 1
    for count in right_values:
        if not 0 <= count < 64:
            fail(f"{name} shift counts must be in [0, 63]")
    if name == "Array.leftShift":
        if any(value < 0 for value in left_values):
            fail("Array.leftShift with negative inputs is not verified")
        result = [value << count for value, count in zip(left_values, right_values)]
        if any(value > _INT64_MAX for value in result):
            fail("Array.leftShift result exceeds the verified signed 64-bit range")
    else:
        result = [value >> count for value, count in zip(left_values, right_values)]
    return _wrap_exact_result(result, left.shape, name)
