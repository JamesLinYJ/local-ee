"""Bounded reduceColumns over literal inline FeatureCollections."""
from __future__ import annotations

import math

from .composed_reducers import (
    MAX_REDUCER_NAME_CHARS,
    MAX_REDUCER_INPUTS,
    MAX_REDUCER_OUTPUTS,
    normalize_reducer_spec,
)
from .ir import fail
from .table_reducers import MAX_TABLE_ROWS
from .composed_reducer_values import reduce_records
from .array_values import StaticArray


_MAX_PROPERTIES = 10_000
_MAX_JSON_BYTES = 1_000_000
_EXACT_INTEGER = 2**53


def _charge(translator, amount):
    if amount < 0 or translator.steps + amount > 50_000:
        fail("reduceColumns exceeds the shared 50000-step compilation work budget")
    translator.steps += amount


def _wire_add(wire, amount):
    if amount > _MAX_JSON_BYTES - wire[0]:
        fail("reduceColumns selected inputs exceed the 1 MB JSON size limit")
    wire[0] += amount


def _scan_string(translator, value, wire, label):
    if type(value) is not str:
        fail(f"{label} must be a string")
    if len(value) > MAX_REDUCER_NAME_CHARS:
        fail(f"{label} exceeds the bounded string length")
    base = len(value) + 2
    _charge(translator, base)
    _wire_add(wire, base)
    for character in value:
        code = ord(character)
        if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
            extra = 1
        elif code < 32 or code >= 127:
            extra = 5 if code <= 0xffff else 11
        else:
            extra = 0
        if extra:
            _charge(translator, extra)
            _wire_add(wire, extra)
    return wire[0]


def _integer_json_size(value):
    bits = abs(value).bit_length()
    if bits > 3_400_000:
        fail("reduceColumns selected inputs exceed the 1 MB JSON size limit")
    digits = max(1, math.ceil(bits * math.log10(2)))
    return digits + int(value < 0)


def _scan_json(translator, value, active, wire, depth=0):
    """Bound selected nested JSON before retaining it in the row table."""
    if depth > 96:
        fail("reduceColumns selected inputs exceed the depth 96 limit")
    kind = type(value)
    if kind is StaticArray:
        from .finite_reducer_scan import _scan_value

        _scan_value(translator, value, active, wire, depth)
        return
    if value is None:
        _charge(translator, 1)
        _wire_add(wire, 4)
        return
    if kind is bool:
        _charge(translator, 1)
        _wire_add(wire, 4 if value else 5)
        return
    if kind is int:
        size = _integer_json_size(value)
        _charge(translator, 1 + size)
        _wire_add(wire, size)
        return
    if kind is float:
        if not math.isfinite(value):
            fail("reduceColumns selected inputs must contain finite JSON numbers")
        size = len(repr(value))
        _charge(translator, 1 + size)
        _wire_add(wire, size)
        return
    if kind is str:
        _scan_string(translator, value, wire, "Selected string value")
        return
    if kind not in (dict, list):
        fail("reduceColumns supports finite JSON property values only")

    identity = id(value)
    if identity in active:
        fail("reduceColumns selected inputs cannot contain cyclic JSON")
    if kind is dict and len(value) > _MAX_PROPERTIES:
        fail("reduceColumns selected dictionaries support at most 10000 entries")
    count = len(value)
    _charge(translator, 1 + count)
    _wire_add(wire, 2 + max(0, count - 1) + (count if kind is dict else 0))
    active.add(identity)
    try:
        if kind is dict:
            for key, child in value.items():
                _scan_string(translator, key, wire, "Selected dictionary key")
                _scan_json(translator, child, active, wire, depth + 1)
        else:
            for child in value:
                _scan_json(translator, child, active, wire, depth + 1)
    finally:
        active.remove(identity)


def _selectors(translator, value, input_count):
    if type(value) is not list or len(value) != input_count or len(value) > MAX_REDUCER_INPUTS:
        fail(f"reduceColumns requires exactly {input_count} selectors")
    _charge(translator, 1 + len(value))
    for selector in value:
        if type(selector) is not str or not selector:
            fail("reduceColumns selectors must be non-empty property names")
        if len(selector) > MAX_REDUCER_NAME_CHARS:
            fail("reduceColumns selector exceeds the bounded name length")
        _charge(translator, len(selector))
        if "." in selector:
            fail("reduceColumns currently supports flat property selectors only")
    return tuple(value)


def _weights(translator, value):
    if value is None:
        return
    if type(value) is not list:
        fail("weightSelectors must be a list of property names or null")
    _charge(translator, 1 + len(value))
    for selector in value:
        _scan_string(translator, selector, [0], "weightSelectors entry")
    if value:
        fail("Non-empty weightSelectors are unsupported for composed table reducers")


def _inline_features(value):
    if (type(value) is not dict or value.get("type") != "FeatureCollection"
            or type(value.get("features")) is not list):
        fail("reduceColumns requires a literal inline FeatureCollection")
    features = value["features"]
    if len(features) > MAX_TABLE_ROWS:
        fail("reduceColumns supports at most 1000 inline features")
    return features


def _selected_rows(translator, features, selectors):
    # Reserve the bounded outer row walk before inspecting or copying rows.
    _charge(translator, 1 + len(features))
    wire = [0]
    rows = []
    for feature in features:
        if type(feature) is not dict or feature.get("type") != "Feature":
            fail("reduceColumns requires static inline Features")
        properties = feature.get("properties", {})
        if type(properties) is not dict or len(properties) > _MAX_PROPERTIES:
            fail("Feature properties must be a dictionary with at most 10000 entries")
        # Reserve key validation, selector lookup, and the row copy before the
        # corresponding dictionary scan or list allocation starts.
        _charge(translator, 1 + len(properties) + 2 * len(selectors))
        if any(type(key) is not str for key in properties):
            fail("Feature properties must be a string-keyed dictionary")
        selected = [properties.get(selector) for selector in selectors]
        for value in selected:
            _scan_json(translator, value, set(), wire)
        rows.append(selected)
    return rows


def reduce_columns(translator, arguments, reducer):
    """Compute basic scalar and regression reducers on an owned finite table."""
    translator.allowed(arguments, {"collection", "reducer", "selectors", "weightSelectors"})
    spec, nodes = normalize_reducer_spec(translator, reducer)
    if spec.input_count > MAX_REDUCER_INPUTS or len(spec.outputs) > MAX_REDUCER_OUTPUTS:
        fail("reduceColumns reducer exceeds bounded input or output arity")
    selectors = _selectors(translator, arguments.get("selectors"), spec.input_count)
    _weights(translator, arguments.get("weightSelectors"))
    features = _inline_features(arguments.get("collection"))
    rows = _selected_rows(translator, features, selectors)
    return reduce_records(
        translator, rows, spec, normalized=True, prevalidated=nodes,
    )
