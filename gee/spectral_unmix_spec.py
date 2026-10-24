"""Canonical bounded wire contract for per-pixel spectral unmixing."""
from __future__ import annotations

import json
import math
import struct


MAX_BYTES = 8_192
MAX_AXIS = 8
PROCESS_ID = "local_ee_unmix"
_FIELDS = frozenset({"endmembers", "nonNegative", "sumToOne", "v"})
_HEX = frozenset("0123456789abcdef")


def _check(spec):
    if (type(spec) is not dict or set(spec) != _FIELDS
            or type(spec["v"]) is not int or spec["v"] != 1):
        raise ValueError("Spectral unmix specification requires exactly v1 and three fields")
    if type(spec["sumToOne"]) is not bool or type(spec["nonNegative"]) is not bool:
        raise ValueError("Spectral unmix constraints must be explicit booleans")
    endmembers = spec["endmembers"]
    if type(endmembers) is not list or not 1 <= len(endmembers) <= MAX_AXIS:
        raise ValueError("Spectral unmix components must be a list with 1..8 rows")
    columns = None
    for row in endmembers:
        if type(row) is not list or not 1 <= len(row) <= MAX_AXIS:
            raise ValueError("Each spectral endmember row must contain 1..8 bands")
        if columns is None:
            columns = len(row)
        elif len(row) != columns:
            raise ValueError("Spectral endmembers must form a rectangular matrix")
        for bits in row:
            if type(bits) is not str or len(bits) != 16 or not set(bits) <= _HEX:
                raise ValueError("Spectral coefficients require lowercase binary64 hex")
            if not math.isfinite(struct.unpack(">d", bytes.fromhex(bits))[0]):
                raise ValueError("Spectral coefficients must be finite binary64 values")
    return spec


def spectral_unmix_component_count(spec):
    """Return the validated component count from an already decoded spec."""
    return len(_check(spec)["endmembers"])


def spectral_unmix_input_count(spec):
    """Return the validated ordered input-band count from a decoded spec."""
    return len(_check(spec)["endmembers"][0])


def _encode(spec):
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _binary64_bits(value):
    if type(value) is bool or type(value) not in (int, float):
        raise ValueError("Spectral endmember coefficients must be finite real numbers")
    if type(value) is int and abs(value) > 2**53:
        raise ValueError("Spectral integer coefficients outside exact binary64 range are unsupported")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Spectral endmember coefficients must be finite real numbers")
    return struct.pack(">d", number).hex()


def prepare_spectral_unmix_spec(endmembers, sumToOne=False, nonNegative=False):
    """Encode component rows and explicit constraint flags as canonical v1 JSON."""
    if type(sumToOne) is not bool or type(nonNegative) is not bool:
        raise ValueError("Spectral unmix constraints must be booleans")
    if type(endmembers) not in (list, tuple) or not 1 <= len(endmembers) <= MAX_AXIS:
        raise ValueError("Spectral unmix requires 1..8 endmember components")
    rows = []
    columns = None
    for row in endmembers:
        if type(row) not in (list, tuple) or not 1 <= len(row) <= MAX_AXIS:
            raise ValueError("Each spectral endmember must contain 1..8 coefficients")
        if columns is None:
            columns = len(row)
        elif len(row) != columns:
            raise ValueError("Spectral endmembers must have a rectangular shape")
        rows.append([_binary64_bits(value) for value in row])
    value = _check({
        "v": 1, "endmembers": rows,
        "sumToOne": sumToOne, "nonNegative": nonNegative,
    })
    text = _encode(value)
    if len(text) > MAX_BYTES or not text.isascii():
        raise ValueError("Spectral unmix specification exceeds 8192 ASCII bytes")
    return text


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Spectral unmix specification contains duplicate keys")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("Spectral unmix specification contains a non-JSON constant")


def decode_spectral_unmix_spec(text):
    """Parse and revalidate the exact bounded canonical v1 wire."""
    if type(text) is not str or len(text) > MAX_BYTES or not text.isascii():
        raise ValueError("Spectral unmix specification requires at most 8192 ASCII bytes")
    try:
        value = json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_reject_constant,
        )
        _check(value)
    except (TypeError, RecursionError, json.JSONDecodeError) as error:
        raise ValueError("Spectral unmix specification is invalid JSON") from error
    if _encode(value) != text:
        raise ValueError("Spectral unmix specification must use canonical compact sorted-key JSON")
    return value


def spectral_unmix_process_spec():
    """Return the bounded OpenEO process contract for the native adapter."""
    cube = {"type": "object", "subtype": "raster-cube"}
    return {
        "id": PROCESS_ID,
        "experimental": True,
        "summary": "Bounded per-pixel spectral unmixing",
        "description": (
            "Apply a finite component-by-band endmember matrix to 1..8 ordered input "
            "bands. The v1 wire contains 1..8 components and finite binary64 coefficients. "
            "sumToOne and nonNegative are independent explicit constraints; their local "
            "solver behavior is defined by the native implementation. Outputs are Float64 "
            "bands unmix0.. in component order. Source grid, time and whole-input NoData "
            "are retained. This local naming and numerical policy do not establish Google parity."
        ),
        "categories": ["cubes"],
        "parameters": [
            {"name": "data", "description": "Ordered input bands band0..", "schema": cube},
            {"name": "spec", "description": "Canonical bounded v1 endmember specification",
             "schema": {"type": "string", "maxLength": MAX_BYTES}},
        ],
        "returns": {"description": "Float64 bands unmix0.. in component order", "schema": cube},
    }
