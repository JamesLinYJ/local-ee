"""Precharged histogram key conversion with explicit collision rejection."""
from __future__ import annotations

import math

from .aggregate_statistics_values import (
    MAX_EXACT_INTEGER,
    MAX_PUBLIC_BYTES,
    _public_scalar_size,
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
    # Reserve each scan before scalar validation, string hashing, or spelling.
    charge(translator, 8 * len(values), "aggregate_histogram scan")
    scalar_values = []
    for value in values:
        if value is None:
            continue
        value = _scalar(value, "aggregate_histogram")
        if type(value) is str:
            charge(translator, len(value), "aggregate_histogram string hash")
        elif type(value) in (int, float):
            charge(translator, 32, "aggregate_histogram numeric spelling")
        scalar_values.append(value)

    estimate = 2 + 10 * len(scalar_values)
    for value in scalar_values:
        if type(value) is str:
            estimate += _json_string_size(value) + 8
        elif type(value) is int:
            estimate += _public_scalar_size(value) + 8
        elif type(value) is float:
            # repr(binary64) is at most 24 ASCII characters; integer-like
            # values in the exact range have at most 16 decimal digits.
            estimate += 34
        else:
            estimate += 13
    if estimate > MAX_PUBLIC_BYTES:
        fail("aggregate_histogram output exceeds the 1 MB public JSON limit")
    charge(translator, estimate, "aggregate_histogram output")

    counts = {}
    identities = {}
    for value in scalar_values:
        key, identity = _histogram_key(value)
        previous = identities.get(key)
        if previous is not None and previous != identity:
            fail("aggregate_histogram values collide after conversion to string keys")
        identities[key] = identity
        counts[key] = counts.get(key, 0) + 1
    return counts
