"""Canonical bounded v1 wire for actual integer values and closed Float64 operations."""
from __future__ import annotations

import json
import re
import struct

from .integer_values_contract import (
    check_constant, evaluate_integer_values, finite_number, validate_operation,
)


MAX_BYTES = 1024


def constant_operand(value):
    finite_number(value)
    return {"constant": struct.pack(">d", float(value)).hex()}


def _constant(encoded):
    if type(encoded) is not str or not re.fullmatch(r"[0-9a-f]{16}", encoded):
        raise ValueError("Integer image constant must be 16 lowercase binary64 hexadecimal digits")
    return finite_number(struct.unpack(">d", bytes.fromhex(encoded))[0])


def _check(spec):
    if (type(spec) is not dict or set(spec) != {"dtype", "op", "operands", "v"}
            or type(spec["v"]) is not int or spec["v"] != 1):
        raise ValueError("Integer image spec requires exactly dtype/op/operands/v1")
    arity = validate_operation(spec["op"], spec["dtype"])
    operands = spec["operands"]
    if type(operands) is not list or len(operands) != arity:
        raise ValueError(f"Integer image operation requires exactly {arity} operands")
    bands = set()
    for index, operand in enumerate(operands):
        if type(operand) is not dict:
            raise ValueError("Integer image operand requires exactly one band or constant")
        if set(operand) == {"band"}:
            band = operand["band"]
            if type(band) is not int or band not in (0, 1):
                raise ValueError("Integer image band index must be 0 or 1")
            bands.add(band)
        elif set(operand) == {"constant"}:
            check_constant(spec["op"], index, _constant(operand["constant"]))
        else:
            raise ValueError("Integer image operand requires exactly one band or constant")
    if not bands or bands != set(range(len(bands))):
        raise ValueError("Integer image band references must be contiguous from 0 and nonempty")
    return spec


def prepare_integer_values_spec(op, operands, dtype=None):
    spec = _check({"dtype": dtype, "op": op, "operands": operands, "v": 1})
    text = json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(text) > MAX_BYTES:
        raise ValueError("Integer image spec exceeds 1024 bytes")
    return text


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Integer image spec contains duplicate keys")
        result[key] = value
    return result


def decode_integer_values_spec(text):
    if type(text) is not str or len(text) > MAX_BYTES or not text.isascii():
        raise ValueError("Integer image spec requires at most 1024 ASCII bytes")
    try:
        spec = _check(json.loads(text, object_pairs_hook=_unique_object))
    except (TypeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("Integer image spec is invalid JSON") from error
    canonical = prepare_integer_values_spec(spec["op"], spec["operands"], spec["dtype"])
    if canonical != text:
        raise ValueError("Integer image spec must use canonical compact sorted-key JSON")
    return spec


def integer_values_process_spec():
    cube = {"type": "object", "subtype": "raster-cube"}
    return {
        "id": "local_ee_integer_values", "experimental": True,
        "summary": "Bounded integer-value operations and closed Float64 pixel math",
        "description": (
            "Canonical v1 specification over one or two ordered operand bands. "
            "Bit inputs/results must be integral within +/-2^53, signed shifts use counts0..63 "
            "without left-shift wrapping, bitCount counts64-bit two's complement. "
            "Integer casts clamp and truncate toward zero; int64 is limited to +/-2^53. "
            "Comparisons and closed core arithmetic preserve finite Float64 values and intersect operand masks. "
            "Arithmetic domain/overflow results become NoData; divide by zero returns0. "
            "Mod uses signed remainder and zero divisor becomes NoData; round uses local ties toward+infinity. "
            "Grid/time/key limits, decoded10M cells/tile and100M total, work100M/tile "
            "and1B total apply. Google dtype and full-service parity remain unverified."
        ),
        "categories": ["cubes"],
        "parameters": [
            {"name": "data", "description": "One or two ordered operand bands", "schema": cube},
            {"name": "spec", "description": "Canonical v1 integer image specification",
             "schema": {"type": "string", "maxLength": MAX_BYTES}},
        ],
        "returns": {"description": "One Float64 NaN NoData band v", "schema": cube},
    }
