"""Bounded, owned JSON values for static String.encodeJSON/decodeJSON."""
from __future__ import annotations

import json
import math

from .ir import fail


MAX_JSON_BYTES = 1_000_000
MAX_JSON_DEPTH = 96
MAX_JSON_WORK = 50_000
MAX_SAFE_INTEGER = 2**53


def _charge(translator, amount, label):
    if (amount < 0 or amount > MAX_JSON_WORK
            or translator.steps + amount > MAX_JSON_WORK):
        fail(f"{label} exceeds the 50000-step work budget")
    translator.steps += amount


def _utf8_width(character):
    code = ord(character)
    return 1 if code < 0x80 else 2 if code < 0x800 else 4 if code > 0xFFFF else 3


def _quoted_size(text):
    """Count bytes in the UTF-8 JSON spelling without creating an escaped copy."""
    size = 2
    for character in text:
        code = ord(character)
        if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
            size += 2
        elif code < 0x20 or 0xD800 <= code <= 0xDFFF:
            size += 6
        else:
            size += _utf8_width(character)
        if size > MAX_JSON_BYTES:
            fail("String JSON value exceeds the 1 MB UTF-8 output limit")
    return size


def _number_text(value):
    """Use shortest binary64 digits with ECMAScript-like decimal thresholds."""
    if type(value) is int:
        if value > MAX_SAFE_INTEGER or value < -MAX_SAFE_INTEGER:
            fail("String JSON integers must be exact within 2^53")
        return str(value)
    if not math.isfinite(value):
        fail("String JSON numbers must be finite")
    if value == 0:
        return "0"
    text = repr(value).lower()
    sign = ""
    if text.startswith("-"):
        sign, text = "-", text[1:]
    if "e" in text:
        mantissa, exponent_text = text.split("e", 1)
        exponent = int(exponent_text)
    else:
        mantissa, exponent = text, 0
    if "." in mantissa:
        decimal_position = mantissa.index(".") + exponent
        digits = mantissa.replace(".", "")
    else:
        decimal_position = len(mantissa) + exponent
        digits = mantissa
    if digits.endswith("0") and text.endswith(".0"):
        digits = digits[:-1]
    while len(digits) > 1 and digits.startswith("0"):
        digits = digits[1:]
        decimal_position -= 1
    if 1e-6 <= abs(value) < 1e21:
        if decimal_position <= 0:
            body = "0." + "0" * -decimal_position + digits
        elif decimal_position >= len(digits):
            body = digits + "0" * (decimal_position - len(digits))
        else:
            body = digits[:decimal_position] + "." + digits[decimal_position:]
        return sign + body
    scientific_exponent = decimal_position - 1
    fraction = "." + digits[1:] if len(digits) > 1 else ""
    exponent_sign = "+" if scientific_exponent >= 0 else "-"
    return (sign + digits[0] + fraction + "e" + exponent_sign
            + str(abs(scientific_exponent)))


def _scan_value(translator, value, depth, active):
    """Validate static JSON input and reserve its scan before iteration."""
    if depth > MAX_JSON_DEPTH:
        fail("String JSON value exceeds the depth limit of 96")
    kind = type(value)
    _charge(translator, 1, "String.encodeJSON")
    if value is None or kind is bool:
        return 4 if value is None else 4 if value else 5, 1
    if kind is str:
        _charge(translator, len(value), "String.encodeJSON string scan")
        return _quoted_size(value), 1 + len(value)
    if kind in (int, float):
        _charge(translator, 1, "String.encodeJSON number scan")
        number = _number_text(value)
        return len(number), 2
    if kind not in (list, dict):
        fail("String.encodeJSON supports only finite JSON primitives, lists, and dictionaries")
    identity = id(value)
    if identity in active:
        fail("String.encodeJSON cannot encode cyclic values")
    if len(value) > MAX_JSON_WORK:
        fail("String JSON value exceeds the 50000-step work budget")
    _charge(translator, len(value), "String.encodeJSON container scan")
    active.add(identity)
    try:
        byte_size = 2
        work = 1 + len(value)
        if kind is list:
            for index, child in enumerate(value):
                child_size, child_work = _scan_value(
                    translator, child, depth + 1, active
                )
                byte_size += child_size + (1 if index else 0)
                work += child_work
                if byte_size > MAX_JSON_BYTES:
                    fail("String JSON value exceeds the 1 MB UTF-8 output limit")
        else:
            for index, (key, child) in enumerate(value.items()):
                if type(key) is not str:
                    fail("String.encodeJSON dictionary keys must be strings")
                if key == "type" and child in ("Feature", "FeatureCollection"):
                    fail("String.encodeJSON cannot serialize internal Feature values")
                _charge(translator, len(key), "String.encodeJSON key scan")
                key_size = _quoted_size(key)
                child_size, child_work = _scan_value(
                    translator, child, depth + 1, active
                )
                byte_size += key_size + 1 + child_size + (1 if index else 0)
                work += len(key) + child_work
                if byte_size > MAX_JSON_BYTES:
                    fail("String JSON value exceeds the 1 MB UTF-8 output limit")
        return byte_size, work
    finally:
        active.remove(identity)


