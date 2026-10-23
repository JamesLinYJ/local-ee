"""Strict bounded neighborhood wire shared by compiler and native bridge."""
from __future__ import annotations

import json

MAX_BYTES = 32_768
MAX_OFFSETS = 1_089
OPERATIONS = frozenset({"mean", "min", "max", "median", "mode"})
FIELDS = {"v", "operation", "offsets", "iterations", "skip_masked"}


def _check(spec):
    if (type(spec) is not dict or set(spec) != FIELDS
            or type(spec["v"]) is not int or spec["v"] != 1):
        raise ValueError("Focal specification requires exactly v=1/operation/offsets/iterations/skip_masked")
    if type(spec["operation"]) is not str or spec["operation"] not in OPERATIONS:
        raise ValueError("Unsupported focal operation")
    if type(spec["iterations"]) is not int or not 1 <= spec["iterations"] <= 8:
        raise ValueError("Focal iterations must be an integer in 1..8")
    if type(spec["skip_masked"]) is not bool:
        raise ValueError("Focal skip_masked must be boolean")
    offsets = spec["offsets"]
    if type(offsets) is not list or not 1 <= len(offsets) <= MAX_OFFSETS:
        raise ValueError("Focal offsets require 1..1089 entries")
    previous = None
    for pair in offsets:
        if (type(pair) is not list or len(pair) != 2
                or any(type(x) is not int or not -32 <= x <= 32 for x in pair)):
            raise ValueError("Focal offsets require [dx,dy] integer pairs in -32..32")
        key = (pair[1], pair[0])
        if previous is not None and key <= previous:
            raise ValueError("Focal offsets must be unique and sorted by (dy,dx)")
        previous = key
    return spec


def _encode(spec):
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False)


def prepare_focal_spec(operation, offsets, iterations=1, skip_masked=True):
    if type(offsets) not in (list, tuple) or not 1 <= len(offsets) <= MAX_OFFSETS:
        raise ValueError("Focal offsets require 1..1089 entries")
    pairs = []
    for pair in offsets:
        if (type(pair) not in (list, tuple) or len(pair) != 2
                or any(type(x) is not int or not -32 <= x <= 32 for x in pair)):
            raise ValueError("Focal offsets require [dx,dy] integer pairs in -32..32")
        pairs.append(list(pair))
    pairs.sort(key=lambda pair: (pair[1], pair[0]))
    return _encode(_check({"v": 1, "operation": operation, "offsets": pairs,
                           "iterations": iterations, "skip_masked": skip_masked}))


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Focal specification contains duplicate keys")
        result[key] = value
    return result


def decode_focal_spec(text):
    if type(text) is not str or len(text) > MAX_BYTES or not text.isascii():
        raise ValueError("Focal specification must be canonical JSON text within 32768 ASCII bytes")
    try:
        spec = json.loads(text, object_pairs_hook=_object)
    except (ValueError, RecursionError) as error:
        raise ValueError("Focal specification is invalid JSON") from error
    _check(spec)
    if _encode(spec) != text:
        raise ValueError("Focal specification must be canonical JSON text")
    return spec


def focal_process_spec():
    cube = {"type": "object", "subtype": "raster-cube"}
    return {
        "id": "local_ee_focal", "experimental": True, "categories": ["cubes"],
        "summary": "Bounded Float64 raster neighborhood reduction",
        "description": (
            "One-band cube and canonical v1 spec: mean/min/max/median/mode, "
            "1..1089 [dx,dy] offsets within -32..32, 1..8 iterations and skip_masked. "
            "Rebuild cross-tile halos each iteration; retain grid and observation keys. "
            "Missing neighbors and empty windows are NoData. No missing tiles are synthesized. "
            "Existing key/cell limits plus neighbor/sort/buffer work limits apply. "
            "Nonzero radius must be smaller than both tile dimensions. Output is Float64 NaN band v. "
            "Smallest value wins mode ties. Google numerical equivalence is unverified."
        ),
        "parameters": [
            {"name": "data", "description": "One-band raster cube", "schema": cube},
            {"name": "spec", "description": "Canonical focal specification",
             "schema": {"type": "string", "maxLength": MAX_BYTES}},
        ],
        "returns": {"description": "Float64 raster cube", "schema": cube},
    }
