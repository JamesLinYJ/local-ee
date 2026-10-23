"""Bounded validation and ownership helpers for static EE dictionaries."""
from __future__ import annotations

import json
import math

import numpy as np

from .array_core import MAX_ARRAY_CELLS, MAX_ARRAY_RANK, StaticArray
from .ir import fail


MAX_STATIC_VALUES = 10_000
MAX_STATIC_DEPTH = 96
MAX_STATIC_WORK = 50_000
MAX_STATIC_BYTES = 1_000_000


def charge(translator, amount=1):
    """Reserve compiler work before scanning, allocating, or copying values."""
    if amount < 0 or translator.steps + amount > MAX_STATIC_WORK:
        fail("Static Dictionary operation exceeds the compilation work budget")
    translator.steps += amount


def _string_bytes(value):
    size = len(value) + 2
    for character in value:
        code = ord(character)
        if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
            size += 1
        elif code < 32 or code >= 127:
            size += 5 if code <= 0xffff else 11
    return size


def _number_bytes(value):
    if type(value) is int:
        if abs(value) > 2**53:
            fail("Static Dictionary integers must be exact Float64 values")
    elif type(value) is float:
        if not math.isfinite(value):
            fail("Static Dictionary numbers must be finite")
    else:
        fail("Static Dictionary values must contain finite real numbers")
    return len(json.dumps(value, allow_nan=False))


def _array_list_bytes(shape):
    """JSON list punctuation emitted by StaticArray.to_value()."""
    size = 0
    prefixes = 1
    for dimension in shape:
        size += prefixes * (2 + 2 * max(0, dimension - 1))
        prefixes *= dimension
    return size


def _measure(translator, value, *, active=None, depth=0, byte_limit=MAX_STATIC_BYTES):
    """Validate a finite JSON/Array value and return (work, public JSON bytes).

    Every node and string/array scan is charged before it starts. The size
    accounting matches public_values.public_value, including escaped strings.
    """
    active = set() if active is None else active
    if depth > MAX_STATIC_DEPTH:
        fail("Static Dictionary value exceeds the nesting limit")
    charge(translator)
    work = 1

    if value is None:
        payload = 4
    elif type(value) is bool:
        payload = 4 if value else 5
    elif type(value) in (int, float):
        payload = _number_bytes(value)
    elif type(value) is str:
        charge(translator, len(value))
        work += len(value)
        payload = _string_bytes(value)
    elif type(value) is StaticArray:
        data = value.data
        if not isinstance(data, np.ndarray):
            fail("Static Dictionary arrays require a NumPy-backed ee.Array")
        if (data.ndim > MAX_ARRAY_RANK or data.size > MAX_ARRAY_CELLS
                or any(length > MAX_ARRAY_CELLS for length in data.shape)
                ):
            fail("Static Dictionary arrays exceed 10000 cells or rank 8")
        if data.dtype.kind not in "iuf":
            fail("Static Dictionary arrays must contain real numeric values")
        list_nodes = sum(math.prod(data.shape[:axis]) for axis in range(data.ndim))
        charge(translator, int(data.size) + list_nodes)
        work += int(data.size) + list_nodes
        numeric_bytes = 0
        for scalar in data.flat:
            numeric_bytes += _number_bytes(scalar.item())
            if numeric_bytes > byte_limit:
                fail("Static Dictionary value exceeds 1 MB")
        payload = _array_list_bytes(data.shape) + numeric_bytes
    elif type(value) in (list, dict):
        identity = id(value)
        if identity in active:
            fail("Static Dictionary values cannot contain cycles")
        if len(value) > MAX_STATIC_VALUES:
            fail("Static Dictionary containers support at most 10000 entries")
        active.add(identity)
        try:
            if type(value) is list:
                payload = 2 + 2 * max(0, len(value) - 1)
                for item in value:
                    child_work, child_bytes = _measure(
                        translator, item, active=active, depth=depth + 1,
                        byte_limit=max(0, byte_limit - payload),
                    )
                    work += child_work
                    payload += child_bytes
                    if payload > byte_limit:
                        fail("Static Dictionary value exceeds 1 MB")
            else:
                payload = 2 + 2 * len(value) + 2 * max(0, len(value) - 1)
                for key, item in value.items():
                    key_work, key_bytes = _measure(
                        translator, key, active=active, depth=depth + 1,
                        byte_limit=max(0, byte_limit - payload),
                    )
                    if type(key) is not str:
                        fail("Static Dictionary keys must be strings")
                    work += key_work
                    payload += key_bytes
                    child_work, child_bytes = _measure(
                        translator, item, active=active, depth=depth + 1,
                        byte_limit=max(0, byte_limit - payload),
                    )
                    work += child_work
                    payload += child_bytes
                    if payload > byte_limit:
                        fail("Static Dictionary value exceeds 1 MB")
        finally:
            active.remove(identity)
    else:
        fail(f"Static Dictionary does not support {type(value).__name__} values")

    if payload > byte_limit:
        fail("Static Dictionary value exceeds 1 MB")
    return work, payload


def require_dictionary(translator, value, label="dictionary"):
    if type(value) is not dict:
        fail(f"{label} must be a static Dictionary")
    work, _ = _measure(translator, value)
    return work


def require_string(translator, value, label):
    if type(value) is not str:
        fail(f"{label} must be a string")
    work, _ = _measure(translator, value)
    return work


def require_string_list(translator, value, label):
    if type(value) is not list or len(value) > MAX_STATIC_VALUES:
        fail(f"{label} must be a list of at most 10000 strings")
    work, _ = _measure(translator, value)
    charge(translator, len(value))
    if any(type(item) is not str for item in value):
        fail(f"{label} must contain only strings")
    return work


def measure_entries(translator, entries, *, byte_limit=MAX_STATIC_BYTES):
    """Preflight an output dictionary plan before constructing its nested copy."""
    charge(translator, 1 + len(entries))
    work = 1 + len(entries)
    payload = 2
    if len(entries) > MAX_STATIC_VALUES:
        fail("Computed Dictionary exceeds 10000 entries")
    for index, (key, value) in enumerate(entries):
        key_work, key_bytes = _measure(
            translator, key, byte_limit=max(0, byte_limit - payload),
        )
        value_work, value_bytes = _measure(
            translator, value,
            byte_limit=max(0, byte_limit - payload - key_bytes - 2),
        )
        work += key_work + value_work
        payload += 2 + (2 if index else 0) + key_bytes + value_bytes
        if payload > byte_limit:
            fail("Computed Dictionary exceeds 1 MB")
    return work, payload


def clone_value(value):
    """Copy a value after _measure and charge have established its bounds."""
    if type(value) is StaticArray:
        result = StaticArray(value.data.copy())
        result.data.flags.writeable = False
        return result
    if type(value) is list:
        return [clone_value(item) for item in value]
    if type(value) is dict:
        return {key: clone_value(item) for key, item in value.items()}
    return value


def clone_entries(entries):
    return {key: clone_value(value) for key, value in entries}


def natural_keys(translator, dictionary):
    """Return the pinned API's documented natural ordering of string keys."""
    count = len(dictionary)
    levels = max(1, math.ceil(math.log2(max(2, count))))
    charge(translator, count)
    comparison_work = sum(len(key) for key in dictionary) * levels + count * levels
    charge(translator, comparison_work)
    return sorted(dictionary)
