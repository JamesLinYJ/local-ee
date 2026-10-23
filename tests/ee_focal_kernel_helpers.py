"""Independent whole-raster references for the bounded native focal kernel."""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
import math
import random
import struct
import sys


OPERATIONS = ("mean", "min", "max", "median", "mode")


def _reduce(values: list[float], operation: str) -> float:
    if not values:
        return math.nan
    if operation == "min":
        return min(values)
    if operation == "max":
        return max(values)
    if operation == "mean":
        exact_sum = sum((Fraction.from_float(value) for value in values), Fraction())
        return float(exact_sum / len(values))
    if operation == "median":
        ordered = sorted(0.0 if value == 0.0 else value for value in values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        left, right = ordered[middle - 1], ordered[middle]
        return float((Fraction.from_float(left) + Fraction.from_float(right)) / 2)
    if operation == "mode":
        counts = Counter(0.0 if value == 0.0 else value for value in values)
        frequency = max(counts.values())
        return min(value for value, count in counts.items() if count == frequency)
    raise AssertionError(operation)


def whole_raster_reference(
    values: list[float | None], *, width: int, height: int, tile_cols: int, tile_rows: int,
    existing_tiles: list[list[int]], offsets: list[list[int]], iterations: int,
    skip_masked: bool, operation: str,
) -> list[float | None]:
    """Reference semantics using whole-raster indexing, independent of tile assembly."""
    assert len(values) == width * height
    available = {(col, row) for col, row in existing_tiles}
    current = [None if cell is None else float(cell) for cell in values]
    for _ in range(iterations):
        output: list[float | None] = [None] * len(current)
        for tile_col, tile_row in available:
            for local_row in range(tile_rows):
                row = tile_row * tile_rows + local_row
                for local_col in range(tile_cols):
                    col = tile_col * tile_cols + local_col
                    center = current[row * width + col]
                    if skip_masked and center is None:
                        continue
                    neighbors = []
                    for dx, dy in offsets:
                        x, y = col + dx, row + dy
                        if 0 <= x < width and 0 <= y < height and (x // tile_cols, y // tile_rows) in available:
                            value = current[y * width + x]
                            if value is not None:
                                neighbors.append(value)
                    result = _reduce(neighbors, operation)
                    output[row * width + col] = None if math.isnan(result) else result
        current = output
    return current


def make_fixture() -> dict:
    width, height = 6, 4
    ordinary = [
        1.0, 2.0, 3.0, 4.0, None, 6.0,
        7.0, None, 9.0, 10.0, 11.0, 12.0,
        -1.0, -2.0, -3.0, -4.0, -5.0, -6.0,
        13.0, 14.0, 15.0, None, 17.0, 18.0,
    ]
    wide = [
        sys.float_info.max, sys.float_info.max, 1.0e308, -sys.float_info.max, -sys.float_info.max, -1.0e308,
        sys.float_info.max, -sys.float_info.max, 9.0e307, sys.float_info.max, -sys.float_info.max, -9.0e307,
        1.0e-300, -1.0e-300, 0.0, 3.0e-300, -3.0e-300, 0.0,
        5.0, 5.0, 8.0, -5.0, -5.0, -8.0,
    ]
    signed_zero = [
        -0.0, 0.0, 2.0, 0.0, 0.0, 4.0,
        -0.0, 3.0, 2.0, 4.0, 0.0, 4.0,
        1.0, 1.0, 8.0, 9.0, 9.0, 10.0,
        -2.0, -2.0, 5.0, 5.0, 7.0, 7.0,
    ]
    full_tiles = [[0, 0], [1, 0], [0, 1], [1, 1]]
    missing_top_right = [[0, 0], [0, 1], [1, 1]]
    square = [[dx, dy] for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    sparse = [[0, -1], [0, 0], [1, 0]]
    no_data = [None] * (width * height)
    identity_values = ordinary
    min_subnormal = math.ulp(0.0)
    adjacent = math.nextafter(sys.float_info.max, 0.0)
    min_normal = float.fromhex("0x1.0p-1022")
    largest_subnormal = math.nextafter(min_normal, 0.0)
    adjacent_large = [sys.float_info.max, adjacent, min_subnormal] + [0.0] * (width * height - 3)
    adjacent_large_median = adjacent_large
    subnormal_midpoints = [
        largest_subnormal, min_normal, min_subnormal, 2.0 * min_subnormal, 0.0, min_subnormal,
    ] + [0.0] * (width * height - 6)
    cancellation = [1.0e308, -1.0e308, 1.0e-300] + [0.0] * (width * height - 3)
    subnormal_residue = [sys.float_info.max, -sys.float_info.max, 3.0 * min_subnormal]
    subnormal_residue += [0.0] * (width * height - len(subnormal_residue))
    subnormal_pair = [min_subnormal, min_subnormal] + [0.0] * (width * height - 2)
    rng = random.Random(0xF0CA1)
    random_finite = []
    while len(random_finite) < width * height:
        bits = rng.getrandbits(64)
        value = struct.unpack(">d", bits.to_bytes(8, "big"))[0]
        if math.isfinite(value):
            random_finite.append(value)
    cases = []
    profiles = [
        ("ordinary", ordinary, full_tiles, square, 1, True, OPERATIONS),
        ("iterative-missing-tile", ordinary, missing_top_right, sparse, 2, False, OPERATIONS),
        ("wide-float64", wide, full_tiles, sparse, 1, True, ("mean", "min", "max", "median")),
        ("signed-zero-mode", signed_zero, full_tiles, [[0, 0], [1, 0]], 1, False, ("mode",)),
        ("all-nodata", no_data, full_tiles, [[0, 0]], 1, False, OPERATIONS),
        ("single-identity", identity_values, full_tiles, [[0, 0]], 1, True, OPERATIONS),
        ("adjacent-large-mean", adjacent_large, full_tiles, [[0, 0], [1, 0]], 1, True, ("mean",)),
        ("adjacent-large-median", adjacent_large_median, full_tiles, [[0, 0], [1, 0]], 1, True, ("median",)),
        ("subnormal-midpoint-median", subnormal_midpoints, full_tiles, [[0, 0], [1, 0]], 1, True, ("median",)),
        ("subnormal-contribution", cancellation, full_tiles, [[0, 0], [1, 0], [2, 0]], 1, True, ("mean",)),
        ("subnormal-cancellation", subnormal_residue, full_tiles, [[0, 0], [1, 0], [2, 0]], 1, True, ("mean",)),
        ("subnormal-mean", subnormal_pair, full_tiles, [[0, 0], [1, 0]], 1, True, ("mean",)),
        ("fraction-stress-mean", random_finite, full_tiles, square, 1, True, ("mean",)),
        ("fraction-stress-median", random_finite, full_tiles, square, 1, True, ("median",)),
    ]
    for profile, raster, tiles, offsets, iterations, skip_masked, operations in profiles:
        radius = max(abs(dx) for dx, _ in offsets) if offsets else 0
        radius = max(radius, max(abs(dy) for _, dy in offsets)) if offsets else 0
        tile_cols, tile_rows = (3, 4) if radius > 1 else (3, 2)
        profile_tiles = [[0, 0], [1, 0]] if tile_rows == 4 and tiles == full_tiles else tiles
        for operation in operations:
            expected = whole_raster_reference(
                raster, width=width, height=height, tile_cols=tile_cols, tile_rows=tile_rows,
                existing_tiles=profile_tiles, offsets=offsets, iterations=iterations,
                skip_masked=skip_masked, operation=operation,
            )
            cases.append({
                "name": f"{profile}-{operation}",
                "width": width,
                "height": height,
                "tile_cols": tile_cols,
                "tile_rows": tile_rows,
                "values": raster,
                "existing_tiles": profile_tiles,
                "offsets": offsets,
                "iterations": iterations,
                "skip_masked": skip_masked,
                "operation": operation,
                "expected": expected,
            })
    pixel_count = len(cases) * width * height
    valid_pixel_count = sum(value is not None for case in cases for value in case["expected"])
    return {
        "cases": cases,
        "case_count": len(cases),
        "pixel_count": pixel_count,
        "valid_pixel_count": valid_pixel_count,
    }
