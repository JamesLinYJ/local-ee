"""Independent reference fixtures for the bounded fast-distance kernel probe.

This module intentionally does not call the Scala transform or fragment code.
Small transforms use a brute-force target-coordinate oracle; tile fixtures use
the same direct oracle over observed source tiles and hash compact outputs.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import struct
from typing import Optional

from gee.fast_distance_spec import prepare_fast_distance_spec


NO_TARGET_DISTANCE = (2**63 - 1) // 4
METRICS = ("squared_euclidean", "manhattan", "chebyshev")
_MAX_FINITE_BITS = "7fefffffffffffff"
_MIN_FINITE_BITS = "ffefffffffffffff"
_SUBNORMAL_BITS = "0000000000000001"
_NEGATIVE_ZERO_BITS = "8000000000000000"


def _metric(dx: int, dy: int, metric: str) -> int:
    if metric == "squared_euclidean":
        return dx * dx + dy * dy
    if metric == "manhattan":
        return abs(dx) + abs(dy)
    if metric == "chebyshev":
        return max(abs(dx), abs(dy))
    raise ValueError(f"unknown test metric: {metric}")


def brute_force_transform(targets: list[int], width: int, height: int,
                          metric: str) -> list[int]:
    """Exact nearest-target oracle over integer coordinates, including empty masks."""
    if width <= 0 or height <= 0 or len(targets) != width * height:
        raise ValueError("target mask shape does not match positive dimensions")
    sites = [(index % width, index // width) for index, target in enumerate(targets)
             if target]
    if not sites:
        return [NO_TARGET_DISTANCE] * (width * height)
    result = []
    for y in range(height):
        for x in range(width):
            result.append(min(_metric(x - tx, y - ty, metric) for tx, ty in sites))
    return result


def digest_unsigned(values: list[int], width: int = 8) -> str:
    """SHA-256 of fixed-width big-endian nonnegative integer cells."""
    if width not in (4, 8):
        raise ValueError("digest width must be 4 or 8 bytes")
    pack = struct.Struct(">I" if width == 4 else ">Q").pack
    digest = hashlib.sha256()
    for value in values:
        digest.update(pack(value))
    return digest.hexdigest()


def _pure_kernel_cases() -> list[dict]:
    cases: list[dict] = []
    rng = random.Random(0xFAD157A)
    for metric in METRICS:
        for name, width, height, targets in (
            ("empty", 7, 1, []),
            ("full", 1, 9, list(range(9))),
            ("seeded-sparse", 7, 6,
             [index for index in range(42) if rng.random() < 0.23]),
            ("seeded-dense", 8, 5,
             [index for index in range(40) if rng.random() < 0.72]),
        ):
            mask = [int(index in set(targets)) for index in range(width * height)]
            expected = brute_force_transform(mask, width, height, metric)
            cases.append({
                "name": f"{metric}-{name}", "metric": metric,
                "width": width, "height": height, "targets": targets,
                "expected": expected,
            })

    # The 1-D route exercises the exact wide-integer path without allocating a
    # second line-sized Long array. Its last value exceeds signed Int32.
    width = 65_537
    expected = list(range(width))
    cases.append({
        "name": "squared-euclidean-long-line-int32-overflow",
        "metric": "squared_euclidean", "width": width, "height": 1,
        "targets": [0], "last_value": expected[-1] ** 2,
        "digest": digest_unsigned([value * value for value in expected]),
    })
    return cases


def _tile_key(col: int, row: int, instant: int = 0, temporal: bool = False) -> list:
    return [col, row, instant, temporal]


def _tile_record(col: int, row: int, cols: int, rows: int,
                 default_bits: str = "0000000000000000", overrides=None,
                 instant: int = 0, temporal: bool = False) -> dict:
    overrides = overrides or {}
    if any(not 0 <= index < cols * rows for index in overrides):
        raise ValueError("tile override index is outside the tile")
    return {
        "key": _tile_key(col, row, instant, temporal),
        "default": default_bits,
        "overrides": [[index, bits] for index, bits in sorted(overrides.items())],
    }


def _tile_values(tile: dict, tile_cells: int) -> list[Optional[float]]:
    default = _decode_value(tile["default"])
    values: list[float | None] = [default] * tile_cells
    for index, bits in tile["overrides"]:
        values[index] = None if bits is None else _decode_value(bits)
    return values


def _decode_value(bits: str) -> float:
    return struct.unpack(">d", bytes.fromhex(bits))[0]


def _is_target(value: Optional[float]) -> bool:
    return value is not None and math.isfinite(value) and value != 0.0


def _source_expected(case: dict) -> tuple[dict[str, dict], list[dict]]:
    cols, rows = case["tile_cols"], case["tile_rows"]
    cells = cols * rows
    tiles = case["tiles"]
    by_key = {tuple(tile["key"]): tile for tile in tiles}
    if len(by_key) != len(tiles):
        raise ValueError("source fixture has duplicate observed tile keys")
    decoded = {key: _tile_values(tile, cells) for key, tile in by_key.items()}
    targets: dict[tuple[int, bool], list[tuple[int, int]]] = {}
    for key, values in decoded.items():
        col, row, instant, temporal = key
        for index, value in enumerate(values):
            if _is_target(value):
                targets.setdefault((instant if temporal else 0, temporal), []).append(
                    (col * cols + index % cols, row * rows + index // cols))

    cap = case["neighborhood"] ** (2 if case["metric"] == "squared_euclidean" else 1)
    digests: dict[str, dict] = {}
    full_results: dict[tuple[int, int, int, bool], list[int]] = {}
    for key in sorted(by_key, key=lambda value: (value[3], value[2], value[1], value[0])):
        col, row, instant, temporal = key
        selected = targets.get((instant if temporal else 0, temporal), [])
        output = []
        for local_row in range(rows):
            for local_col in range(cols):
                global_col = col * cols + local_col
                global_row = row * rows + local_row
                value = (min((_metric(global_col - tx, global_row - ty, case["metric"])
                              for tx, ty in selected), default=cap))
                output.append(min(value, cap))
        full_results[key] = output
        digests[json.dumps(key)] = {
            "key": list(key), "digest": digest_unsigned(output, width=4),
            "min": min(output), "max": max(output), "cap_cells": sum(v == cap for v in output),
        }

    probes = []
    for key, col, row in case.get("probes", []):
        normalized = tuple(key)
        if normalized not in full_results:
            raise ValueError(f"probe references absent source key: {normalized}")
        if not (0 <= col < cols and 0 <= row < rows):
            raise ValueError("probe coordinate lies outside tile")
        probes.append({
            "key": list(normalized), "col": col, "row": row,
            "value": full_results[normalized][row * cols + col],
        })
    case["expected_tiles"] = list(digests.values())
    case["probes"] = probes
    case["observed_key_count"] = len(tiles)
    case["evaluated_pixel_count"] = len(tiles) * cells
    case["grid_slot_count"] = ((case["max_tile_col"] - case["min_tile_col"] + 1) * cols
                               * (case["max_tile_row"] - case["min_tile_row"] + 1) * rows
                               * len({(key[2], key[3]) for key in by_key}))
    return digests, probes


def _source_case(name: str, metric: str, neighborhood: int, cols: int, rows: int,
                 tiles: list[dict], *, bounds=(0, 0, 0, 0), probes=()) -> dict:
    case = {
        "name": name, "metric": metric, "neighborhood": neighborhood,
        "spec": prepare_fast_distance_spec(metric, neighborhood),
        "tile_cols": cols, "tile_rows": rows,
        "min_tile_col": bounds[0], "min_tile_row": bounds[1],
        "max_tile_col": bounds[2], "max_tile_row": bounds[3],
        "tiles": tiles, "probes": [list(probe) for probe in probes],
    }
    _source_expected(case)
    return case


def _small_source_cases() -> list[dict]:
    cases = []
    for metric in METRICS:
        cases.append(_source_case(
            f"all-zero-{metric}", metric, 3, 5, 4,
            [_tile_record(0, 0, 5, 4)],
            probes=[(_tile_key(0, 0), 4, 3)],
        ))
        cases.append(_source_case(
            f"all-one-{metric}", metric, 3, 5, 4,
            [_tile_record(0, 0, 5, 4, _MIN_FINITE_BITS)],
            probes=[(_tile_key(0, 0), 4, 3)],
        ))
        cases.append(_source_case(
            f"cutoff-boundaries-{metric}", metric, 3, 6, 1,
            [_tile_record(0, 0, 6, 1, overrides={0: "bff0000000000000"})],
            probes=[(_tile_key(0, 0), x, 0) for x in (0, 3, 4, 5)],
        ))

    # One actual DoubleArrayTile carries every finite sign/magnitude corner.
    # The null override is NoData, and the negative zero override is not a target.
    numeric = _source_case(
        "finite-sign-subnormal-extremes-and-masked-center",
        "squared_euclidean", 6, 8, 4,
        [_tile_record(0, 0, 8, 4, overrides={
            0: "bff0000000000000", 2: _SUBNORMAL_BITS,
            4: _MAX_FINITE_BITS, 6: _MIN_FINITE_BITS,
            8: _NEGATIVE_ZERO_BITS, 9: None, 10: "0000000000000000",
        })],
        probes=[(_tile_key(0, 0), 1, 1), (_tile_key(0, 0), 7, 3)],
    )
    cases.append(numeric)
    return cases


def _wide_source_cases() -> list[dict]:
    cases = []
    for metric in METRICS:
        tiles = []
        for row in range(3):
            for col in range(3):
                overrides = {0: "bff0000000000000"} if (col, row) == (1, 1) else None
                tiles.append(_tile_record(col, row, 256, 256, overrides=overrides))
        cases.append(_source_case(
            f"default-neighborhood-256-{metric}", metric, 256, 256, 256, tiles,
            bounds=(0, 0, 2, 2),
            probes=[(_tile_key(0, 1), 255, 0), (_tile_key(2, 2), 255, 255)],
        ))
    return cases


def _multihop_temporal_case(metric: str) -> dict:
    tiles = []
    missing = (1, 1)
    for instant in (1000, 2000):
        for row in range(3):
            for col in range(3):
                if (col, row) == missing:
                    continue
                overrides = {}
                if instant == 1000 and (col, row) == (2, 1):
                    overrides[0] = "bff0000000000000"  # negative nonzero target
                if (col, row) == (0, 1):
                    overrides[63] = None  # output center remains observed and filled
                tiles.append(_tile_record(
                    col, row, 8, 8, overrides=overrides,
                    instant=instant, temporal=True))
    target_key = _tile_key(2, 1, 1000, True)
    center_key = _tile_key(0, 1, 1000, True)
    isolated_key = _tile_key(0, 1, 2000, True)
    return _source_case(
        f"two-tile-hop-temporal-isolation-{metric}", metric, 12, 8, 8, tiles,
        bounds=(0, 0, 2, 2),
        probes=[(center_key, 7, 7), (center_key, 7, 0), (isolated_key, 7, 7)],
    )


def make_fixture() -> dict:
    """Build the portable fixture sent to Scala; no output raster is serialized."""
    pure = _pure_kernel_cases()
    source = _small_source_cases() + _wide_source_cases() + [
        _multihop_temporal_case(metric) for metric in METRICS
    ]
    invalid_specs = [
        '{"metric":"squared_euclidean","neighborhood":256,"v":1,"x":0}',
        '{"metric":"squared_euclidean","neighborhood":256,"v":1,"v":1}',
        '{"metric":"squared_euclidean","neighborhood":256.0,"v":1}',
        '{"metric":"squared_euclidean","neighborhood":true,"v":1}',
        '{"metric":"squared_euclidean","neighborhood":0,"v":1}',
        '{"metric":"squared_euclidean","neighborhood":4097,"v":1}',
        '{"metric":"euclidean","neighborhood":256,"v":1}',
        '{"neighborhood":256,"metric":"squared_euclidean","v":1}',
        '{"metric":"squared_euclidean","neighborhood":256,"v":2}',
    ]
    return {
        "schema": "local-ee-synthetic-fast-distance/v1",
        "kernel_cases": pure,
        "source_cases": source,
        "invalid_specs": invalid_specs,
        "kernel_case_count": len(pure),
        "source_case_count": len(source),
        "source_observed_keys": sum(case["observed_key_count"] for case in source),
        "source_evaluated_pixels": sum(case["evaluated_pixel_count"] for case in source),
        "source_grid_slots": sum(case["grid_slot_count"] for case in source),
    }
