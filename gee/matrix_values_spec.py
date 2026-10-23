"""Canonical finite wire contract for bounded per-pixel matrix algorithms."""
from __future__ import annotations

import json
import math
import re
import struct


MAX_BYTES = 8192
MAX_CELLS = 64
MAX_AXIS = 8
OPERATIONS = frozenset({"solve", "inverse", "pinverse"})
PROCESS_ID = "local_ee_matrix_values"


def _check(spec):
    if (type(spec) is not dict
            or set(spec) != {"v", "op", "rows", "cols", "rhs_cols", "operands"}
            or type(spec["v"]) is not int or spec["v"] != 1):
        raise ValueError("Matrix values spec requires exactly v1/op/rows/cols/rhs_cols/operands")
    op, rows, cols, rhs = spec["op"], spec["rows"], spec["cols"], spec["rhs_cols"]
    if type(op) is not str or op not in OPERATIONS:
        raise ValueError("Unsupported matrix values operation")
    if any(type(size) is not int or not 1 <= size <= MAX_AXIS for size in (rows, cols)):
        raise ValueError("Matrix values rows and cols must be integers in1..8")
    if type(rhs) is not int or not (1 <= rhs <= MAX_AXIS if op == "solve" else rhs == 0):
        raise ValueError("Matrix values rhs_cols must be1..8 for solve or0 otherwise")
    if op == "inverse" and rows != cols:
        raise ValueError("Matrix inverse requires a square matrix")
    count = rows * cols + (rows * rhs if op == "solve" else 0)
    outputs = cols * (rhs if op == "solve" else rows)
    if count > MAX_CELLS or outputs > MAX_CELLS:
        raise ValueError("Matrix input and output must each fit the shared64-cell limit")
    operands = spec["operands"]
    if type(operands) is not list or len(operands) != count:
        raise ValueError("Matrix values operands must match the exact row-major input shape")
    bands = set()
    for operand in operands:
        if type(operand) is not dict:
            raise ValueError("Matrix operand requires one band or constant")
        if set(operand) == {"band"}:
            index = operand["band"]
            if type(index) is not int or not 0 <= index < MAX_CELLS:
                raise ValueError("Matrix input band index must be an integer in0..63")
            bands.add(index)
        elif set(operand) == {"constant"}:
            encoded = operand["constant"]
            if (type(encoded) is not str or not re.fullmatch("[0-9a-f]{16}", encoded)
                    or not math.isfinite(struct.unpack(">d", bytes.fromhex(encoded))[0])):
                raise ValueError("Matrix constant requires finite lowercase binary64 hexadecimal")
        else:
            raise ValueError("Matrix operand requires exactly one band or constant")
    if not bands or bands != set(range(len(bands))):
        raise ValueError("Matrix input band references must be nonempty and contiguous from0")
    return spec


def matrix_output_shape(spec):
    value = _check(spec)
    return value["cols"], value["rhs_cols"] if value["op"] == "solve" else value["rows"]


def matrix_input_bands(spec):
    value = _check(spec)
    return len({operand["band"] for operand in value["operands"] if "band" in operand})


def prepare_matrix_values_spec(op, rows, cols, rhs_cols, operands):
    value = _check({"v": 1, "op": op, "rows": rows, "cols": cols,
                    "rhs_cols": rhs_cols, "operands": operands})
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(text) > MAX_BYTES or not text.isascii():
        raise ValueError("Matrix values spec exceeds8192 ASCII bytes")
    return text


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Matrix values spec contains duplicate keys")
        result[key] = value
    return result


def decode_matrix_values_spec(text):
    if type(text) is not str or len(text) > MAX_BYTES or not text.isascii():
        raise ValueError("Matrix values spec requires at most8192 ASCII bytes")
    try:
        value = _check(json.loads(text, object_pairs_hook=_unique_object))
    except (TypeError, RecursionError, json.JSONDecodeError) as error:
        raise ValueError("Matrix values spec is invalid JSON") from error
    if prepare_matrix_values_spec(value["op"], value["rows"], value["cols"],
                                  value["rhs_cols"], value["operands"]) != text:
        raise ValueError("Matrix values spec must use canonical compact sorted-key JSON")
    return value


def matrix_values_process_spec():
    cube = {"type": "object", "subtype": "raster-cube"}
    return {
        "id": PROCESS_ID, "experimental": True,
        "summary": "Bounded per-pixel matrix solve, inverse and pseudoinverse",
        "description": (
            "Finite row-major fixed matrices, axes1..8 and input/output64 cells. "
            "Scaled SVD computes local minimum-norm solve/pseudoinverse; numerical "
            "singular inverse, any input NoData or nonfinite result masks the whole matrix. "
            "Source Infinity rejects. Ordered input bands and actual grid/time/key/cell/work "
            "limits are revalidated. Float64 outputs matrix0.. are not Google rank/dtype parity."
        ),
        "categories": ["cubes"],
        "parameters": [
            {"name": "data", "description": "Ordered actual operand bands band0..", "schema": cube},
            {"name": "spec", "description": "Canonical bounded v1 matrix specification",
             "schema": {"type": "string", "maxLength": MAX_BYTES}},
        ],
        "returns": {"description": "Row-major matrix0.. Float64 NaN NoData bands", "schema": cube},
    }
