"""Bounded local semantics for static Earth Engine String values.

Unicode length and ordering use Python Unicode code points. The pinned
signature describes strings as lexicographic but does not specify whether the
remote service uses code points or UTF-16 code units, so non-ASCII agreement
with Earth Engine is unverified. Numeric constructor values use Python's
shortest round-trip number spelling (with an integral ``.0`` removed); Google
formatting equivalence is also unverified.
"""
from __future__ import annotations

import math

from .ir import fail


MAX_STATIC_STRING_WORK = 50_000


def _required(arguments, name):
    if name not in arguments:
        fail(f"String operation requires {name}")
    return arguments[name]


def _string(value, label):
    if not isinstance(value, str):
        fail(f"{label} must be a string")
    return value


def _charge(translator, amount, label):
    if amount < 0 or amount > MAX_STATIC_STRING_WORK or translator.steps + amount > MAX_STATIC_STRING_WORK:
        fail(f"{label} exceeds the shared string work budget")
    translator.steps += amount


def _number_text(translator, value):
    if type(value) not in (int, float):
        fail("String constructor supports only static strings and finite numbers")
    if type(value) is float and not math.isfinite(value):
        fail("String constructor requires a finite Number")

    if type(value) is int:
        # Preflight using an integer upper bound before asking Python to create
        # the decimal spelling. log10(2) is less than 0.30103.
        bits = abs(value).bit_length()
        digits = max(1, (bits * 30103 + 99999) // 100000)
        estimated_size = digits + int(value < 0)
        _charge(translator, estimated_size, "String numeric conversion")
        try:
            result = str(value)
        except ValueError:
            fail("String numeric conversion exceeds the local integer spelling limit")
    else:
        result = repr(value)
        if result.endswith(".0"):
            result = result[:-2]
        _charge(translator, len(result), "String numeric conversion")

    # Integer preflight may conservatively overestimate by one character.
    if type(value) is int:
        translator.steps -= estimated_size - len(result)
    return result


def construct_string(translator, arguments):
    """Convert the supported static subset of the official String input."""
    if "input" not in arguments:
        fail("String constructor requires input")
    value = arguments["input"]
    if isinstance(value, str):
        return value
    return _number_text(translator, value)


def invoke_string(translator, name, arguments):
    """Evaluate a pinned basic String method with bounded type/work checks."""
    if name == "String.cat":
        left = _string(_required(arguments, "string1"), "String.cat string1")
        right = _string(_required(arguments, "string2"), "String.cat string2")
        size = len(left) + len(right)
        # Charge the complete result before allocating it; this also bounds
        # every repeated List.iterate concatenation against the shared budget.
        _charge(translator, size, "String.cat")
        return left + right
    if name == "String.length":
        return len(_string(_required(arguments, "string"), "String.length input"))
    if name == "String.compareTo":
        left = _string(_required(arguments, "string1"), "String.compareTo string1")
        right = _string(_required(arguments, "string2"), "String.compareTo string2")
        # Comparing strings can inspect their full common prefix. Charge that
        # worst case before Python starts the comparison.
        _charge(translator, min(len(left), len(right)), "String.compareTo")
        return (left > right) - (left < right)
    fail(f"Unsupported static String operation: {name}")
