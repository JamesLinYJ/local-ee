"""Bounded local semantics for static Earth Engine String values.

String indexing and length use Python Unicode code points. Case conversion and
trim use Python's Unicode tables and whitespace rules. Non-ASCII parity with
Earth Engine is unverified. Numeric constructor values use Python's shortest
round-trip spelling, with an integral ``.0`` removed.
"""
from __future__ import annotations

import math

from .ir import fail
from .string_json import decode_json, encode_json


MAX_STATIC_STRING_WORK = 50_000
MAX_SAFE_INTEGER = 2**53
STRING_EXTRA_FUNCTIONS = frozenset({
    "String.equals", "String.index", "String.rindex", "String.slice",
    "String.toLowerCase", "String.toUpperCase", "String.trim",
    "String.encodeJSON", "String.decodeJSON",
})


def _required(arguments, name):
    if name not in arguments:
        fail(f"String operation requires {name}")
    return arguments[name]


def _string(value, label):
    if type(value) is not str:
        fail(f"{label} must be a string")
    return value


def _charge(translator, amount, label):
    if (amount < 0 or amount > MAX_STATIC_STRING_WORK
            or translator.steps + amount > MAX_STATIC_STRING_WORK):
        fail(f"{label} exceeds the shared string work budget")
    translator.steps += amount


def _number_text(translator, value):
    if type(value) not in (int, float):
        fail("String constructor supports only static strings and finite numbers")
    if type(value) is int:
        if value > MAX_SAFE_INTEGER or value < -MAX_SAFE_INTEGER:
            fail("String constructor requires an exact integer within 2^53")
        result = str(value)
        _charge(translator, len(result), "String numeric conversion")
        return result
    if not math.isfinite(value):
        fail("String constructor requires a finite Number")
    result = repr(value)
    if result.endswith(".0"):
        result = result[:-2]
    _charge(translator, len(result), "String numeric conversion")
    return result


def construct_string(translator, arguments):
    """Convert the supported static subset of the official String input."""
    if "input" not in arguments:
        fail("String constructor requires input")
    value = arguments["input"]
    if type(value) is str:
        return value
    return _number_text(translator, value)


def _integer_index(value, label):
    if type(value) is int:
        result = value
    elif type(value) is float and math.isfinite(value) and value.is_integer():
        if value > MAX_SAFE_INTEGER or value < -MAX_SAFE_INTEGER:
            fail(f"{label} must be within the exact integer range 2^53")
        result = int(value)
    else:
        fail(f"{label} must be an integer")
    if result > MAX_SAFE_INTEGER or result < -MAX_SAFE_INTEGER:
        fail(f"{label} must be within the exact integer range 2^53")
    return result


def _search(translator, text, pattern, last):
    if not pattern:
        return len(text) if last else 0
    if len(pattern) > len(text):
        return -1
    _charge(translator, len(text) + len(pattern), "String search")
    prefix = [0] * len(pattern)
    matched = 0
    for index in range(1, len(pattern)):
        while matched and pattern[index] != pattern[matched]:
            matched = prefix[matched - 1]
        if pattern[index] == pattern[matched]:
            matched += 1
        prefix[index] = matched
    found = -1
    matched = 0
    for index, character in enumerate(text):
        while matched and character != pattern[matched]:
            matched = prefix[matched - 1]
        if character == pattern[matched]:
            matched += 1
        if matched == len(pattern):
            found = index - len(pattern) + 1
            if not last:
                return found
            matched = prefix[matched - 1]
    return found


def _case_map(translator, text, upper):
    label = "String.toUpperCase" if upper else "String.toLowerCase"
    _charge(translator, len(text), label + " preflight")
    mapper = str.upper if upper else str.lower
    output_size = 0
    output_utf8 = 0
    for character in text:
        mapped = mapper(character)
        output_size += len(mapped)
        for result_character in mapped:
            code = ord(result_character)
            output_utf8 += (1 if code < 0x80 else 2 if code < 0x800 else
                            4 if code > 0xFFFF else 3)
        if output_size > MAX_STATIC_STRING_WORK or output_utf8 > 1_000_000:
            fail(f"{label} result exceeds the bounded string output size")
    _charge(translator, output_size, label + " result")
    return mapper(text)


def invoke_string(translator, name, arguments):
    """Evaluate a pinned basic String method with bounded type/work checks."""
    if name == "String.cat":
        translator.allowed(arguments, {"string1", "string2"})
        left = _string(_required(arguments, "string1"), "String.cat string1")
        right = _string(_required(arguments, "string2"), "String.cat string2")
        size = len(left) + len(right)
        _charge(translator, size, "String.cat")
        return left + right
    if name == "String.length":
        translator.allowed(arguments, {"string"})
        return len(_string(_required(arguments, "string"), "String.length input"))
    if name == "String.compareTo":
        translator.allowed(arguments, {"string1", "string2"})
        left = _string(_required(arguments, "string1"), "String.compareTo string1")
        right = _string(_required(arguments, "string2"), "String.compareTo string2")
        _charge(translator, min(len(left), len(right)), "String.compareTo")
        return (left > right) - (left < right)
    if name == "String.equals":
        translator.allowed(arguments, {"reference", "target"})
        reference = _string(_required(arguments, "reference"), "String.equals reference")
        target = _required(arguments, "target")
        if type(target) is not str:
            return False
        _charge(translator, min(len(reference), len(target)), "String.equals")
        return reference == target
    if name in {"String.index", "String.rindex"}:
        translator.allowed(arguments, {"target", "pattern"})
        target = _string(_required(arguments, "target"), name + " target")
        pattern = _string(_required(arguments, "pattern"), name + " pattern")
        return _search(translator, target, pattern, name == "String.rindex")
    if name == "String.slice":
        translator.allowed(arguments, {"string", "start", "end"})
        text = _string(_required(arguments, "string"), "String.slice string")
        start = _integer_index(_required(arguments, "start"), "String.slice start")
        end_value = arguments.get("end")
        end = None if end_value is None else _integer_index(end_value, "String.slice end")
        first, stop, _ = slice(start, end).indices(len(text))
        size = max(0, stop - first)
        _charge(translator, size, "String.slice")
        return text[first:stop]
    if name in {"String.toLowerCase", "String.toUpperCase"}:
        translator.allowed(arguments, {"string"})
        text = _string(_required(arguments, "string"), name + " input")
        return _case_map(translator, text, name == "String.toUpperCase")
    if name == "String.trim":
        translator.allowed(arguments, {"string"})
        text = _string(_required(arguments, "string"), "String.trim input")
        _charge(translator, len(text), "String.trim")
        start, end = 0, len(text)
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        _charge(translator, end - start, "String.trim result")
        return text[start:end]
    if name == "String.encodeJSON":
        translator.allowed(arguments, {"object"})
        return encode_json(translator, _required(arguments, "object"))
    if name == "String.decodeJSON":
        translator.allowed(arguments, {"string"})
        text = _string(_required(arguments, "string"), "String.decodeJSON input")
        return decode_json(translator, text)
    fail(f"Unsupported static String operation: {name}")
