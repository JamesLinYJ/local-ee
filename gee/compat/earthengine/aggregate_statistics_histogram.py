"""Precharged histogram key conversion with explicit collision rejection."""
from __future__ import annotations

import math

from .aggregate_statistics_values import (
    MAX_EXACT_INTEGER,
    MAX_PUBLIC_BYTES,
    _scalar,
    _json_string_size,
    charge,
)
from .ir import fail


def _histogram_key(value):
    if type(value) is str:
        return value, ("string", value)
    if type(value) is bool:
        return ("true" if value else "false"), ("boolean", value)
    if type(value) is int:
        if abs(value) > MAX_EXACT_INTEGER:
            fail("aggregate_histogram integer values must be within the exact ±2^53 range")
        return str(value), ("number", float(value))
    if type(value) is float and math.isfinite(value):
        if value == 0:
            return "0", ("number", 0.0)
        if value.is_integer() and abs(value) <= MAX_EXACT_INTEGER:
            return str(int(value)), ("number", value)
        return repr(value), ("number", value)
    fail("aggregate_histogram supports only scalar strings, booleans, and numbers")


def aggregate_histogram(translator, values):
    # Reserve the row walk before scalar validation, spelling, or hashing.
    charge(translator, 8 * len(values), "aggregate_histogram scan")

    # `counts` is the public result and keeps source insertion order. `entries`
    # retains typed identities so stringified-key collisions can be rejected
    # without treating every repeated value as a new serialized output key.
    counts = {}
    entries = {}
    output_size = 2  # `{}`
    for value in values:
        if value is None:
            continue
        value = _scalar(value, "aggregate_histogram")
        if type(value) is int:
            # Reserve a safe decimal-width bound before str() in _histogram_key.
            digits = max(1, math.ceil(value.bit_length() * math.log10(2)))
            charge(
                translator, digits + (1 if value < 0 else 0),
                "aggregate_histogram numeric spelling",
            )
        elif type(value) is float:
            # repr(binary64) is at most 24 ASCII characters.
            charge(translator, 24, "aggregate_histogram numeric spelling")
        elif type(value) is bool:
            # Boolean keys are the fixed strings "true" and "false".
            charge(translator, 6, "aggregate_histogram boolean spelling")

        key, identity = _histogram_key(value)

        # Reserve every key hash and lookup, including repeated keys, before
        # dictionary access. String hashing scans the string; numeric spelling
        # above separately reserves conversion before the key is created.
        charge(translator, len(key) + 1, "aggregate_histogram key hash and lookup")
        entry = entries.get(key)
        if entry is None:
            # This key will appear in the public result exactly once. Measure
            # and reserve that serialized growth before either dictionary grows.
            charge(translator, len(key) + 1, "aggregate_histogram output key scan")
            key_size = _json_string_size(key)
            # Match json.dumps defaults used at the public boundary: `: ` and
            # `, ` each occupy two bytes (commas occur only between entries).
            addition = key_size + 2 + 1 + (2 if counts else 0)
            if output_size + addition > MAX_PUBLIC_BYTES:
                fail("aggregate_histogram output exceeds the 1 MB public JSON limit")
            charge(translator, addition, "aggregate_histogram output")
            charge(translator, len(key) + 5, "aggregate_histogram unique key growth")
            output_size += addition
            entries[key] = [identity, 1, 1]
            counts[key] = 1
            continue

        if type(value) is str and entry[0][0] == "string":
            # Distinct string objects with equal content may require a full
            # character comparison after the typed-key lookup.
            charge(translator, len(value), "aggregate_histogram string identity comparison")
        if entry[0] != identity:
            fail("aggregate_histogram values collide after conversion to string keys")

        # Repeated inputs pay for the result-map update but not for another
        # serialized key. Account for count-width growth before mutating either
        # stored value so the 1 MB cap remains incremental and exact.
        charge(translator, 1, "aggregate_histogram count update")
        new_count = entry[1] + 1
        # Counts grow by exactly one; detect width changes without allocating
        # another decimal string for every occurrence.
        added_digits = int(new_count == 10 ** entry[2])
        new_width = entry[2] + added_digits
        if output_size + added_digits > MAX_PUBLIC_BYTES:
            fail("aggregate_histogram output exceeds the 1 MB public JSON limit")
        if added_digits:
            charge(translator, added_digits, "aggregate_histogram output")
            output_size += added_digits
        charge(translator, len(key) + 1, "aggregate_histogram result lookup/update")
        entry[1] = new_count
        entry[2] = new_width
        counts[key] = new_count
    return counts
