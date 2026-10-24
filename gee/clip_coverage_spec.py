"""Canonical bounded wire for local great-circle polygon cell coverage.

The wire is an internal compiler/native contract.  It does not claim parity
with Earth Engine's rasterizer or boundary-cell quantizer.
"""
from __future__ import annotations

import json
import math


PROCESS_ID = "local_ee_clip_coverage"
MAX_POLYGONS = 1_000
MAX_RINGS = 1_000
MAX_POSITIONS = 10_000
MAX_SPEC_BYTES = 1_000_000
_FIELDS = frozenset({"model", "polygons", "version"})


def _check(value):
    if (type(value) is not dict or set(value) != _FIELDS
            or type(value["version"]) is not int or value["version"] != 1
            or type(value["model"]) is not str
            or value["model"] != "great-circle"):
        raise ValueError("Clip coverage requires the canonical great-circle v1 fields")
    polygons = value["polygons"]
    if type(polygons) is not list or not 1 <= len(polygons) <= MAX_POLYGONS:
        raise ValueError("Clip coverage requires 1..1000 polygons")

    rings = positions = 0
    longitudes = []
    for polygon in polygons:
        if type(polygon) is not list or not polygon:
            raise ValueError("Clip coverage polygons require one or more rings")
        rings += len(polygon)
        if rings > MAX_RINGS:
            raise ValueError("Clip coverage exceeds 1000 total rings")
        for ring in polygon:
            if type(ring) is not list or len(ring) < 4:
                raise ValueError("Clip coverage rings require at least four closed positions")
            positions += len(ring)
            if positions > MAX_POSITIONS:
                raise ValueError("Clip coverage exceeds 10000 positions including closures")
            first = ring[0]
            if (type(first) is not list or len(first) != 2
                    or any(type(number) is not float for number in first)):
                raise ValueError("Clip coverage positions require Float64 [longitude, latitude]")
            if ring[-1] != first:
                raise ValueError("Clip coverage rings must close with an exact first-position copy")
            for position in ring:
                if (type(position) is not list or len(position) != 2
                        or any(type(number) is not float for number in position)):
                    raise ValueError("Clip coverage positions require Float64 [longitude, latitude]")
                longitude, latitude = position
                if (not math.isfinite(longitude) or not math.isfinite(latitude)
                        or not -180.0 <= longitude <= 180.0
                        or not -90.0 < latitude < 90.0):
                    raise ValueError("Clip coverage positions must be finite nonpolar WGS84 coordinates")
                longitudes.append(longitude)
    if not longitudes or max(longitudes) - min(longitudes) >= 180.0:
        raise ValueError("Clip coverage rejects a global longitude span of 180 degrees or more")
    return value


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def prepare_clip_coverage_spec(geometry):
    """Encode an already freshly validated Polygon/MultiPolygon as sorted JSON."""
    if not isinstance(geometry, dict):
        raise ValueError("Clip coverage requires a decoded Polygon or MultiPolygon")
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Polygon":
        source_polygons = [coordinates]
    elif kind == "MultiPolygon":
        source_polygons = coordinates
    else:
        raise ValueError("Clip coverage supports Polygon and MultiPolygon only")

    polygons = []
    for source_polygon in source_polygons:
        polygon = []
        for source_ring in source_polygon:
            ring = [[float(position[0]), float(position[1])]
                    for position in source_ring]
            if ring[-1] != ring[0]:
                ring.append(ring[0].copy())
            polygon.append(ring)
        polygons.append(polygon)
    value = _check({"version": 1, "model": "great-circle", "polygons": polygons})
    text = _encode(value)
    if len(text.encode("utf-8")) > MAX_SPEC_BYTES:
        raise ValueError("Clip coverage specification exceeds 1000000 UTF-8 bytes")
    return text


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Clip coverage specification contains duplicate keys")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("Clip coverage specification contains a non-JSON constant")


def decode_clip_coverage_spec(text):
    """Parse and independently validate the canonical v1 geometry payload."""
    if type(text) is not str:
        raise ValueError("Clip coverage requires bounded canonical ASCII JSON")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("Clip coverage requires bounded canonical ASCII JSON") from error
    if len(encoded) > MAX_SPEC_BYTES:
        raise ValueError("Clip coverage specification exceeds 1000000 UTF-8 bytes")
    if not text.isascii():
        raise ValueError("Clip coverage requires bounded canonical ASCII JSON")
    try:
        value = json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_reject_constant,
        )
        _check(value)
    except (TypeError, RecursionError, json.JSONDecodeError) as error:
        raise ValueError("Clip coverage specification is invalid JSON") from error
    if _encode(value) != text:
        raise ValueError("Clip coverage specification must use sorted compact canonical JSON")
    return value


def clip_coverage_process_spec():
    """Describe the local fraction producer and its narrow accuracy boundary."""
    cube = {"type": "object", "subtype": "raster-cube"}
    return {
        "id": PROCESS_ID,
        "experimental": True,
        "summary": "Great-circle polygon cell coverage weights",
        "description": (
            "Compute an independent Float64 coverage weight for each actual input-grid cell. "
            "Raw NoData produces valid zero and finite raw data produces the projected-cell "
            "area fraction covered by the great-circle Polygon or MultiPolygon. The closed "
            "v1 geometry uses EPSG:4326 coordinates, even/odd interiors, nonpolar bounds, "
            "less than 180 degrees of global longitude span, at most 1000 polygons/rings, "
            "10000 closed coordinate positions and 1000000 UTF-8 bytes. Local edge subdivision "
            "is bounded by a 0.25 degree maximum arc and a 1e-6 pixel projected chord tolerance "
            "with at most 32 levels. These are bounded local numerical rules, not a formal "
            "coverage error certificate or Google's boundary-cell quantizer. All existing "
            "cell, observation and grid limits remain in force."
        ),
        "categories": ["cubes"],
        "parameters": [
            {"name": "data", "description": "One actual science band and its grid", "schema": cube},
            {"name": "spec", "description": "Canonical closed great-circle Polygon/MultiPolygon v1 JSON",
             "schema": {"type": "string", "maxLength": MAX_SPEC_BYTES}},
        ],
        "returns": {"description": "One independent Float64 coverage-weight band named v", "schema": cube},
    }


__all__ = [
    "MAX_POLYGONS", "MAX_POSITIONS", "MAX_RINGS", "MAX_SPEC_BYTES",
    "PROCESS_ID", "clip_coverage_process_spec", "decode_clip_coverage_spec",
    "prepare_clip_coverage_spec",
]
