"""Bounded canonical convolution coefficients with exact binary64 weights."""
from __future__ import annotations

import json
import math
import struct

MAX_BYTES = 32_768
MAX_COEFFICIENTS = 1_089
_HEX = frozenset("0123456789abcdef")


def _coordinate(value):
    return type(value) is int and -32 <= value <= 32


def _check(spec):
    if (type(spec) is not dict or set(spec) != {"v", "coefficients"}
            or type(spec["v"]) is not int or spec["v"] != 1):
        raise ValueError("Convolution specification requires exactly v=1 and coefficients")
    coefficients = spec["coefficients"]
    if type(coefficients) is not list or not 1 <= len(coefficients) <= MAX_COEFFICIENTS:
        raise ValueError("Convolution requires 1..1089 coefficients")
    previous = None
    for coefficient in coefficients:
        if (type(coefficient) is not list or len(coefficient) != 3
                or not all(_coordinate(x) for x in coefficient[:2])):
            raise ValueError("Convolution coefficients require [dx,dy,bits] with integer offsets in -32..32")
        dx, dy, bits = coefficient
        if (type(bits) is not str or len(bits) != 16 or not set(bits) <= _HEX
                or bits == "8000000000000000"):
            raise ValueError("Convolution weights require canonical lowercase binary64 hex; negative zero is forbidden")
        weight = struct.unpack(">d", bytes.fromhex(bits))[0]
        if not math.isfinite(weight):
            raise ValueError("Convolution weights must be finite binary64 values")
        key = (dy, dx)
        if previous is not None and key <= previous:
            raise ValueError("Convolution coefficients must be unique and sorted by (dy,dx)")
        previous = key
    if (all(c[2] == "0000000000000000" for c in coefficients)
            and coefficients != [[0, 0, "0000000000000000"]]):
        raise ValueError("An all-zero convolution kernel requires the single zero center coefficient")
    return spec


def _encode(spec):
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False)


def prepare_convolve_spec(coefficients):
    if type(coefficients) not in (list, tuple) or not 1 <= len(coefficients) <= MAX_COEFFICIENTS:
        raise ValueError("Convolution requires a bounded list of 1..1089 coefficients")
    owned = []
    for coefficient in coefficients:
        if (type(coefficient) not in (list, tuple) or len(coefficient) != 3
                or not all(_coordinate(x) for x in coefficient[:2])):
            raise ValueError("Convolution coefficients require integer offsets in -32..32")
        dx, dy, weight = coefficient
        if type(weight) is not float or not math.isfinite(weight):
            raise ValueError("Convolution weights must be finite floats")
        # Signed zero has no effect on a linear combination and has one wire encoding.
        bits = struct.pack(">d", 0.0 if weight == 0.0 else weight).hex()
        owned.append([dx, dy, bits])
    owned.sort(key=lambda c: (c[1], c[0]))
    text = _encode(_check({"v": 1, "coefficients": owned}))
    if len(text) > MAX_BYTES:
        raise ValueError("Convolution specification exceeds 32768 ASCII bytes")
    return text


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Convolution specification contains duplicate keys")
        result[key] = value
    return result


def decode_convolve_spec(text):
    if type(text) is not str or len(text) > MAX_BYTES or not text.isascii():
        raise ValueError("Convolution specification requires canonical JSON within 32768 ASCII bytes")
    try:
        spec = json.loads(text, object_pairs_hook=_object)
    except (ValueError, RecursionError) as error:
        raise ValueError("Convolution specification is invalid JSON") from error
    _check(spec)
    if _encode(spec) != text:
        raise ValueError("Convolution specification must use canonical compact JSON")
    return spec


def convolve_process_spec():
    cube = {"type": "object", "subtype": "raster-cube"}
    return {
        "id": "local_ee_convolve", "experimental": True, "categories": ["cubes"],
        "summary": "Bounded Float64 raster convolution",
        "description": (
            "One-band cube and canonical v1 coefficients: 1..1089 [dx,dy,binary64_hex] entries, "
            "unique offsets within -32..32. Apply the kernel in its stored row/column orientation. "
            "Exact products and accumulation with one Float64 rounding; overflow rejects. "
            "Local mask policy: a masked center or missing nonzero-weight neighbor produces NoData; "
            "zero weights require no neighbor. No border renormalization or missing tile synthesis. "
            "Retain source grid and time. Positive halo radius must be smaller than both tile dimensions. "
            "Existing key/cell limits and bounded exact-arithmetic work apply. Output band v uses Float64 NaN. "
            "Google numerical and mask equivalence are unverified."
        ),
        "parameters": [
            {"name": "data", "description": "One-band raster cube", "schema": cube},
            {"name": "spec", "description": "Canonical convolution coefficient specification",
             "schema": {"type": "string", "maxLength": MAX_BYTES}},
        ],
        "returns": {"description": "Float64 raster cube", "schema": cube},
    }