def _quote(text):
    parts = ['"']
    escapes = {
        '"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f",
        "\n": "\\n", "\r": "\\r", "\t": "\\t",
    }
    for character in text:
        code = ord(character)
        if character in escapes:
            parts.append(escapes[character])
        elif code < 0x20 or 0xD800 <= code <= 0xDFFF:
            parts.append(f"\\u{code:04x}")
        else:
            parts.append(character)
    parts.append('"')
    return "".join(parts)


def _write_value(value, parts):
    kind = type(value)
    if value is None:
        parts.append("null")
    elif kind is bool:
        parts.append("true" if value else "false")
    elif kind in (int, float):
        parts.append(_number_text(value))
    elif kind is str:
        parts.append(_quote(value))
    elif kind is list:
        parts.append("[")
        for index, child in enumerate(value):
            if index:
                parts.append(",")
            _write_value(child, parts)
        parts.append("]")
    else:
        parts.append("{")
        for index, (key, child) in enumerate(value.items()):
            if index:
                parts.append(",")
            parts.append(_quote(key))
            parts.append(":")
            _write_value(child, parts)
        parts.append("}")


def encode_json(translator, value):
    byte_size, work = _scan_value(translator, value, 0, set())
    if byte_size > MAX_JSON_BYTES:
        fail("String JSON value exceeds the 1 MB UTF-8 output limit")
    _charge(translator, work, "String.encodeJSON serialization")
    parts = []
    _write_value(value, parts)
    result = "".join(parts)
    return result


def _preflight_json_text(translator, text):
    if len(text) > MAX_JSON_WORK:
        fail("String.decodeJSON exceeds the 50000-step work budget")
    _charge(translator, len(text) * 2, "String.decodeJSON preflight and parse")
    utf8_size = 0
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        code = ord(character)
        if 0xD800 <= code <= 0xDFFF:
            utf8_size += 3
        else:
            utf8_size += _utf8_width(character)
        if utf8_size > MAX_JSON_BYTES:
            fail("String.decodeJSON exceeds the 1 MB UTF-8 input limit")
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                fail("String.decodeJSON exceeds the depth limit of 96")
        elif character in "]}":
            depth -= 1
    if depth != 0:
        # json.loads will report malformed syntax; this keeps the preflight's
        # state bounded and avoids a misleading successful nesting scan.
        fail("String.decodeJSON has unbalanced JSON containers")


def _parse_integer(text):
    digits = text[1:] if text.startswith("-") else text
    if len(digits) > 16:
        fail("String.decodeJSON integer exceeds the exact range 2^53")
    value = int(text)
    if value > MAX_SAFE_INTEGER or value < -MAX_SAFE_INTEGER:
        fail("String.decodeJSON integer exceeds the exact range 2^53")
    return value


def _parse_float(text):
    value = float(text)
    if not math.isfinite(value):
        fail("String.decodeJSON numbers must be finite")
    return value


def _reject_constant(text):
    fail(f"String.decodeJSON rejects non-finite JSON number {text}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("String.decodeJSON rejects duplicate object keys")
        if key == "type" and value in ("Feature", "FeatureCollection"):
            fail("String.decodeJSON cannot create internal Feature values")
        result[key] = value
    return result


def decode_json(translator, text):
    _preflight_json_text(translator, text)
    try:
        return json.loads(
            text,
            parse_int=_parse_integer,
            parse_float=_parse_float,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        fail(f"String.decodeJSON requires strict bounded JSON: {exc}")
