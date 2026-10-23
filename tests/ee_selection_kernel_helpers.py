"""Synthetic selection tiles and an independent binary64 reference."""
from __future__ import annotations

import json
import math
import struct
import sys
from typing import Any


MAX_FLOAT = sys.float_info.max
MIN_SUBNORMAL = math.ulp(0.0)


def _bits(value: float | int) -> str:
    return struct.pack(">d", float(value)).hex()


def _encode(value: float | int | None) -> str:
    if value is None or math.isnan(float(value)):
        return "NaN"
    if math.isinf(float(value)):
        return "Infinity" if float(value) > 0 else "-Infinity"
    return float(value).hex()


def _decode(value: str) -> float:
    if value == "NaN":
        return math.nan
    if value == "Infinity":
        return math.inf
    if value == "-Infinity":
        return -math.inf
    return float.fromhex(value)


def _band(index: int) -> dict[str, int]:
    return {"band": index}


def _constant(value: float | int) -> dict[str, str]:
    return {"constant": _bits(value)}


def _spec(operation: str, operands: list[dict[str, Any]],
          dtype: str | None = None) -> str:
    return json.dumps(
        {"dtype": dtype, "op": operation, "operands": operands, "v": 1},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )


def _resolve(operand: dict[str, Any], bands: list[list[float]], pixel: int) -> float:
    if set(operand) == {"band"}:
        return bands[operand["band"]][pixel]
    encoded = operand["constant"]
    return struct.unpack(">d", bytes.fromhex(encoded))[0]


def reference(row: dict[str, Any]) -> list[float]:
    """Apply conditional selection semantics, preserving selected raw values."""
    spec = json.loads(row["spec"])
    bands = [[_decode(value) for value in band] for band in row["bands"]]
    width = len(bands[0])
    operands = spec["operands"]
    result = []
    for pixel in range(width):
        condition = _resolve(operands[0], bands, pixel)
        if spec["op"] == "select":
            if math.isnan(condition):
                result.append(math.nan)
                continue
            selected = _resolve(operands[1 if condition != 0.0 else 2], bands, pixel)
            result.append(math.nan if math.isnan(selected) else selected)
            continue

        if spec["op"] == "where_select":
            replacement = _resolve(operands[1], bands, pixel)
            original = _resolve(operands[2], bands, pixel)
            if math.isnan(original):
                result.append(math.nan)
            elif math.isnan(condition) or math.isnan(replacement):
                result.append(original)
            elif condition != 0.0:
                result.append(replacement)
            else:
                result.append(original)
            continue

        raise AssertionError(f"unsupported reference operation: {spec['op']}")
    return result


def _case(name: str, operands: list[dict[str, Any]],
          bands: list[list[float | int | None]],
          operation: str = "select") -> dict[str, Any]:
    row = {
        "name": name,
        "spec": _spec(operation, operands),
        "input_type": "double",
        "bands": [[_encode(value) for value in band] for band in bands],
    }
    row["expected"] = [_encode(value) for value in reference(row)]
    return row


def _invalid_specs() -> list[str]:
    select = lambda operands, dtype=None: _spec("select", operands, dtype)
    where_select = lambda operands, dtype=None: _spec("where_select", operands, dtype)
    return [
        select([_band(0), _band(1)]),
        select([_band(0), _band(1), _band(2), _constant(0)]),
        select([_band(0), _band(1), _band(3)]),
        select([_band(0), _band(2), _constant(0)]),
        select([_band(0), _constant(1), _constant(0)], "float64"),
        select([_band(0), {"constant": "7ff0000000000000"}, _constant(0)]),
        select([_band(0), {"constant": "7ff8000000000000"}, _constant(0)]),
        select([_constant(1), _constant(2), _constant(3)]),
        where_select([_band(0), _band(1)]),
        where_select([_band(0), _band(1), _band(2), _constant(0)]),
        where_select([_band(0), _band(1), _band(3)]),
        where_select([_band(0), _band(2), _constant(0)]),
        where_select([_band(0), _constant(1), _constant(0)], "float64"),
        where_select([_constant(1), _constant(2), _constant(3)]),
        _spec("add", [_band(0), _band(1), _band(2)]),
        _spec("add", [_band(0), _band(2)]),
    ]


