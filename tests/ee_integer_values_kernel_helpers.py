"""Independent Python oracle and deterministic fixtures for integer-value tiles."""
from __future__ import annotations

import json
import math
import struct
import sys
from typing import Any


MAX_SAFE_INTEGER = 1 << 53
MASK_64 = (1 << 64) - 1
CAST_RANGES = {
    "int8": (-128, 127),
    "uint8": (0, 255),
    "int16": (-32768, 32767),
    "uint16": (0, 65535),
    "int32": (-(1 << 31), (1 << 31) - 1),
    "uint32": (0, (1 << 32) - 1),
    "int64": (-MAX_SAFE_INTEGER, MAX_SAFE_INTEGER),
}
OPERATIONS = (
    "bit_and", "bit_or", "bit_xor", "bit_not", "left_shift", "right_shift",
    "bit_count", "cast", "eq", "neq", "lt", "lte", "gt", "gte",
)


def binary64_hex(value: float | int) -> str:
    """Encode the exact IEEE-754 payload used by the versioned native wire."""
    return struct.pack(">d", float(value)).hex()


def _decode_value(value: str) -> float | None:
    if value == "NaN":
        return None
    if value == "Infinity":
        return math.inf
    if value == "-Infinity":
        return -math.inf
    return float.fromhex(value)


