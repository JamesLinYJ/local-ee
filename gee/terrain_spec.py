"""Canonical finite Terrain operation and illumination contract."""
from __future__ import annotations

import json
import math
import struct

MAX_BYTES = 1_024
OPERATIONS = frozenset({"slope", "aspect", "hillshade"})
_FIELDS = {"azimuth", "elevation", "operation", "v"}
_HEX = frozenset("0123456789abcdef")
_DEFAULTS = {"azimuth": struct.pack(">d", 270.0).hex(),
             "elevation": struct.pack(">d", 45.0).hex()}


def _angle(value):
    if (type(value) not in (int, float)
            or type(value) is int and abs(value) > 2**53
            or not math.isfinite(value)):
        raise ValueError("Terrain illumination angles must be finite real numbers")
    normalized = float(value) % 360.0
    # Very small negative angles can round up to the excluded upper endpoint.
    if normalized == 360.0 or normalized == 0.0:
        normalized = 0.0
    return struct.pack(">d", normalized).hex()


def _check(spec):
    if (type(spec) is not dict or set(spec) != _FIELDS
            or type(spec["v"]) is not int or spec["v"] != 1):
        raise ValueError("Terrain requires exactly azimuth, elevation, operation and v=1")
    if type(spec["operation"]) is not str or spec["operation"] not in OPERATIONS:
        raise ValueError("Unsupported terrain operation")
    for name, default in _DEFAULTS.items():
        bits = spec[name]
        if (type(bits) is not str or len(bits) != 16 or not set(bits) <= _HEX
                or bits[0] not in "01234567"):
            raise ValueError("Terrain angles require nonnegative lowercase binary64 hex")
        value = struct.unpack(">d", bytes.fromhex(bits))[0]
        if not math.isfinite(value) or not 0 <= value < 360:
            raise ValueError("Terrain illumination angles must be normalized to [0,360)")
        if spec["operation"] != "hillshade" and bits != default:
            raise ValueError("Terrain slope/aspect require default illumination fields")
    return spec


def _encode(spec):
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False)


def prepare_terrain_spec(operation, azimuth=270.0, elevation=45.0):
    return _encode(_check({"azimuth": _angle(azimuth), "elevation": _angle(elevation),
                           "operation": operation, "v": 1}))


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Terrain specification contains duplicate keys")
        result[key] = value
    return result


def decode_terrain_spec(text):
    if type(text) is not str or len(text) > MAX_BYTES or not text.isascii():
        raise ValueError("Terrain requires canonical JSON within 1024 ASCII bytes")
    try:
        spec = json.loads(text, object_pairs_hook=_object)
    except (ValueError, RecursionError) as error:
        raise ValueError("Terrain specification is invalid JSON") from error
    _check(spec)
    if _encode(spec) != text:
        raise ValueError("Terrain specification must use canonical compact JSON")
    return spec


def terrain_process_spec():
    cube = {"type": "object", "subtype": "raster-cube"}
    return {
        "id": "local_ee_terrain", "experimental": True, "categories": ["cubes"],
        "summary": "Four-neighbor terrain derivatives on the actual source grid",
        "description": (
            "Single elevation band in metres; derive local east/north distances from actual "
            "cube CRS and grid using the documented WGS84 tangent-chord policy. All four "
            "neighbors and center must be valid. Slope/aspect are degrees; flat aspect is zero. "
            "Hillshade uses periodic illumination angles and rounded Lambert brightness0..255. "
            "Physical output v remains Float64 NaN, including integral hillshade, to preserve "
            "zero brightness and missing values. No implicit elevation scale conversion, "
            "source reprojection or Google equivalence. Key/cell/work limits apply."
        ),
        "parameters": [
            {"name": "data", "description": "One-band elevation raster cube in metres", "schema": cube},
            {"name": "spec", "description": "Canonical terrain operation specification",
             "schema": {"type": "string", "maxLength": MAX_BYTES}},
        ],
        "returns": {"description": "One-band Float64 raster cube", "schema": cube},
    }
