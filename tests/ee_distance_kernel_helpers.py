"""Independent exact-grid references for the native Image.distance probe."""
from __future__ import annotations

from fractions import Fraction
from decimal import Decimal, localcontext
import json
import math
import struct

from gee.distance_spec import prepare_distance_spec


def _bits(value: float | None) -> str | None:
    if value is None:
        return None
    return struct.pack(">d", value).hex()


def _float(bits: str | None) -> float | None:
    if bits is None:
        return None
    return struct.unpack(">d", bytes.fromhex(bits))[0]


def _sqrt_integer(value: int) -> float:
    """Correctly rounded Decimal-backed square root for a small integer norm."""
    with localcontext() as context:
        context.prec = 120
        return float(Decimal(value).sqrt())


def _eligible(metric: str, dx: int, dy: int, radius: Fraction) -> bool:
    if metric == "euclidean":
        return Fraction(dx * dx + dy * dy) <= radius * radius
    if metric == "manhattan":
        return Fraction(abs(dx) + abs(dy)) <= radius
    if metric == "chebyshev":
        return Fraction(max(abs(dx), abs(dy))) <= radius
    raise AssertionError(f"unhandled metric: {metric}")


def reference(case: dict) -> list[float | None]:
    """Search the complete finite grid using exact Fraction radius tests.

    The implementation deliberately does not use the production offset plan or
    kernel constructors. Missing tiles have no source pixels and no output
    centers; masked values are ignored as targets. The center mask follows the
    independent skip_masked switch.
    """
    width, height = case["width"], case["height"]
    tile_cols, tile_rows = case["tile_cols"], case["tile_rows"]
    tile_keys = {tuple(key) for key in case["tile_keys"]}
    values = [_float(item) for item in case["values"]]
    radius = Fraction.from_float(case["radius"])
    output: list[float | None] = [None] * (width * height)

    for row in range(height):
        for col in range(width):
            center_key = (col // tile_cols, row // tile_rows)
            if center_key not in tile_keys:
                continue
            center = values[row * width + col]
            if center is None and case["skip_masked"]:
                continue

            nearest: tuple[int, int] | None = None
            halo = math.ceil(case["radius"])
            for dy in range(-halo, halo + 1):
                for dx in range(-halo, halo + 1):
                    if not _eligible(case["metric"], dx, dy, radius):
                        continue
                    candidate_col, candidate_row = col + dx, row + dy
                    if not (0 <= candidate_col < width and 0 <= candidate_row < height):
                        continue
                    candidate_key = (candidate_col // tile_cols, candidate_row // tile_rows)
                    if candidate_key not in tile_keys:
                        continue
                    candidate = values[candidate_row * width + candidate_col]
                    if candidate is None or candidate == 0.0:
                        continue
                    distance = (dx * dx + dy * dy if case["metric"] == "euclidean"
                                else abs(dx) + abs(dy) if case["metric"] == "manhattan"
                                else max(abs(dx), abs(dy)))
                    if nearest is None or distance < nearest[0]:
                        nearest = (distance, dx * dx + dy * dy)
            if nearest is not None:
                output[row * width + col] = (
                    _sqrt_integer(nearest[1]) if case["metric"] == "euclidean"
                    else float(nearest[0])
                )
    return output


def _case(
    name: str,
    metric: str,
    radius: float,
    values: list[float | None],
    *,
    skip_masked: bool = True,
    tile_keys: list[tuple[int, int]] | None = None,
) -> dict:
    width, height, tile_cols, tile_rows = 8, 6, 4, 3
    if len(values) != width * height:
        raise ValueError(f"{name}: expected {width * height} input pixels")
    if tile_keys is None:
        tile_keys = [(0, 0), (1, 0), (0, 1), (1, 1)]
    case = {
        "name": name,
        "width": width,
        "height": height,
        "tile_cols": tile_cols,
        "tile_rows": tile_rows,
        "tile_keys": [list(key) for key in tile_keys],
        "metric": metric,
        "radius": radius,
        "skip_masked": skip_masked,
        "spec": prepare_distance_spec(metric, radius, skip_masked),
        "values": [_bits(value) for value in values],
    }
    case["expected"] = [_bits(value) for value in reference(case)]
    return case


def _blank() -> list[float | None]:
    return [0.0] * (8 * 6)


def _set(values: list[float | None], col: int, row: int, value: float | None) -> None:
    values[row * 8 + col] = value


def make_fixture() -> dict:
    """Produce metric, radius, mask, tile-boundary and value-range controls."""
    maximum = float.fromhex("0x1.fffffffffffffp+1023")
    subnormal = math.ulp(0.0)

    all_tiles = [(0, 0), (1, 0), (0, 1), (1, 1)]
    mixed = _blank()
    _set(mixed, 3, 1, -2.0)       # Negative target across the x tile seam.
    _set(mixed, 4, 4, subnormal)  # Smallest positive subnormal is still a target.
    _set(mixed, 6, 1, maximum)
    _set(mixed, 0, 5, -maximum)
    _set(mixed, 7, 5, 9.0)
    _set(mixed, 2, 3, None)       # A masked value is never a target.

    diagonal = _blank()
    _set(diagonal, 4, 3, -subnormal)
    diagonal_center = (3, 2)

    masked = _blank()
    _set(masked, 4, 2, None)      # Output center on a tile boundary.
    _set(masked, 5, 2, None)    # Closer masked target candidate must be ignored.
    _set(masked, 2, 2, -maximum) # Valid target at distance two across the seam.

    no_targets = _blank()

    missing = _blank()
    _set(missing, 4, 1, 2.0)      # Target is inside the absent tile.
    _set(missing, 0, 0, -3.0)     # Separate positive control in an observed tile.
    observed_without_top_right = [(0, 0), (0, 1), (1, 1)]

    edge = _blank()
    _set(edge, 0, 0, 4.0)

    cases = [
        *[_case(f"metric-{metric}-radius-2", metric, 2.0, mixed)
          for metric in ("euclidean", "manhattan", "chebyshev")],
        _case("fractional-euclidean-nextafter-sqrt2-below", "euclidean",
              math.nextafter(math.sqrt(2.0), 0.0), diagonal),
        _case("fractional-euclidean-sqrt2", "euclidean", math.sqrt(2.0), diagonal),
        _case("fractional-manhattan-1_5", "manhattan", 1.5, diagonal),
        _case("fractional-chebyshev-1_5", "chebyshev", 1.5, diagonal),
        _case("subnormal-radius-includes-only-center", "manhattan", subnormal, mixed),
        _case("masked-center-skip", "euclidean", 2.0, masked, skip_masked=True),
        _case("masked-center-fill", "euclidean", 2.0, masked, skip_masked=False),
        _case("no-target-no-sentinel", "chebyshev", 2.0, no_targets,
              skip_masked=False),
        _case("missing-tile-is-not-a-target", "euclidean", 1.0, missing,
              tile_keys=observed_without_top_right),
        _case("radius-zero-positive-control", "manhattan", 0.0, mixed),
        _case("edge-target-positive-control", "chebyshev", 2.0, edge),
    ]

    # Keep explicit named target/control coordinates in the fixture manifest so
    # an auditor can locate the intentionally extreme values without reverse-
    # engineering the generated binary64 list.
    return {
        "schema": "local-ee-synthetic-image-distance/v1",
        "cases": cases,
        "case_count": len(cases),
        "grid_slot_count": sum(len(case["expected"]) for case in cases),
        "evaluated_pixel_count": sum(
            len(case["tile_keys"]) * case["tile_cols"] * case["tile_rows"] for case in cases
        ),
        "oracle": "Python Fraction exact radius comparisons and Decimal-backed correctly rounded Euclidean output over integer grid offsets",
        "controls": {
            "diagonal_center": list(diagonal_center),
            "negative_target": [-2.0, 3, 1],
            "subnormal_target_bits": _bits(subnormal),
            "extreme_target_bits": _bits(maximum),
            "missing_tile": [1, 0],
            "masked_center": [4, 2],
            "edge_target": [0, 0],
        },
        "invalid_specs": canonical_invalid_specs(),
    }


def canonical_invalid_specs() -> list[str]:
    """Small stable malformed corpus used by the independent Scala parser probe."""
    valid = json.loads(prepare_distance_spec("euclidean", 1.0))
    malformed = [
        "{}",
        "[]",
        '{"metric":"euclidean","metric":"euclidean","radius":"3ff0000000000000","skip_masked":true,"v":1}',
        json.dumps({**valid, "radius": "3FF0000000000000"}, sort_keys=True, separators=(",", ":")),
        json.dumps({**valid, "radius": "7ff0000000000000"}, sort_keys=True, separators=(",", ":")),
        json.dumps({**valid, "radius": "bff0000000000000"}, sort_keys=True, separators=(",", ":")),
        json.dumps({**valid, "radius": "8000000000000000"}, sort_keys=True, separators=(",", ":")),
        json.dumps({**valid, "metric": "circle"}, sort_keys=True, separators=(",", ":")),
        json.dumps({**valid, "skip_masked": 1}, sort_keys=True, separators=(",", ":")),
        json.dumps({**valid, "v": 1.0}, sort_keys=True, separators=(",", ":")),
    ]
    return malformed
