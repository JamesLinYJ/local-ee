"""Bounded validation and input-size accounting for finite reducer values."""
from __future__ import annotations

import math

import numpy as np

from .aggregate_statistics_values import MAX_EXACT_INTEGER, MAX_PUBLIC_BYTES, charge
from .array_values import MAX_ARRAY_CELLS, MAX_ARRAY_RANK, StaticArray
from .ir import fail


MAX_DISCRETE_VALUES = 1_000
MAX_STATIC_CONTAINER_VALUES = 10_000
MAX_STATIC_DEPTH = 96


def _string_wire_size(translator, value, state, label):
    # Reserve character inspection before calculating JSON escaping or hashing.
    charge(translator, len(value) + 2, label)
    size = len(value) + 2
    for character in value:
        code = ord(character)
        if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
            size += 1
        elif code < 32 or code >= 127:
            size += 5 if code <= 0xffff else 11
    state[0] += size
    if state[0] > MAX_PUBLIC_BYTES:
        fail("Discrete reducer inputs exceed the 1 MB JSON size limit")


def _wire_add(state, size):
    state[0] += size
    if state[0] > MAX_PUBLIC_BYTES:
        fail("Discrete reducer inputs exceed the 1 MB JSON size limit")


def _scan_value(translator, value, active, wire, depth=0):
    """Validate and account one bounded static value, including ignored rows."""
    if depth > MAX_STATIC_DEPTH:
        fail("Discrete reducer inputs exceed the depth 96 limit")
    kind = type(value)
    if value is None:
        charge(translator, 1, "Discrete reducer input scan")
        _wire_add(wire, 4)
        return
    if kind is bool:
        charge(translator, 1, "Discrete reducer input scan")
        _wire_add(wire, 4 if value else 5)
        return
    if kind is int:
        charge(translator, max(1, value.bit_length()), "Discrete reducer integer scan")
        if value < -MAX_EXACT_INTEGER or value > MAX_EXACT_INTEGER:
            fail("Discrete reducer integers must be within the exact ±2^53 range")
        _wire_add(wire, len(str(value)))
        return
    if kind is float:
        charge(translator, 1, "Discrete reducer input scan")
        if not math.isfinite(value):
            fail("Discrete reducer inputs must contain finite numbers")
        _wire_add(wire, len(repr(value)))
        return
    if kind is str:
        _string_wire_size(translator, value, wire, "Discrete reducer string scan")
        return
    if kind is StaticArray:
        data = value.data
        if (not isinstance(data, np.ndarray) or data.size > MAX_ARRAY_CELLS
                or data.ndim > MAX_ARRAY_RANK or data.dtype.kind not in "iuf"):
            fail("Discrete reducer Array values must be bounded numeric arrays")
        cell_count = int(data.size)
        charge(translator, 1 + cell_count, "Discrete reducer Array scan")
        if data.dtype.kind in "iu":
            if data.dtype.kind == "u":
                unsafe_integer = np.any(data > MAX_EXACT_INTEGER)
            else:
                unsafe_integer = np.any(
                    (data < -MAX_EXACT_INTEGER) | (data > MAX_EXACT_INTEGER)
                )
            if bool(unsafe_integer.item()):
                fail("Discrete reducer Array integers exceed the exact ±2^53 range")
        if not np.isfinite(data).all():
            fail("Discrete reducer Array values must be finite")
        _wire_add(wire, 32 * cell_count + 2 + 2 * data.ndim)
        return
    if kind not in (list, dict):
        fail(f"Discrete reducers support finite static JSON or Array values, not {kind.__name__}")

    identity = id(value)
    if identity in active:
        fail("Discrete reducer inputs cannot contain cycles")
    if len(value) > MAX_STATIC_CONTAINER_VALUES:
        fail("Discrete reducer containers support at most 10000 entries")
    count = len(value)
    charge(translator, 1 + count, "Discrete reducer container scan")
    _wire_add(wire, 2 + max(0, count - 1) + (count if kind is dict else 0))
    active.add(identity)
    try:
        if kind is dict:
            for key, child in value.items():
                if type(key) is not str:
                    fail("Discrete reducer dictionaries require string keys")
                _string_wire_size(translator, key, wire, "Discrete reducer dictionary key scan")
                _scan_value(translator, child, active, wire, depth + 1)
        else:
            for child in value:
                _scan_value(translator, child, active, wire, depth + 1)
    finally:
        active.remove(identity)


def scan_inputs(translator, values):
    """Preflight at most 1000 values without copying their outer list."""
    if type(values) is not list or len(values) > MAX_DISCRETE_VALUES:
        fail("Discrete List reduction requires at most 1000 inline values")
    # Reserve the complete outer walk and result-list view before scanning rows.
    charge(translator, 1 + len(values), "Discrete reducer input scan")
    wire = [2 + max(0, len(values) - 1)]
    for value in values:
        _scan_value(translator, value, set(), wire)
