"""Exact scalar integer helpers for the pinned Earth Engine Number API.

These functions operate on already-decoded scalar values only. They do not
evaluate EE graphs, coerce floating-point inputs, or emulate raster casts.
"""
from __future__ import annotations

import math
from typing import Any, Callable


INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1
_SIGNED_WIDTHS = (8, 16, 32, 64)


def _fail(message: str) -> None:
    from gee.ee_translate import fail
    fail(message)


def _integer(value: Any, label: str) -> int:
    """Require an exact integral scalar; do not silently truncate floats."""
    if isinstance(value, bool):
        _fail(f"{label} must be an integer, not a boolean")
    if isinstance(value, int):
        result = value
    elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
        result = int(value)
    else:
        _fail(f"{label} must be a finite integer")
    if not INT64_MIN <= result <= INT64_MAX:
        _fail(f"{label} must fit a signed 64-bit integer")
    return result


def bit_count64(value: Any) -> int:
    """Count set bits in the documented 64-bit two's-complement form."""
    integer = _integer(value, "Number.bitCount input")
    return (integer & ((1 << 64) - 1)).bit_count()


def bitwise_not_smallest_signed(value: Any) -> int:
    """Apply EE Number.bitwiseNot using the smallest containing signed type."""
    integer = _integer(value, "Number.bitwiseNot input")
    for width in _SIGNED_WIDTHS:
        low, high = -(1 << (width - 1)), (1 << (width - 1)) - 1
        if low <= integer <= high:
            mask = (1 << width) - 1
            result = (~integer) & mask
            sign_bit = 1 << (width - 1)
            return result - (1 << width) if result & sign_bit else result
    raise AssertionError("signed 64-bit range validation should make this unreachable")


def bitwise_binary_nonnegative64(operation: str, left: Any, right: Any) -> int:
    """Evaluate documented non-negative scalar AND/OR/XOR examples exactly.

    Earth Engine documents these operations as bitwise operations but leaves
    Number operand coercion and result width unspecified. This helper accepts
    only non-negative, integer-valued signed-64 inputs. Negative operands are
    rejected because the Number reference examples do not establish their
    width/sign extension rules. It does not round, narrow, or wrap values.
    """
    lhs = _integer(left, f"Number.{operation} left input")
    rhs = _integer(right, f"Number.{operation} right input")
    if lhs < 0 or rhs < 0:
        _fail(f"Number.{operation} with negative operands is not verified")
    implementations: dict[str, Callable[[int, int], int]] = {
        "bitwiseAnd": int.__and__,
        "bitwiseOr": int.__or__,
        "bitwiseXor": int.__xor__,
    }
    try:
        return implementations[operation](lhs, rhs)
    except KeyError:
        _fail(f"Unsupported Number bitwise operation: {operation}")


def shift64(operation: str, left: Any, right: Any) -> int:
    """Evaluate documented shifts on a conservative, non-overflowing subset."""
    lhs = _integer(left, f"Number.{operation} left input")
    count = _integer(right, f"Number.{operation} shift count")
    if not 0 <= count < 64:
        _fail(f"Number.{operation} shift count must be in [0, 63]")
    if operation == "rightShift":
        # The EE API explicitly documents signed right shift.
        return lhs >> count
    if operation == "leftShift":
        if lhs < 0:
            _fail("Number.leftShift with negative inputs is not verified")
        result = lhs << count
        if not INT64_MIN <= result <= INT64_MAX:
            _fail("Number.leftShift result exceeds the verified signed 64-bit range")
        return result
    _fail(f"Unsupported Number shift operation: {operation}")


SUPPORTED_INTEGER_FUNCTIONS = frozenset({
    "Number.bitCount",
    "Number.bitwiseNot",
    "Number.bitwiseAnd",
    "Number.bitwiseOr",
    "Number.bitwiseXor",
    "Number.leftShift",
    "Number.rightShift",
})


def invoke_integer(translator, name: str, arguments: dict[str, Any]):
    """Evaluate one supported static Number bitwise invocation.

    Raster Image casts/bitwise operations are intentionally not dispatched
    here. The accepted scalar domains are narrower than all GEE inputs: see
    the operation helpers above, which reject unknown coercion and overflow
    cases instead of silently narrowing them.
    """
    if name not in SUPPORTED_INTEGER_FUNCTIONS:
        _fail(f"Unsupported Earth Engine integer algorithm: {name}")
    if not isinstance(arguments, dict):
        _fail("Integer algorithm arguments must be an object")

    binary = {"Number.bitwiseAnd", "Number.bitwiseOr", "Number.bitwiseXor"}
    shifts = {"Number.leftShift", "Number.rightShift"}
    expected = {"input"} if name in {"Number.bitCount", "Number.bitwiseNot"} else {"left", "right"}
    translator.allowed(arguments, expected)
    missing = expected.difference(arguments)
    if missing:
        _fail(f"{name} requires {', '.join(sorted(missing))}")

    if name == "Number.bitCount":
        return bit_count64(arguments["input"])
    if name == "Number.bitwiseNot":
        return bitwise_not_smallest_signed(arguments["input"])
    if name in binary:
        return bitwise_binary_nonnegative64(name.rsplit(".", 1)[1], arguments["left"], arguments["right"])
    if name in shifts:
        return shift64(name.rsplit(".", 1)[1], arguments["left"], arguments["right"])
    raise AssertionError("supported integer dispatch is exhaustive")
