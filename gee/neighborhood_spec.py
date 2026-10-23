"""Canonical positive-weight neighborhood statistics protocol."""
from __future__ import annotations

import json
import math
import struct

MAX_BYTES = 32_768
MAX_COEFFICIENTS = 1_089
OPERATIONS = frozenset({"sum", "mean", "count", "min", "max", "variance", "stdDev",
                        "sampleVariance", "sampleStdDev", "product", "median", "mode"})
UNIT_WEIGHT_OPERATIONS = frozenset({"sampleVariance", "sampleStdDev", "product", "median", "mode"})
_FIELDS = {"coefficients", "operation", "skip_masked", "v"}
_HEX = frozenset("0123456789abcdef")


def _coordinate(value):
    return type(value) is int and -32 <= value <= 32


def _check(spec):
    if (type(spec) is not dict or set(spec) != _FIELDS
            or type(spec["v"]) is not int or spec["v"] != 1):
        raise ValueError("Neighborhood requires exactly coefficients, operation, skip_masked and v=1")
    operation = spec["operation"]
    if type(operation) is not str or operation not in OPERATIONS:
        raise ValueError("Unsupported neighborhood operation")
    if type(spec["skip_masked"]) is not bool:
        raise ValueError("Neighborhood skip_masked must be boolean")
    coefficients = spec["coefficients"]
    if type(coefficients) is not list or not 1 <= len(coefficients) <= MAX_COEFFICIENTS:
        raise ValueError("Neighborhood requires 1..1089 coefficients")
    previous = None
    for coefficient in coefficients:
        if (type(coefficient) is not list or len(coefficient) != 3
                or not all(_coordinate(x) for x in coefficient[:2])):
            raise ValueError("Neighborhood coefficients require [dx,dy,bits] offsets in -32..32")
        dx, dy, bits = coefficient
        if type(bits) is not str or len(bits) != 16 or not set(bits) <= _HEX:
            raise ValueError("Neighborhood weights require lowercase binary64 hex")
        weight = struct.unpack(">d", bytes.fromhex(bits))[0]
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError("Neighborhood weights must be strictly positive finite binary64 values")
        if operation in UNIT_WEIGHT_OPERATIONS and weight != 1.0:
            raise ValueError(f"Neighborhood {operation} requires unit weights")
        key = (dy, dx)
        if previous is not None and key <= previous:
            raise ValueError("Neighborhood coefficients must be unique and sorted by (dy,dx)")
        previous = key
    return spec


def _encode(spec):
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False)


def prepare_neighborhood_spec(operation, coefficients, skip_masked=True):
    if type(coefficients) not in (list, tuple) or not 1 <= len(coefficients) <= MAX_COEFFICIENTS:
        raise ValueError("Neighborhood requires a bounded list of 1..1089 coefficients")
    owned = []
    for coefficient in coefficients:
        if (type(coefficient) not in (list, tuple) or len(coefficient) != 3
                or not all(_coordinate(x) for x in coefficient[:2])):
            raise ValueError("Neighborhood coefficients require integer offsets in -32..32")
        dx, dy, weight = coefficient
        if type(weight) is not float or not math.isfinite(weight) or weight <= 0:
            raise ValueError("Neighborhood weights must be strictly positive finite floats")
        owned.append([dx, dy, struct.pack(">d", weight).hex()])
    owned.sort(key=lambda c: (c[1], c[0]))
    text = _encode(_check({"coefficients": owned, "operation": operation,
                           "skip_masked": skip_masked, "v": 1}))
    if len(text) > MAX_BYTES:
        raise ValueError("Neighborhood specification exceeds 32768 ASCII bytes")
    return text


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Neighborhood specification contains duplicate keys")
        result[key] = value
    return result


def decode_neighborhood_spec(text):
    if type(text) is not str or len(text) > MAX_BYTES or not text.isascii():
        raise ValueError("Neighborhood requires canonical JSON within 32768 ASCII bytes")
    try:
        spec = json.loads(text, object_pairs_hook=_object)
    except (ValueError, RecursionError) as error:
        raise ValueError("Neighborhood specification is invalid JSON") from error
    _check(spec)
    if _encode(spec) != text:
        raise ValueError("Neighborhood specification must use canonical compact JSON")
    return spec


def neighborhood_process_spec():
    cube = {"type": "object", "subtype": "raster-cube"}
    return {
        "id": "local_ee_neighborhood", "experimental": True, "categories": ["cubes"],
        "summary": "Bounded Float64 neighborhood statistics",
        "description": (
            "One-band cube with positive finite kernel coefficients and a named statistic. "
            "Valid neighbors contribute; missing/masked neighbors are omitted. No support yields NoData. "
            "skip_masked preserves masked centers; false may fill only existing source tiles. "
            "Sum retains coefficient scale; mean and population dispersion normalize valid weights. "
            "Count/min/max ignore positive magnitudes; sample dispersion, product, median and mode "
            "require unit weights. Preserve source grid and time; radius must be smaller than the tile. "
            "Key/cell/exact-arithmetic work caps apply; output v uses Float64 NaN. "
            "Fractional source masks and Google same-data equivalence remain unverified."
        ),
        "parameters": [
            {"name": "data", "description": "One-band raster cube", "schema": cube},
            {"name": "spec", "description": "Canonical neighborhood coefficient specification",
             "schema": {"type": "string", "maxLength": MAX_BYTES}},
        ],
        "returns": {"description": "Float64 raster cube", "schema": cube},
    }
