"""Canonical bounded pixel-distance contract for compiler and trusted engine."""
from __future__ import annotations

import json
import math
import struct

MAX_BYTES = 1024
MAX_RADIUS = 16
METRICS = frozenset({"euclidean", "manhattan", "chebyshev"})
_FIELDS = {"metric", "radius", "skip_masked", "v"}
_HEX = frozenset("0123456789abcdef")


def _check(spec):
    if (type(spec) is not dict or set(spec) != _FIELDS
            or type(spec["v"]) is not int or spec["v"] != 1):
        raise ValueError("Distance requires exactly metric, radius, skip_masked and v=1")
    if type(spec["metric"]) is not str or spec["metric"] not in METRICS:
        raise ValueError("Distance requires euclidean, manhattan or chebyshev")
    if type(spec["skip_masked"]) is not bool:
        raise ValueError("Distance skip_masked must be a boolean")
    bits = spec["radius"]
    if (type(bits) is not str or len(bits) != 16 or not set(bits) <= _HEX
            or bits[0] not in "01234567"):
        raise ValueError("Distance radius requires nonnegative lowercase binary64 hex")
    radius = struct.unpack(">d", bytes.fromhex(bits))[0]
    if not math.isfinite(radius) or not 0 <= radius <= MAX_RADIUS:
        raise ValueError("Distance radius must be in 0..16 pixels")
    return spec


def _encode(spec):
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False)


def prepare_distance_spec(metric, radius, skip_masked=True):
    if (type(radius) not in (int, float) or not 0 <= radius <= MAX_RADIUS
            or not math.isfinite(radius)):
        raise ValueError("Distance radius must be a finite number in 0..16 pixels")
    # Canonical positive zero; all other binary64 bits retain their exact value.
    bits = struct.pack(">d", float(radius) if radius else 0.0).hex()
    return _encode(_check({"metric": metric, "radius": bits,
                           "skip_masked": skip_masked, "v": 1}))


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Distance specification contains duplicate keys")
        result[key] = value
    return result


def decode_distance_spec(text):
    if type(text) is not str or len(text) > MAX_BYTES or not text.isascii():
        raise ValueError("Distance requires canonical JSON within 1024 ASCII bytes")
    try:
        spec = json.loads(text, object_pairs_hook=_object)
    except (ValueError, RecursionError) as error:
        raise ValueError("Distance specification is invalid JSON") from error
    _check(spec)
    if _encode(spec) != text:
        raise ValueError("Distance specification must use canonical compact JSON")
    return spec


def distance_process_spec():
    cube = {"type": "object", "subtype": "raster-cube"}
    return {
        "id": "local_ee_distance", "experimental": True, "categories": ["cubes"],
        "summary": "Nearest valid nonzero pixel within a bounded metric radius",
        "description": (
            "Single-band Float64 pixel distance on the actual source grid. Euclidean, "
            "Manhattan or Chebyshev search in 0..16 pixels; no implicit resampling. "
            "Masked neighbors are not targets; skip_masked controls the output center. "
            "No target within the metric radius gives NaN NoData; targets give zero. "
            "Output v preserves existing keys and time slices. Source/buffer/work caps "
            "apply. Metre kernels and Google same-data parity are not implemented."
        ),
        "parameters": [
            {"name": "data", "description": "One-band source raster cube", "schema": cube},
            {"name": "spec", "description": "Canonical distance metric/radius specification",
             "schema": {"type": "string", "maxLength": MAX_BYTES}},
        ],
        "returns": {"description": "One-band Float64 raster cube", "schema": cube},
    }
