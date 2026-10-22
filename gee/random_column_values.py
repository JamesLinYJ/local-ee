"""Typed row-key hashing for local deterministic uniform and normal columns.

This versioned local algorithm is not a Google RNG equivalence claim. Numeric
keys use their actual binary64 value, so integral int/float keys agree.
"""
from __future__ import annotations

import hashlib
import math
import struct

from .random_column_spec import validate_random_column_spec


_DOMAIN = b"local-ee/randomColumn/sha256-rowkeys-v1\0"


def _charge(callback, amount):
    if callback is not None:
        callback(amount)


def _options(spec, charge):
    # Inspect only bounded name slots before reserving their encoding work.
    # Malformed or oversized shapes fail validation without encoding them.
    work = 32
    if type(spec) is dict:
        keys = spec.get("row_keys")
        if type(keys) is list and len(keys) <= 64:
            for name in [spec.get("column_name"), *keys]:
                if type(name) is str and len(name) <= 256:
                    work += 6 * len(name)
    _charge(charge, work)
    validate_random_column_spec(spec)


def _frame(value, charge):
    if type(value) is str:
        if len(value) > 4096:
            raise ValueError("randomColumn string row keys exceed4096 characters")
        _charge(charge, 5 + 4 * len(value))  # before UTF-8 allocation and hashing
        try:
            return b"s", value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("randomColumn row keys must be valid UTF-8") from exc
    if type(value) is bool:
        _charge(charge, 6)
        return b"b", bytes([int(value)])
    try:
        valid = (type(value) in (int, float) and math.isfinite(value)
                 and abs(value) <= 2**53)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("randomColumn row keys must be non-null finite scalar values; integer abs<=2^53")
    _charge(charge, 13)
    number = float(value)
    return b"n", struct.pack(">d", 0.0 if number == 0 else number)


def _value(feature, spec, charge):
    if type(feature) is not dict or type(feature.get("properties")) is not dict:
        raise ValueError("randomColumn requires actual Feature properties")
    properties = feature["properties"]
    _charge(charge, len(_DOMAIN) + 12 + len(spec["row_keys"]))
    digest = hashlib.sha256()
    digest.update(_DOMAIN)
    digest.update(spec["seed"].to_bytes(8, "big", signed=True))
    digest.update(len(spec["row_keys"]).to_bytes(4, "big"))
    for name in spec["row_keys"]:
        if name in properties:
            value = properties[name]
        elif name == "system:index" and "id" in feature:
            value = feature["id"]
        else:
            raise ValueError(f"randomColumn row key is missing: {name}; supply explicit rowKeys")
        tag, payload = _frame(value, charge)
        digest.update(tag)
        digest.update(len(payload).to_bytes(4, "big"))
        digest.update(payload)
    raw = digest.digest()
    first = int.from_bytes(raw[:8], "big")
    if spec["distribution"] == "uniform":
        return (first >> 11) * (2.0 ** -53)
    u1 = ((first >> 12) + 0.5) * (2.0 ** -52)
    u2 = (int.from_bytes(raw[8:16], "big") >> 11) * (2.0 ** -53)
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def random_value(feature, spec, charge=None):
    _options(spec, charge)
    return _value(feature, spec, charge)


def apply_random_column(features, spec, charge=None):
    """Return immutable row copies; sampled callers charge their deep copies too."""
    _options(spec, charge)
    if type(features) is not list or len(features) > 1000:
        raise ValueError("randomColumn supports at most1000 features")
    output = []
    for feature in features:
        if type(feature) is not dict or type(feature.get("properties")) is not dict:
            raise ValueError("randomColumn requires actual Feature properties")
        # Reserve both dict copies before constructing either output object.
        _charge(charge, len(feature) + len(feature["properties"]) + 3)
        value = _value(feature, spec, charge)
        output.append({**feature, "properties": {**feature["properties"], spec["column_name"]: value}})
    return output