def _invalid_tile_cases() -> list[dict[str, Any]]:
    three_dynamic = _spec("select", [_band(0), _band(1), _band(2)])
    where_dynamic = _spec("where_select", [_band(0), _band(1), _band(2)])
    return [
        {
            "name": "positive-infinity-in-unselected-branch",
            "spec": three_dynamic,
            "input_type": "double",
            "bands": [["0x0.0p+0"], ["Infinity"], ["0x1.4p+2"]],
        },
        {
            "name": "negative-infinity-in-unselected-branch",
            "spec": three_dynamic,
            "input_type": "double",
            "bands": [["0x0.0p+0"], ["-Infinity"], ["0x1.4p+2"]],
        },
        {
            "name": "input-band-count-does-not-match-spec",
            "spec": three_dynamic,
            "input_type": "double",
            "bands": [["0x0.0p+0"], ["0x1.0p+0"]],
        },
        {
            "name": "where-positive-infinity-in-unused-replacement",
            "spec": where_dynamic,
            "input_type": "double",
            "bands": [["0x0.0p+0"], ["Infinity"], ["0x1.4p+2"]],
        },
        {
            "name": "where-negative-infinity-with-missing-condition",
            "spec": where_dynamic,
            "input_type": "double",
            "bands": [["NaN"], ["0x1.0p+0"], ["-Infinity"]],
        },
        {
            "name": "where-input-band-count-does-not-match-spec",
            "spec": where_dynamic,
            "input_type": "double",
            "bands": [["0x0.0p+0"], ["0x1.0p+0"]],
        },
    ]


def make_fixture() -> dict[str, Any]:
    dynamic = _case(
        "three-dynamic-bands-mask-extremes-and-signed-zero",
        [_band(0), _band(1), _band(2)],
        [
            [1.0, -1.0, MIN_SUBNORMAL, 0.0, -0.0, None, 1.0, 0.0,
             -MIN_SUBNORMAL, 0.0, 1.0],
            [MAX_FLOAT, MIN_SUBNORMAL, -MAX_FLOAT, 2.0, 7.0, 3.0,
             6.5, None, -0.0, 1.0, None],
            [-MAX_FLOAT, -MAX_FLOAT, MAX_FLOAT, MIN_SUBNORMAL, -0.0, 4.0,
             None, -9.0, 3.0, -0.0, 2.0],
        ],
    )
    constant_branches = _case(
        "constant-selected-branches-and-condition-mask",
        [_band(0), _constant(1.25), _constant(-0.0)],
        [[MIN_SUBNORMAL, 0.0, -0.0, -MIN_SUBNORMAL, None, 1.0]],
    )
    constant_condition = _case(
        "constant-subnormal-condition-with-two-dynamic-branches",
        [_constant(-MIN_SUBNORMAL), _band(0), _band(1)],
        [
            [MAX_FLOAT, MIN_SUBNORMAL, -0.0, None, 4.0],
            [-MAX_FLOAT, -MIN_SUBNORMAL, 0.0, 9.0, None],
        ],
    )
    where_dynamic = _case(
        "where-dynamic-bands-fallback-masks-extremes-and-signed-zero",
        [_band(0), _band(1), _band(2)],
        [
            [1.0, 1.0, 1.0, 0.0, 0.0, None, None, 1.0,
             1.0, 0.0, 1.0, -MIN_SUBNORMAL, 0.0, 1.0],
            [MAX_FLOAT, None, -MAX_FLOAT, 123.0, None, 999.0,
             MIN_SUBNORMAL, -0.0, 0.0, MAX_FLOAT, 1.5, 9.0,
             -MAX_FLOAT, -MAX_FLOAT],
            [-MAX_FLOAT, -MAX_FLOAT, MAX_FLOAT, -0.0, 4.0, 5.0,
             6.0, None, -0.0, MIN_SUBNORMAL, None, 0.0,
             -MIN_SUBNORMAL, MAX_FLOAT],
        ],
        operation="where_select",
    )
    where_constant_branches = _case(
        "where-constant-branches-subnormal-condition",
        [_band(0), _constant(-0.0), _constant(MAX_FLOAT)],
        [[MIN_SUBNORMAL, 0.0, -0.0, -MIN_SUBNORMAL]],
        operation="where_select",
    )
    cases = [dynamic, constant_branches, constant_condition,
             where_dynamic, where_constant_branches]
    invalid_specs = _invalid_specs()
    invalid_tiles = _invalid_tile_cases()
    return {
        "schema": "local-ee-selection-kernel-synthetic/v1",
        "operations": ["select", "where_select"],
        "case_count": len(cases),
        "pixel_count": sum(len(row["expected"]) for row in cases),
        "cases": cases,
        "invalid_specs": invalid_specs,
        "invalid_tile_cases": invalid_tiles,
    }
