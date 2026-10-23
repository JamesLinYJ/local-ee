"""Bounded finite static Number.parse for pinned Earth Engine signatures."""
from __future__ import annotations

from decimal import Decimal, DecimalException
import math

from .array_core import MAX_ARRAY_WORK
from .ir import fail


NUMBER_PARSE_FUNCTIONS = frozenset({"Number.parse"})
MAX_PARSE_INPUT_CHARS = 256
_MAX_EXACT_INTEGER = 2**53
_MAX_EXACT_DECIMAL = Decimal(_MAX_EXACT_INTEGER)
_ASCII_WHITESPACE = " \t\n\r\v\f"


def _charge_input(translator, size):
    work = size + 1
    if work > MAX_ARRAY_WORK or translator.steps + work > MAX_ARRAY_WORK:
        fail("Number.parse exceeds the compilation work budget")
    translator.steps += work


def _radix(value):
    if type(value) is int:
        if not 2 <= value <= 36:
            fail("Number.parse radix must be an integer from 2 through 36")
        return value
    if (type(value) is float and math.isfinite(value)
            and 2 <= value <= 36 and int(value) == value):
        return int(value)
    fail("Number.parse radix must be an integer from 2 through 36")


def _bounds(text):
    start, end = 0, len(text)
    while start < end and text[start] in _ASCII_WHITESPACE:
        start += 1
    while end > start and text[end - 1] in _ASCII_WHITESPACE:
        end -= 1
    if start == end:
        fail("Number.parse input must contain a number")
    return start, end


def _digit(character):
    code = ord(character)
    if 48 <= code <= 57:
        return code - 48
    if 65 <= code <= 90:
        return code - 65 + 10
    if 97 <= code <= 122:
        return code - 97 + 10
    return -1


def _integer(text, start, end, radix):
    negative = False
    if text[start] in "+-":
        negative = text[start] == "-"
        start += 1
    if start == end:
        fail("Number.parse input is not a complete integer")
    value = 0
    for index in range(start, end):
        digit = _digit(text[index])
        if digit < 0 or digit >= radix:
            fail("Number.parse input is not valid for its radix")
        if value > (_MAX_EXACT_INTEGER - digit) // radix:
            fail("Number.parse integer exceeds the exact Float64 domain")
        value = value * radix + digit
    if negative:
        value = -value
        if value == 0:
            return -0.0
    return float(value)


def _decimal_syntax(text, start, end):
    index = start
    if text[index] in "+-":
        index += 1
    before = 0
    while index < end and "0" <= text[index] <= "9":
        before += 1
        index += 1
    after = 0
    if index < end and text[index] == ".":
        index += 1
        while index < end and "0" <= text[index] <= "9":
            after += 1
            index += 1
    if before + after == 0:
        return False
    if index < end and text[index] in "eE":
        index += 1
        if index < end and text[index] in "+-":
            index += 1
        exponent_start = index
        while index < end and "0" <= text[index] <= "9":
            index += 1
        if exponent_start == index:
            return False
    return index == end


def _is_exact_integer(value):
    _, digits, exponent = value.as_tuple()
    if not any(digits) or exponent >= 0:
        return True
    fractional_digits = -exponent
    if fractional_digits > len(digits):
        return False
    return all(digit == 0 for digit in digits[-fractional_digits:])


def _decimal(text, start, end):
    if not _decimal_syntax(text, start, end):
        fail("Number.parse input is not a complete decimal number")
    # The input is capped before this copy and Decimal conversion. It lets us
    # reject exact integers outside the Float64 domain before rounding them.
    try:
        exact = Decimal(text[start:end])
        if _is_exact_integer(exact) and exact.copy_abs() > _MAX_EXACT_DECIMAL:
            fail("Number.parse integer exceeds the exact Float64 domain")
        result = float(exact)
    except (DecimalException, OverflowError, ValueError):
        fail("Number.parse input is outside the finite decimal domain")
    if not math.isfinite(result):
        fail("Number.parse must produce a finite Number")
    # A decimal fraction near the integer precision boundary can round to an
    # integer that no longer preserves the supplied value. Keep that explicit.
    if (result.is_integer() and abs(result) >= _MAX_EXACT_INTEGER
            and exact != Decimal.from_float(result)):
        fail("Number.parse decimal exceeds the exact Float64 domain")
    # Float64 underflow to signed zero is accepted as the local decimal policy.
    return result


def invoke_number_parse(translator, name, arguments):
    """Parse a bounded decimal or radix integer into a finite static Number.

    Decimal literals use Python's correctly rounded Float64 conversion after
    strict ASCII lexing. Non-decimal radices accept complete signed integers
    only. This is a finite local subset; cloud service edge cases are unverified.
    """
    if name not in NUMBER_PARSE_FUNCTIONS:
        fail(f"Unsupported static Number parse: {name}")
    translator.allowed(arguments, {"input", "radix"})
    if "input" not in arguments:
        fail("Number.parse requires input")
    text = arguments["input"]
    if type(text) is not str:
        fail("Number.parse input must be a static String")
    if len(text) > MAX_PARSE_INPUT_CHARS:
        fail(f"Number.parse input exceeds {MAX_PARSE_INPUT_CHARS} characters")
    radix_value = arguments.get("radix")
    radix = 10 if radix_value is None else _radix(radix_value)
    _charge_input(translator, len(text))
    start, end = _bounds(text)
    if radix != 10:
        return _integer(text, start, end, radix)
    # Decimal integers are accumulated with an exact, bounded range check;
    # decimal fractions and exponent forms use the decimal path below.
    if all("0" <= text[index] <= "9" for index in range(start + (text[start] in "+-"), end)):
        return _integer(text, start, end, 10)
    return _decimal(text, start, end)
