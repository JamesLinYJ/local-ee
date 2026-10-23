"""Finite static scalar casts for the pinned Earth Engine Number API."""
from __future__ import annotations

import math
import struct

from .array_core import MAX_ARRAY_WORK
from .ir import fail


_INTEGER_CASTS = {
    "toByte": (0, 2**8 - 1),
    "toInt8": (-(2**7), 2**7 - 1),
    "toInt16": (-(2**15), 2**15 - 1),
    "toInt32": (-(2**31), 2**31 - 1),
    "toInt64": (-(2**63), 2**63 - 1),
    "toLong": (-(2**63), 2**63 - 1),
    "toShort": (-(2**15), 2**15 - 1),
    "toUint8": (0, 2**8 - 1),
    "toUint16": (0, 2**16 - 1),
    "toUint32": (0, 2**32 - 1),
    "byte": (0, 2**8 - 1),
    "int8": (-(2**7), 2**7 - 1),
    "int16": (-(2**15), 2**15 - 1),
    "int32": (-(2**31), 2**31 - 1),
    "int64": (-(2**63), 2**63 - 1),
    "long": (-(2**63), 2**63 - 1),
    "short": (-(2**15), 2**15 - 1),
    "uint8": (0, 2**8 - 1),
    "uint16": (0, 2**16 - 1),
    "uint32": (0, 2**32 - 1),
}
_FLOAT32_CASTS = frozenset({"toFloat", "float"})
_FLOAT64_CASTS = frozenset({"toDouble", "double"})
NUMBER_CAST_FUNCTIONS = frozenset(
    "Number." + operation
    for operation in _INTEGER_CASTS.keys() | _FLOAT32_CASTS | _FLOAT64_CASTS
)
_MAX_EXACT_INTEGER = 2**53


def _number(value, name):
    if type(value) not in (int, float):
        fail(f"{name} requires a finite static numeric input")
    if type(value) is int and abs(value) > _MAX_EXACT_INTEGER:
        fail(f"{name} input integer exceeds the exact Float64 domain")
    if type(value) is float and not math.isfinite(value):
        fail(f"{name} requires a finite static numeric input")
    return value


def _charge(translator):
    if translator.steps + 1 > MAX_ARRAY_WORK:
        fail("Number cast exceeds the 50000-step compilation work budget")
    translator.steps += 1


def _cast(operation, value):
    if operation in _INTEGER_CASTS:
        lower, upper = _INTEGER_CASTS[operation]
        # EE documents precision loss and clamping. Toward-zero truncation is
        # the declared local policy; rounding-direction parity is unverified.
        if value < lower:
            result = lower
        elif value > upper:
            result = upper
        else:
            result = int(value)  # Python int truncates toward zero.
        if abs(result) > _MAX_EXACT_INTEGER:
            fail(f"{operation} result exceeds the exact Float64 integer domain")
        return result
    if operation in _FLOAT32_CASTS:
        try:
            result = struct.unpack("!f", struct.pack("!f", float(value)))[0]
        except OverflowError:
            fail(f"{operation} exceeds the finite Float32 domain")
        if not math.isfinite(result):
            fail(f"{operation} exceeds the finite Float32 domain")
        return result
    if operation in _FLOAT64_CASTS:
        result = float(value)
        if not math.isfinite(result):
            fail(f"{operation} exceeds the finite Float64 domain")
        return result
    fail(f"Unsupported static Number cast: Number.{operation}")


def invoke_number_cast(translator, name, arguments):
    """Evaluate one bounded scalar cast while retaining the shared work cap.

    The static subset accepts finite Python int/float values; Python integers
    and integer cast results stay in the exact Float64 integer domain (<=2^53).
    """
    if name not in NUMBER_CAST_FUNCTIONS:
        fail(f"Unsupported static Number cast: {name}")
    translator.allowed(arguments, {"input"})
    if "input" not in arguments:
        fail(f"{name} requires input")
    value = _number(arguments["input"], name)
    _charge(translator)
    return _cast(name.split(".", 1)[1], value)
