"""Canonical bounded projections for actual Smile RF explanations."""
from __future__ import annotations

import json
import math

from .sampling_spec import _parse, encode_spec


MAX_SPEC_BYTES = 16_384
MAX_SCHEMA = 8
MAX_TREES = 256
MAX_KEYS = 64
ROOT_KEYS = ("importance", "numberOfTrees", "outOfBagErrorEstimate")
VIEWS = frozenset({"explanation", "importance", "numberOfTrees",
                   "outOfBagErrorEstimate", "importance_value", "values",
                   "importance_values"})
_BASE_FIELDS = {"version", "schema", "trees", "view"}
_LIST_VIEWS = {"importance_value", "values", "importance_values"}


def _utf8_size(text, maximum):
    """Measure a string's UTF-8 size without allocating an encoded copy."""
    if type(text) is not str or len(text) > maximum:
        raise ValueError("RF explanation specification exceeds16384 UTF-8 bytes")
    size = 0
    for char in text:
        codepoint = ord(char)
        if codepoint <= 0x7F:
            size += 1
        elif codepoint <= 0x7FF:
            size += 2
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError("RF explanation specification must be valid UTF-8")
        elif codepoint <= 0xFFFF:
            size += 3
        else:
            size += 4
        if size > maximum:
            raise ValueError("RF explanation specification exceeds16384 UTF-8 bytes")
    return size


def _json_string_size(value):
    size = 2  # Opening and closing quote.
    for char in value:
        codepoint = ord(char)
        if char in {'"', "\\", "\b", "\t", "\n", "\f", "\r"}:
            size += 2
        elif codepoint < 0x20:
            size += 6  # Canonical JSON's \u00xx control escape.
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError("RF explanation specification must be valid UTF-8")
        elif codepoint <= 0x7F:
            size += 1
        elif codepoint <= 0x7FF:
            size += 2
        elif codepoint <= 0xFFFF:
            size += 3
        else:
            size += 4
    return size


def _canonical_json_size(value):
    """Measure this bounded spec's canonical JSON before serializing it."""
    size = 2  # Object braces.
    for index, (key, item) in enumerate(value.items()):
        if index:
            size += 1  # Comma.
        size += _json_string_size(key) + 1  # Key and colon.
        if type(item) is str:
            size += _json_string_size(item)
        elif type(item) is int:
            size += len(str(item))
        elif type(item) in (list, tuple):
            size += 2  # Array brackets.
            for item_index, child in enumerate(item):
                if item_index:
                    size += 1
                if type(child) is str:
                    size += _json_string_size(child)
                elif type(child) is int:
                    size += len(str(child))
                else:
                    raise ValueError("RF explanation specification has an invalid canonical value")
        else:
            raise ValueError("RF explanation specification has an invalid canonical value")
        if size > MAX_SPEC_BYTES:
            raise ValueError("RF explanation specification exceeds16384 UTF-8 bytes")
    return size


def _names(values, minimum, maximum, label):
    if (type(values) not in (list, tuple) or not minimum <= len(values) <= maximum
            or any(type(name) is not str or not name or len(name) > 256
                   or "." in name for name in values)
            or len(set(values)) != len(values)):
        raise ValueError(f"RF explanation {label} requires {minimum}..{maximum} unique flat names")
    return list(values)


