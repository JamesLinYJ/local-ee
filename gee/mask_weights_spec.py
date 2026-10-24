"""Closed contracts for reading independent raster-mask weights.

These projections produce ordinary numeric bands.  They do not turn a
weight-bearing scientific image into an ordinary NoData-only raster.
"""
from __future__ import annotations

import json


MASK_WEIGHT_ARITIES = {
    "validity": 1,
    "result_value": 1,
    "update": 2,
    "apply": 2,
}
MAX_SPEC_CHARS = 128


def mask_weights_spec(operation):
    if type(operation) is not str or operation not in MASK_WEIGHT_ARITIES:
        raise ValueError("Unsupported mask-weight operation")
    return json.dumps({"op": operation, "v": 1}, sort_keys=True, separators=(",", ":"))


def decode_mask_weights_spec(text):
    if type(text) is not str or len(text) > MAX_SPEC_CHARS or not text.isascii():
        raise ValueError("Mask weights require bounded canonical ASCII JSON")
    try:
        value = json.loads(text)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("Invalid mask-weight specification") from error
    if (type(value) is not dict or set(value) != {"op", "v"}
            or type(value["v"]) is not int or value["v"] != 1
            or type(value["op"]) is not str or value["op"] not in MASK_WEIGHT_ARITIES
            or text != mask_weights_spec(value["op"])):
        raise ValueError("Mask weights require a supported canonical v1 specification")
    return value


def mask_weights_process_spec():
    cube = {"type": "object", "subtype": "raster-cube"}
    return {
        "id": "local_ee_mask_weights", "experimental": True,
        "summary": "Read and compose independent finite mask weights",
        "description": (
            "Closed validity, finite-result, update and apply projections on the actual "
            "aligned raster grid. validity reads one source band as finite=1, NoData=0 "
            "and rejects Infinity; result_value preserves a finite arithmetic result and "
            "maps NaN or either Infinity to NoData. update reads old weight and new mask value, replacing "
            "only at nonzero old weights; apply reads a value and independent weight and "
            "masks only zero weights. Weights must be finite in [0,1]; new-mask NoData is "
            "zero. Scientific values are never multiplied by weights. Output is one Float64 "
            "v band; grid, observation keys and all existing key/cell limits remain, with "
            "67108864 cell-operation work. "
            "This is not a spherical rasterizer or Google numerical-equivalence claim."
        ),
        "categories": ["cubes"],
        "parameters": [
            {"name": "data", "description": "One or two ordered operand bands", "schema": cube},
            {"name": "spec", "description": "Canonical closed v1 operation JSON", "schema": {"type": "string"}},
        ],
        "returns": {"description": "One Float64 numeric v band", "schema": cube},
    }
