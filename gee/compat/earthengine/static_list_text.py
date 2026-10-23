"""Bounded textual conversion for the documented static List.join types."""
from __future__ import annotations

import math

from .array_core import charge_array
from .ir import fail


MAX_LIST_OUTPUT_BYTES = 1_000_000


def _number_text(value):
    if type(value) is int:
        if abs(value) > 2**53:
            fail("List.join requires numbers within the exact Float64 domain")
        return str(value)
    if type(value) is not float or not math.isfinite(value):
        fail("List.join supports only finite numbers, strings and booleans")
    if value == 0:
        return "0"
    text = repr(value)
    if "e" not in text:
        return text[:-2] if text.endswith(".0") else text
    mantissa, exponent_text = text.split("e")
    exponent = int(exponent_text)
    if -6 <= exponent < 21:
        from decimal import Decimal

        fixed = format(Decimal(text), "f")
        return fixed.rstrip("0").rstrip(".") if "." in fixed else fixed
    sign = "+" if exponent >= 0 else "-"
    return f"{mantissa}e{sign}{abs(exponent)}"


def _json_string_size(value):
    size = len(value) + 2
    for character in value:
        code = ord(character)
        if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
            size += 1
        elif code < 32:
            size += 5
        elif code >= 127:
            size += 5 if code <= 0xFFFF else 11
    return size


def join_values(translator, values, separator):
    """Join only strings/numbers/booleans, charging before result allocation."""
    if type(separator) is not str:
        fail("List.join separator must be a string")
    separator_work = max(0, len(values) - 1) * len(separator)
    charge_array(translator, max(1, len(values) + separator_work))
    parts = []
    for item in values:
        if type(item) is str:
            part = item
            charge_array(translator, len(part))
        elif type(item) is bool:
            part = "true" if item else "false"
            charge_array(translator, len(part))
        elif type(item) in (int, float):
            charge_array(translator, 24)
            part = _number_text(item)
        else:
            fail("List.join supports only strings, numbers and booleans")
        parts.append(part)
    # Each part and repeated separator was charged before text scanning/joining.
    output = separator.join(parts)
    if _json_string_size(output) > MAX_LIST_OUTPUT_BYTES:
        fail("List.join result exceeds the 1 MB output limit")
    return output