def _check_spec(value):
    if (type(value) is not dict or len(value) not in (4, 5)
            or any(type(key) is not str or len(key) > 16 for key in value)
            or set(value) not in (_BASE_FIELDS, _BASE_FIELDS | {"keys"})
            or type(value.get("version")) is not int or value["version"] != 1):
        raise ValueError("RF explanation requires exact version1 projection fields")
    schema = _names(value["schema"], 1, MAX_SCHEMA, "schema")
    trees = value["trees"]
    if type(trees) is not int or not 1 <= trees <= MAX_TREES:
        raise ValueError("RF explanation trees must be an integer from1 through256")
    view = value["view"]
    if type(view) is not str or len(view) > 32 or view not in VIEWS:
        raise ValueError("Unsupported RF explanation projection view")
    if view in _LIST_VIEWS:
        keys = value.get("keys")
        if (type(keys) is not list or len(keys) > MAX_KEYS
                or any(type(key) is not str or len(key) > 256 for key in keys)):
            raise ValueError("RF explanation projection keys must be an ordered list of at most64 names")
        allowed = set(schema) if view == "importance_values" else set(ROOT_KEYS) if view == "values" else set(schema)
        if any(key not in allowed for key in keys):
            raise ValueError("RF explanation projection contains an unknown key")
        if view == "importance_value" and len(keys) != 1:
            raise ValueError("importance_value requires exactly one schema key")
    elif "keys" in value:
        raise ValueError("RF explanation keys are valid only for list/value projections")
    return value


def _encode(value):
    _check_spec(value)
    if _canonical_json_size(value) > MAX_SPEC_BYTES:
        raise ValueError("RF explanation specification exceeds16384 UTF-8 bytes")
    text = encode_spec(value)
    if len(text.encode("utf-8")) != _canonical_json_size(value):
        raise RuntimeError("RF explanation canonical-size preflight differs from JSON encoding")
    decode_explanation_spec(text)
    return text


def prepare_explanation_spec(schema, number_of_trees, view="explanation", keys=None):
    """Build a canonical, data-only projection for an actual RF model."""
    value = {"version": 1, "schema": _names(schema, 1, MAX_SCHEMA, "schema"),
             "trees": number_of_trees, "view": view}
    if keys is not None:
        if type(keys) not in (list, tuple) or len(keys) > MAX_KEYS:
            raise ValueError("RF explanation projection keys must be a list")
        value["keys"] = list(keys)
    return _encode(value)


def decode_explanation_spec(text):
    """Decode only bounded canonical JSON; duplicate object keys fail in _parse."""
    try:
        _utf8_size(text, MAX_SPEC_BYTES)
        return _check_spec(_parse(text))
    except UnicodeEncodeError as exc:
        raise ValueError("RF explanation specification must be valid UTF-8") from exc


def _get_spec(spec):
    return decode_explanation_spec(spec) if type(spec) is str else _check_spec(spec)


def _finite_number(value, *, nonnegative=False, unit_interval=False):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if type(value) is int and abs(value) > 2**53:
        valid = False
    if not valid or (nonnegative and value < 0) or (unit_interval and not 0 <= value <= 1):
        raise ValueError("RF explanation values must be finite and within their declared range")
    return value


def _owned_importance(value, schema):
    if type(value) is not dict or len(value) != len(schema):
        raise ValueError("RF explanation importance keys must match the model schema")
    keys = list(value)
    if (any(type(key) is not str or len(key) > 256 for key in keys)
            or set(keys) != set(schema)):
        raise ValueError("RF explanation importance keys must match the model schema")
    return {name: _finite_number(value[name], nonnegative=True) for name in schema}


def _owned_full(value, spec):
    if type(value) is not dict or len(value) != len(ROOT_KEYS):
        raise ValueError("RF explanation must contain exactly the three public fields")
    fields = list(value)
    if (any(type(key) is not str or len(key) > 32 for key in fields)
            or set(fields) != set(ROOT_KEYS)):
        raise ValueError("RF explanation must contain exactly the three public fields")
    importance = _owned_importance(value["importance"], spec["schema"])
    trees = value["numberOfTrees"]
    if type(trees) is not int or trees != spec["trees"]:
        raise ValueError("RF explanation tree count differs from its validated model")
    error = _finite_number(value["outOfBagErrorEstimate"], unit_interval=True)
    return {"importance": importance, "numberOfTrees": trees,
            "outOfBagErrorEstimate": error}