def _encode_value(value: float | int | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NaN"
    return float(value).hex()


def _band(index: int) -> dict[str, int]:
    return {"band": index}


def _constant(value: float | int) -> dict[str, str]:
    return {"constant": binary64_hex(value)}


def canonical_spec(operation: str, operands: list[dict[str, Any]],
                   dtype: str | None = None) -> str:
    """Return the strict v1 sorted, compact native wire representation."""
    return json.dumps({"dtype": dtype, "op": operation, "operands": operands, "v": 1},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _as_integer(value: float, label: str = "bit input") -> int:
    if not math.isfinite(value) or value != math.trunc(value):
        raise ValueError(f"{label} must be finite and integral")
    integer = int(value)
    if not -MAX_SAFE_INTEGER <= integer <= MAX_SAFE_INTEGER:
        raise ValueError(f"{label} exceeds the exact Float64 integer range")
    return integer


def _cast(value: float, dtype: str) -> float:
    if not math.isfinite(value):
        raise ValueError("cast input must be finite")
    minimum, maximum = CAST_RANGES[dtype]
    if dtype == "int64":
        truncated = math.trunc(value)
        if not -MAX_SAFE_INTEGER <= truncated <= MAX_SAFE_INTEGER:
            raise ValueError("int64 cast result exceeds the exact Float64 integer range")
        return float(truncated)
    clamped = min(max(value, float(minimum)), float(maximum))
    return float(math.trunc(clamped))


def _evaluate(operation: str, values: list[float], dtype: str | None) -> float:
    left = values[0]
    if operation in {"eq", "neq", "lt", "lte", "gt", "gte"}:
        right = values[1]
        matched = {
            "eq": left == right,
            "neq": left != right,
            "lt": left < right,
            "lte": left <= right,
            "gt": left > right,
            "gte": left >= right,
        }[operation]
        return 1.0 if matched else 0.0
    if operation == "cast":
        assert dtype is not None
        return _cast(left, dtype)
    integer = _as_integer(left)
    if operation == "bit_not":
        result = ~integer
    elif operation == "bit_count":
        return float((integer & MASK_64).bit_count())
    elif operation in {"left_shift", "right_shift"}:
        shift = _as_integer(values[1], "shift count")
        if not 0 <= shift <= 63:
            raise ValueError("shift count must be in 0..63")
        result = integer << shift if operation == "left_shift" else integer >> shift
    else:
        right = _as_integer(values[1])
        result = {
            "bit_and": integer & right,
            "bit_or": integer | right,
            "bit_xor": integer ^ right,
        }[operation]
    if not -MAX_SAFE_INTEGER <= result <= MAX_SAFE_INTEGER:
        raise ValueError(f"{operation} result exceeds the exact Float64 integer range")
    return float(result)


def reference(case: dict[str, Any]) -> list[float | None]:
    """Evaluate a fixture case with Python integers and IEEE-754 comparisons."""
    wire = json.loads(case["spec"])
    operands = wire["operands"]
    bands = [[_decode_value(value) for value in band] for band in case["bands"]]
    width = len(bands[0])
    if any(len(band) != width for band in bands):
        raise ValueError("fixture bands must have matching widths")
    result: list[float | None] = []
    for col in range(width):
        values: list[float] = []
        valid = True
        for operand in operands:
            if "band" in operand:
                value = bands[operand["band"]][col]
                if value is None:
                    valid = False
                    break
                values.append(value)
            else:
                values.append(struct.unpack(">d", bytes.fromhex(operand["constant"]))[0])
        if not valid:
            result.append(None)
        else:
            result.append(_evaluate(wire["op"], values, wire["dtype"]))
    return result


def _case(name: str, operation: str, operands: list[dict[str, Any]],
          bands: list[list[float | int | None]], *, dtype: str | None = None,
          input_type: str = "double") -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": name,
        "spec": canonical_spec(operation, operands, dtype),
        "input_type": input_type,
        "bands": [[_encode_value(value) for value in band] for band in bands],
    }
    row["expected"] = [_encode_value(value) for value in reference(row)]
    return row


def _invalid_tile(name: str, operation: str, operands: list[dict[str, Any]],
                  bands: list[list[float | int | None]], *, dtype: str | None = None,
                  input_type: str = "double") -> dict[str, Any]:
    return {
        "name": name,
        "spec": canonical_spec(operation, operands, dtype),
        "input_type": input_type,
        "bands": [[_encode_value(value) for value in band] for band in bands],
    }


def _invalid_masked_constant(name: str, operation: str, constant: float | int) -> dict[str, Any]:
    return {
        "name": name,
        "spec": canonical_spec(operation, [_band(0), _constant(constant)]),
        "input_type": "double",
        "bands": [["NaN", "NaN"]],
    }


def _invalid_specs() -> list[str]:
    valid = canonical_spec("bit_and", [_band(0), _band(1)])
    encoded_fraction = binary64_hex(0.5)
    encoded_too_large = binary64_hex(MAX_SAFE_INTEGER + 2)
    encoded_infinity = "7ff0000000000000"
    return [
        "",
        "{",
        "null",
        "[]",
        valid[:-1],
        valid + " ",
        valid + " []",
        valid.replace("\"dtype\":null,", "\"extra\":0,\"dtype\":null,"),
        valid.replace("\"dtype\":null,", "\"dtype\":null,\"op\":\"bit_and\",", 1),
        valid.replace("\"v\":1", "\"v\":true"),
        valid.replace("\"v\":1", "\"v\":1.0"),
        valid.replace("\"v\":1", "\"v\":2"),
        valid.replace("\"op\":\"bit_and\"", "\"op\":\"unknown\""),
        canonical_spec("bit_not", [_band(0), _band(1)]),
        canonical_spec("bit_and", [_band(0)]),
        canonical_spec("bit_and", [_constant(1), _constant(2)]),
        canonical_spec("bit_and", [_band(0)], "int8"),
        canonical_spec("cast", [_band(0)]),
        canonical_spec("cast", [_band(0)], "float32"),
        canonical_spec("cast", [_band(0)], "uint64"),
        canonical_spec("bit_and", [{"band": 2}, _band(0)]),
        canonical_spec("bit_and", [{"band": 1}, _constant(1)]),
        canonical_spec("bit_and", [{"band": True}, _constant(1)]),
        canonical_spec("bit_and", [{"band": 0.0}, _constant(1)]),
        canonical_spec("bit_and", [_band(0), {"band": 1, "constant": binary64_hex(1)}]),
        canonical_spec("bit_and", [_band(0), {"other": 1}]),
        canonical_spec("bit_and", [_band(0), {"constant": "ABCDEF0123456789"}]),
        canonical_spec("bit_and", [_band(0), {"constant": "000000000000000"}]),
        canonical_spec("bit_and", [_band(0), {"constant": encoded_infinity}]),
        canonical_spec("bit_and", [_band(0), {"constant": encoded_fraction}]),
        canonical_spec("bit_and", [_band(0), {"constant": encoded_too_large}]),
        canonical_spec("left_shift", [_band(0), _constant(0.5)]),
        canonical_spec("right_shift", [_band(0), _constant(-1)]),
        canonical_spec("left_shift", [_band(0), _constant(64)]),
        valid[:-1] + "," + " " * 1024,
        valid + "雪",
    ]


def make_fixture() -> dict[str, Any]:
    """Return reproducible positive, masked, overflow, and strict-wire controls."""
    min_subnormal = math.ulp(0.0)
    max_float = sys.float_info.max
    cases = [
        _case("bit-and-high-bits-and-negative-sentinels", "bit_and",
              [_band(0), _constant((1 << 53) - 1)],
              [[(1 << 53), (1 << 40) + 17, (1 << 31) + 3, -128,
                -(1 << 31), None, -(1 << 53)]]),
        _case("bit-or-high-bits", "bit_or", [_band(0), _band(1)],
              [[1 << 31, 1 << 40, 1 << 53, -128, -(1 << 31), None],
               [1 << 40, 7, 0, 255, 0, 3]]),
        _case("bit-xor-wide-and-signed", "bit_xor", [_band(0), _constant(0x55)],
              [[(1 << 40) + 0x55, -128, -(1 << 31), (1 << 53) - 1, None]]),
        _case("bit-not-negative-sentinels-and-domain-edge", "bit_not", [_band(0)],
              [[-128, -(1 << 31), -(1 << 53), 0, None]]),
        _case("left-shift-signed-and-count-boundaries", "left_shift", [_band(0), _band(1)],
              [[-1, -2, 1, 1, 1, -(1 << 40), None],
               [53, 40, 0, 31, 53, 13, 1]]),
        _case("right-shift-arithmetic-and-large-counts", "right_shift", [_band(0), _band(1)],
              [[-1, -3, -(1 << 53), 1 << 53, -128, 0, None],
               [63, 1, 63, 53, 7, 0, 2]]),
        _case("bit-count-uses-signed-64-bit-two-complement", "bit_count", [_band(0)],
              [[0, 1, -1, -128, 1 << 53, -(1 << 53), None]]),
    ]

    cast_samples = [-1.0e50, -4294967296.5, -32769.9, -129.9, -128.0,
                    -1.9, 0.9, 1.9, 127.9, 255.9, 32768.9,
                    4294967296.0, 1.0e50, None]
    for dtype in ("int8", "uint8", "int16", "uint16", "int32", "uint32"):
        cases.append(_case(f"cast-clamp-truncate-{dtype}", "cast", [_band(0)],
                           [cast_samples], dtype=dtype))
    cases.append(_case("cast-int64-exact-binary64-domain", "cast", [_band(0)],
                       [[-(1 << 53), -1.9, 0.9, 1 << 53, None]], dtype="int64"))

    compare_left = [0.0, -0.0, min_subnormal, -min_subnormal, max_float,
                    -max_float, float(1 << 53), math.nextafter(float(1 << 53), math.inf),
                    1.0, None, 4.0]
    compare_right = [-0.0, 0.0, 0.0, 0.0, max_float,
                     -max_float, float(1 << 53), float(1 << 53),
                     math.nextafter(1.0, math.inf), 3.0, None]
    for operation in ("eq", "neq", "lt", "lte", "gt", "gte"):
        cases.append(_case(f"compare-float64-signed-zero-subnormal-extremes-{operation}",
                           operation, [_band(0), _band(1)],
                           [compare_left, compare_right]))
    cases.append(_case("compare-negative-zero-constant", "eq", [_band(0), _constant(-0.0)],
                       [[-0.0, 0.0, min_subnormal, -min_subnormal, None]]))

    # The no-NoData integer cell types make these extrema valid samples. They guard
    # against interpreting -128, -32768, or Int.MinValue as storage sentinels.
    cases.extend([
        _case("byte-valid-minus-128-is-not-nodata", "bit_and", [_band(0), _constant(255)],
              [[-128, 127]], input_type="byte"),
        _case("short-valid-minus-32768-is-not-nodata", "bit_not", [_band(0)],
              [[-32768, 32767]], input_type="short"),
        _case("int-valid-minimum-is-not-nodata", "bit_not", [_band(0)],
              [[-(1 << 31), (1 << 31) - 1]], input_type="int"),
        _case("unsigned-source-cell-types-preserve-full-range", "bit_or", [_band(0), _constant(0)],
              [[255, 0]], input_type="ubyte"),
        _case("unsigned-short-source-cell-type-preserves-high-bit", "bit_xor",
              [_band(0), _constant(32768)], [[65535, 32768]], input_type="ushort"),
    ])

    invalid_tile_cases = [
        _invalid_tile("fractional-bit-input", "bit_and", [_band(0), _constant(1)], [[1.5]]),
        _invalid_tile("bit-input-above-exact-range", "bit_or", [_band(0), _constant(0)],
                      [[float(MAX_SAFE_INTEGER + 2)]]),
        _invalid_tile("left-shift-result-overflow", "left_shift", [_band(0), _constant(1)],
                      [[float(MAX_SAFE_INTEGER)]]),
        _invalid_tile("bit-not-result-overflow", "bit_not", [_band(0)],
                      [[float(MAX_SAFE_INTEGER)]]),
        _invalid_tile("negative-shift-count", "right_shift", [_band(0), _band(1)], [[-4], [-1]]),
        _invalid_tile("fractional-shift-count", "left_shift", [_band(0), _band(1)], [[1], [1.5]]),
        _invalid_tile("shift-count-above-63", "left_shift", [_band(0), _constant(64)], [[1]]),
        _invalid_tile("int64-cast-result-overflow", "cast", [_band(0)],
                      [[float(MAX_SAFE_INTEGER + 2)]], dtype="int64"),
        _invalid_tile("source-positive-infinity", "eq", [_band(0), _constant(1)], [[math.inf]]),
        _invalid_tile("source-negative-infinity", "cast", [_band(0)], [[-math.inf]], dtype="int32"),
    ]
    masked_constant_cases = [
        _invalid_masked_constant("fractional-bit-constant-with-masked-band", "bit_and", 0.5),
        _invalid_masked_constant("fractional-shift-constant-with-masked-band", "left_shift", 0.5),
        _invalid_masked_constant("out-of-range-shift-constant-with-masked-band", "right_shift", 64),
        _invalid_masked_constant("negative-shift-constant-with-masked-band", "right_shift", -1),
        _invalid_masked_constant("out-of-domain-bit-constant-with-masked-band",
                                 "bit_or", MAX_SAFE_INTEGER + 2),
    ]
    raw_scl: list[float | None] = [3, 4, 5, 6, 7, 8, 9, 10, 11, 0, 4, None, 6]
    qa_specs = {
        "eq4": canonical_spec("eq", [_band(0), _constant(4)]),
        "shift10": canonical_spec("left_shift", [_band(0), _constant(10)]),
        "eq5": canonical_spec("eq", [_band(0), _constant(5)]),
        "shift11": canonical_spec("left_shift", [_band(0), _constant(11)]),
        "or45": canonical_spec("bit_or", [_band(0), _band(1)]),
        "eq6": canonical_spec("eq", [_band(0), _constant(6)]),
        "shift40": canonical_spec("left_shift", [_band(0), _constant(40)]),
        "or_highbit": canonical_spec("bit_or", [_band(0), _band(1)]),
        "mask_bits": canonical_spec("bit_and", [_band(0), _constant((1 << 40) | (1 << 11) | (1 << 10))]),
        "eq_zero": canonical_spec("eq", [_band(0), _constant(0)]),
    }
    qa_composite = {
        "name": "synthetic-scl-category-qa-composition",
        "raw_scl": [_encode_value(value) for value in raw_scl],
        # This policy is calculated directly from original SCL labels, independently
        # of the isolated-operation reference evaluator above.
        "expected_clear": [
            "NaN" if value is None else _encode_value(0 if value in {4, 5, 6} else 1)
            for value in raw_scl
        ],
        "specs": qa_specs,
        "steps": ["eq4", "shift10", "eq5", "shift11", "or45", "eq6",
                  "shift40", "or_highbit", "mask_bits", "eq_zero"],
    }
    return {
        "schema": "local-ee-integer-values-synthetic/v1",
        "cases": cases,
        "invalid_specs": _invalid_specs(),
        "invalid_tile_cases": invalid_tile_cases,
        "masked_constant_cases": masked_constant_cases,
        "qa_composite": qa_composite,
        "operation_count": len(OPERATIONS),
        "case_count": len(cases),
        "pixel_count": sum(len(row["expected"]) for row in cases),
    }
