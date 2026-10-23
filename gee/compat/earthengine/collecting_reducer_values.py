"""Bounded recursive scans and detached copies for collecting reducers."""
from __future__ import annotations

import math

import numpy as np

from .array_values import MAX_ARRAY_CELLS, MAX_ARRAY_RANK, StaticArray
from .ir import fail


MAX_COLLECTING_ROWS = 1_000
MAX_COLLECTING_INPUTS = 32
MAX_COLLECTING_PROPERTIES = 10_000
MAX_COLLECTING_NAME_CHARS = 10_000
MAX_COLLECTING_DEPTH = 96
MAX_PUBLIC_BYTES = 1_000_000
MAX_TRANSLATOR_WORK = 50_000
MAX_ARRAY_INTEGER = 2**53


def _charge(translator, work: int, label: str) -> None:
    if (type(work) is not int or work < 0 or work > MAX_TRANSLATOR_WORK
            or translator.steps + work > MAX_TRANSLATOR_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps += work


def _wire_add(wire: list[int], amount: int, label: str) -> None:
    if amount < 0 or amount > MAX_PUBLIC_BYTES - wire[0]:
        fail(f"{label} exceeds the 1 MB public JSON size limit")
    wire[0] += amount


def _text(translator, value: str, wire: list[int], label: str,
          max_chars: int | None = None) -> int:
    """Preflight one json.dumps(..., ensure_ascii=True) string."""
    if type(value) is not str:
        fail(f"{label} must be a string")
    if max_chars is not None and len(value) > max_chars:
        fail(f"{label} exceeds the bounded {max_chars}-character limit")
    base = len(value) + 2
    _wire_add(wire, base, label)
    _charge(translator, base, label)
    size = base
    for character in value:
        code = ord(character)
        if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
            extra = 1
        elif code < 32 or code >= 127:
            extra = 5 if code <= 0xffff else 11
        else:
            extra = 0
        if extra:
            _wire_add(wire, extra, label)
            _charge(translator, extra, label)
            size += extra
    return size


def _integer_size(translator, value: int, wire: list[int], label: str) -> int:
    bits = value.bit_length()
    if bits > 3_400_000:
        fail(f"{label} exceeds the 1 MB public JSON size limit")
    # This upper bound avoids materializing decimal text during preflight.
    digits = max(1, math.ceil(bits * math.log10(2))) + int(value < 0)
    _wire_add(wire, digits, label)
    _charge(translator, 1 + digits, label)
    return digits


def _number(translator, value: int | float, wire: list[int], label: str) -> int:
    if type(value) is int:
        return _integer_size(translator, value, wire, label)
    if not math.isfinite(value):
        fail(f"{label} numbers must be finite")
    size = len(repr(value))
    _wire_add(wire, size, label)
    _charge(translator, 1 + size, label)
    return size


def _array_structure(shape: tuple[int, ...]) -> int:
    """List punctuation emitted by to_value and json.dumps defaults."""
    size = 0
    prefixes = 1
    for length in shape:
        size += prefixes * (2 + 2 * max(0, length - 1))
        prefixes *= length
    return size


def _scan_array(translator, value: StaticArray, wire: list[int]) -> int:
    data = value.data
    if (not isinstance(data, np.ndarray) or data.ndim > MAX_ARRAY_RANK
            or data.size > MAX_ARRAY_CELLS or data.dtype.kind not in "iuf"
            or data.dtype.itemsize > 8):
        fail("Collecting reducers support only bounded numeric ee.Array values")
    cells = int(data.size)
    structure = _array_structure(tuple(int(size) for size in data.shape))
    _wire_add(wire, structure, "Collecting reducer ee.Array output")
    _charge(translator, 1 + cells + structure, "Collecting reducer ee.Array scan")
    if data.dtype.kind in "iu":
        if data.dtype.kind == "u":
            unsafe_integer = np.any(data > MAX_ARRAY_INTEGER)
        else:
            unsafe_integer = np.any(
                (data < -MAX_ARRAY_INTEGER) | (data > MAX_ARRAY_INTEGER)
            )
        if bool(unsafe_integer.item()):
            fail("Collecting reducer ee.Array integers must be within the exact ±2^53 range")
    if not np.isfinite(data).all():
        fail("Collecting reducer ee.Array values must be finite")
    for item in data.flat:
        _number(translator, item.item(), wire, "Collecting reducer ee.Array values")
    return 1 + cells


def _scan_value(translator, value, wire: list[int], active: set[int], depth=0) -> int:
    """Validate a public finite value and return later owned-copy work."""
    if depth > MAX_COLLECTING_DEPTH:
        fail("Collecting reducer values exceed the depth 96 limit")
    kind = type(value)
    if value is None:
        _wire_add(wire, 4, "Collecting reducer values")
        _charge(translator, 1, "Collecting reducer value scan")
        return 1
    if kind is bool:
        _wire_add(wire, 4 if value else 5, "Collecting reducer values")
        _charge(translator, 1, "Collecting reducer value scan")
        return 1
    if kind in (int, float):
        _number(translator, value, wire, "Collecting reducer values")
        return 1
    if kind is str:
        _text(translator, value, wire, "Collecting reducer string value")
        return 1 + len(value)
    if kind is StaticArray:
        return _scan_array(translator, value, wire)
    if kind not in (dict, list):
        fail(f"Collecting reducers support finite JSON or ee.Array values, not {kind.__name__}")

    identity = id(value)
    if identity in active:
        fail("Collecting reducer values cannot contain cycles")
    if len(value) > MAX_COLLECTING_PROPERTIES:
        fail("Collecting reducer containers support at most 10000 entries")
    count = len(value)
    # Match json.dumps' default separators: comma-space and colon-space.
    structural = (2 + 2 * count + 2 * max(0, count - 1)
                  if kind is dict else 2 + 2 * max(0, count - 1))
    _wire_add(wire, structural, "Collecting reducer values")
    _charge(translator, 1 + count, "Collecting reducer container scan")
    copy_work = 1 + count
    active.add(identity)
    try:
        if kind is dict:
            for key, child in value.items():
                if type(key) is not str:
                    fail("Collecting reducer dictionaries require string keys")
                _text(translator, key, wire, "Collecting reducer dictionary key",
                      MAX_COLLECTING_NAME_CHARS)
                copy_work += len(key)
                copy_work += _scan_value(translator, child, wire, active, depth + 1)
        else:
            for child in value:
                copy_work += _scan_value(translator, child, wire, active, depth + 1)
        return copy_work
    finally:
        active.remove(identity)


def _copy_value(value):
    """Create a detached copy after the full copy walk has been charged."""
    kind = type(value)
    if kind is StaticArray:
        data = value.data.copy()
        data.flags.writeable = False
        return StaticArray(data)
    if kind is dict:
        return {key: _copy_value(child) for key, child in value.items()}
    if kind is list:
        return [_copy_value(child) for child in value]
    return value