def project_explanation(full_value, spec):
    """Return one closed view, preserving requested key order and duplicates."""
    spec = _get_spec(spec)
    full = _owned_full(full_value, spec)
    view = spec["view"]
    if view == "explanation":
        return full
    if view == "importance":
        return full["importance"]
    if view in ROOT_KEYS[1:]:
        return full[view]
    if view == "importance_value":
        return full["importance"][spec["keys"][0]]
    if view == "values":
        return [_copy_public(full[key]) for key in spec["keys"]]
    if view == "importance_values":
        return [full["importance"][key] for key in spec["keys"]]
    raise ValueError("Unsupported RF explanation projection view")


def _copy_public(value):
    if type(value) is dict:
        return {key: _copy_public(child) for key, child in value.items()}
    if type(value) is list:
        return [_copy_public(child) for child in value]
    return value


def validate_explanation_value(value, spec):
    """Validate and own a projected public value without accepting opaque IR."""
    spec = _get_spec(spec)
    view = spec["view"]
    if view == "explanation":
        return _owned_full(value, spec)
    if view == "importance":
        return _owned_importance(value, spec["schema"])
    if view == "numberOfTrees":
        if type(value) is not int or value != spec["trees"]:
            raise ValueError("RF explanation tree count differs from its validated model")
        return value
    if view == "outOfBagErrorEstimate":
        return _finite_number(value, unit_interval=True)
    if view in {"importance_value", "importance_values"}:
        if view == "importance_values" and (type(value) is not list or len(value) != len(spec["keys"])):
            raise ValueError("RF explanation importance values differ from requested keys")
        values = [value] if view == "importance_value" else value
        checked = [_finite_number(item, nonnegative=True) for item in values]
        return checked[0] if view == "importance_value" else checked
    if view == "values":
        if type(value) is not list or len(value) != len(spec["keys"]):
            raise ValueError("RF explanation values differ from requested keys")
        result = []
        for key, item in zip(spec["keys"], value):
            if key == "importance":
                result.append(_owned_importance(item, spec["schema"]))
            elif key == "numberOfTrees":
                if type(item) is not int or item != spec["trees"]:
                    raise ValueError("RF explanation tree count differs from its validated model")
                result.append(item)
            else:
                result.append(_finite_number(item, unit_interval=True))
        return result
    raise ValueError("Unsupported RF explanation projection view")


def decode_native_explanation(text, spec):
    """Decode the bounded numeric envelope emitted by the trusted JVM factory."""
    spec = _get_spec(spec)
    if type(text) is not str or len(text) > 4096:
        raise ValueError("Native RF explanation exceeds its 4096-character limit")
    try:
        if len(text.encode("utf-8")) > 4096:
            raise ValueError("Native RF explanation exceeds its 4096-byte limit")

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("Native RF explanation contains duplicate keys")
                result[key] = value
            return result

        def constant(_):
            raise ValueError("Native RF explanation values must be finite JSON numbers")

        envelope = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (json.JSONDecodeError, RecursionError, UnicodeEncodeError) as exc:
        raise ValueError("Native RF explanation must be bounded JSON") from exc
    fields = {"version", "importance", "number_of_trees", "out_of_bag_error"}
    if (type(envelope) is not dict or len(envelope) != len(fields)
            or any(type(key) is not str or len(key) > 32 for key in envelope)
            or set(envelope) != fields
            or type(envelope["version"]) is not int or envelope["version"] != 1):
        raise ValueError("Native RF explanation requires the exact version1 numeric envelope")
    values = envelope["importance"]
    if type(values) is not list or len(values) != len(spec["schema"]):
        raise ValueError("Native RF importance length differs from the model schema")
    importance = {name: _finite_number(value, nonnegative=True)
                  for name, value in zip(spec["schema"], values)}
    trees = envelope["number_of_trees"]
    if type(trees) is not int or trees != spec["trees"]:
        raise ValueError("Native RF tree count differs from the validated model")
    error = _finite_number(envelope["out_of_bag_error"], unit_interval=True)
    return {"importance": importance, "numberOfTrees": trees,
            "outOfBagErrorEstimate": error}
