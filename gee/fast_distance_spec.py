"""Canonical local policy for bounded fast pixel-distance transforms."""
from __future__ import annotations

import json

MAX_BYTES = 1024
MAX_NEIGHBORHOOD = 4096
METRICS = frozenset({"squared_euclidean", "manhattan", "chebyshev"})
_FIELDS = {"metric", "neighborhood", "v"}


def _check(spec):
    if (type(spec) is not dict or set(spec) != _FIELDS
            or type(spec["v"]) is not int or spec["v"] != 1):
        raise ValueError("Fast distance requires exactly metric, neighborhood and v=1")
    if (type(spec["metric"]) is not str or len(spec["metric"]) > 32
            or spec["metric"] not in METRICS):
        raise ValueError("Fast distance metric must be squared_euclidean, manhattan or chebyshev")
    if (type(spec["neighborhood"]) is not int
            or not 1 <= spec["neighborhood"] <= MAX_NEIGHBORHOOD):
        raise ValueError("Fast distance neighborhood must be an integer in 1..4096 pixels")
    return spec


def _encode(spec):
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False)


def prepare_fast_distance_spec(metric="squared_euclidean", neighborhood=256):
    return _encode(_check({"metric": metric, "neighborhood": neighborhood, "v": 1}))


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Fast distance specification contains duplicate keys")
        result[key] = value
    return result


def decode_fast_distance_spec(text):
    if type(text) is not str or len(text) > MAX_BYTES or not text.isascii():
        raise ValueError("Fast distance requires canonical JSON within 1024 ASCII bytes")
    try:
        spec = json.loads(text, object_pairs_hook=_object)
    except (ValueError, RecursionError) as error:
        raise ValueError("Fast distance specification is invalid JSON") from error
    _check(spec)
    if _encode(spec) != text:
        raise ValueError("Fast distance specification must use canonical compact JSON")
    return spec


def fast_distance_process_spec():
    cube = {"type": "object", "subtype": "raster-cube"}
    return {
        "id": "local_ee_fast_distance_transform", "experimental": True,
        "categories": ["cubes"], "summary": "Exact capped pixel-distance transform",
        "description": (
            "Local v1 policy: finite unmasked nonzero source cells are targets. "
            "Compute squared Euclidean, Manhattan or Chebyshev distance on the source grid. "
            "Neighborhood N is 1..4096 pixels (default256). Output v contains finite Int32 "
            "values capped at N*N for squared Euclidean or N otherwise, including when no "
            "target exists. Masked centers receive values; absent source keys remain absent. "
            "These exact integers are <=2^24 and can enter existing Float32 callbacks. "
            "Capped/no-target, masked-target and multiband policies lack Google same-data "
            "verification. Source, fragment, buffer, scratch and work limits apply."
        ),
        "parameters": [
            {"name": "data", "description": "One-band finite source raster cube", "schema": cube},
            {"name": "spec", "description": "Canonical versioned local distance policy",
             "schema": {"type": "string", "maxLength": MAX_BYTES}},
        ],
        "returns": {"description": "One-band Int32 raster cube", "schema": cube},
    }
