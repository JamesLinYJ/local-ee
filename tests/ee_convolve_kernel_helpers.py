"""Independent exact-rational whole-raster references for the convolve tile probe."""
from __future__ import annotations

from fractions import Fraction
import math
import random
import struct


def _bits(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{struct.unpack('>Q', struct.pack('>d', value))[0]:016x}"


def _float(bits: str | None) -> float | None:
    if bits is None:
        return None
    return struct.unpack(">d", int(bits, 16).to_bytes(8, "big"))[0]


def _canonical_spec(coefficients: list[tuple[int, int, float]]) -> str:
    ordered = sorted(coefficients, key=lambda value: (value[1], value[0]))
    entries = ",".join(f'[{dx},{dy},"{_bits(weight)}"]' for dx, dy, weight in ordered)
    return f'{{"coefficients":[{entries}],"v":1}}'


def _reference(
    values: list[float | None], *, width: int, height: int, tile_cols: int, tile_rows: int,
    tile_keys: list[tuple[int, int]], coefficients: list[tuple[int, int, float]],
) -> list[float | None]:
    available = set(tile_keys)
    output: list[float | None] = [None] * (width * height)
    for tile_col, tile_row in available:
        for local_row in range(tile_rows):
            y = tile_row * tile_rows + local_row
            for local_col in range(tile_cols):
                x = tile_col * tile_cols + local_col
                center = values[y * width + x]
                if center is None:
                    continue
                exact = Fraction()
                complete = True
                for dx, dy, weight in coefficients:
                    if weight == 0.0:
                        continue
                    neighbor_x = x + dx
                    neighbor_y = y + dy
                    if not (0 <= neighbor_x < width and 0 <= neighbor_y < height):
                        complete = False
                        continue
                    if (neighbor_x // tile_cols, neighbor_y // tile_rows) not in available:
                        complete = False
                        continue
                    value = values[neighbor_y * width + neighbor_x]
                    if value is None:
                        complete = False
                        continue
                    exact += Fraction.from_float(value) * Fraction.from_float(weight)
                if complete:
                    try:
                        output[y * width + x] = float(exact)
                    except OverflowError:
                        raise AssertionError("fixture unexpectedly overflows its final Float64 result")
    return output


def _case(
    name: str, values: list[float | None], *, width: int, height: int, tile_cols: int,
    tile_rows: int, tile_keys: list[tuple[int, int]], coefficients: list[tuple[int, int, float]],
) -> dict:
    expected = _reference(values, width=width, height=height, tile_cols=tile_cols,
                          tile_rows=tile_rows, tile_keys=tile_keys, coefficients=coefficients)
    ordered = sorted(coefficients, key=lambda value: (value[1], value[0]))
    return {
        "name": name,
        "width": width,
        "height": height,
        "tile_cols": tile_cols,
        "tile_rows": tile_rows,
        "tile_keys": [list(key) for key in tile_keys],
        "values": [_bits(value) for value in values],
        "coefficients": [[dx, dy, _bits(weight)] for dx, dy, weight in ordered],
        "spec": _canonical_spec(coefficients),
        "expected": [_bits(value) for value in expected],
    }


def make_fixture() -> dict:
    width, height = 6, 4
    full_tiles = [(0, 0), (1, 0), (0, 1), (1, 1)]
    asymmetric = [(-1, 0, -0.5), (0, 0, 2.0), (1, 1, 1.25)]
    masked = [
        1.0, 2.0, None, 4.0, 5.0, 6.0,
        7.0, 8.0, 9.0, 10.0, None, 12.0,
        13.0, 14.0, 15.0, 16.0, 17.0, 18.0,
        19.0, 20.0, 21.0, 22.0, 23.0, 24.0,
    ]
    alternating = [
        (sys_max if col % 2 == 0 else -sys_max)
        for _row in range(4) for col in range(8)
    ]
    min_subnormal = math.ulp(0.0)
    smallest_normal = float.fromhex("0x1.0p-1022")
    cancellation_values = [1.0e308, -1.0e308, min_subnormal, 3.0, 4.0, 5.0]
    cancellation_values += [0.0] * (width * height - len(cancellation_values))
    rng = random.Random(0xC0A43)

    def finite_raw_float() -> float:
        sign = rng.getrandbits(1) << 63
        exponent = rng.randrange(500, 1520)
        fraction = rng.getrandbits(52)
        return struct.unpack(">d", (sign | (exponent << 52) | fraction).to_bytes(8, "big"))[0]

    random_values = [finite_raw_float() for _ in range(width * height)]
    random_coefficients = [
        (dx, dy, finite_raw_float())
        for dy in (-1, 0, 1) for dx in (-1, 0, 1)
    ]
    cases = [
        _case("asymmetric-signed-seams", list(map(float, range(1, width * height + 1))),
              width=width, height=height, tile_cols=3, tile_rows=2,
              tile_keys=full_tiles, coefficients=asymmetric),
        _case("missing-tile-strict-support", list(map(float, range(1, width * height + 1))),
              width=width, height=height, tile_cols=3, tile_rows=2,
              tile_keys=[(0, 0), (0, 1), (1, 1)], coefficients=[(0, 0, 1.0), (1, 0, 1.0)]),
        _case("masked-neighbor-and-zero-tap", masked,
              width=width, height=height, tile_cols=3, tile_rows=2,
              tile_keys=full_tiles, coefficients=[(0, 0, 2.0), (1, 0, 0.0)]),
        _case("all-zero-center", masked,
              width=width, height=height, tile_cols=3, tile_rows=2,
              tile_keys=full_tiles, coefficients=[(0, 0, 0.0)]),
        _case("large-product-cancellation", alternating,
              width=8, height=4, tile_cols=4, tile_rows=4,
              tile_keys=[(0, 0), (1, 0)],
              coefficients=[(0, 0, 1.0e308), (1, 0, 1.0e308), (2, 0, 1.0e-308)]),
        _case("subnormal-products-sum", [min_subnormal] * (width * height),
              width=width, height=height, tile_cols=3, tile_rows=2,
              tile_keys=full_tiles, coefficients=[(0, 0, 0.5), (1, 0, 0.5)]),
        _case("subnormal-positive-halfway", [min_subnormal] * (width * height),
              width=width, height=height, tile_cols=3, tile_rows=2,
              tile_keys=full_tiles, coefficients=[(0, 0, 0.5)]),
        _case("subnormal-negative-halfway", [-min_subnormal] * (width * height),
              width=width, height=height, tile_cols=3, tile_rows=2,
              tile_keys=full_tiles, coefficients=[(0, 0, 0.5)]),
        _case("exact-cancellation-subnormal-residue", cancellation_values,
              width=width, height=height, tile_cols=3, tile_rows=2,
              tile_keys=full_tiles, coefficients=[(0, 0, 1.0), (1, 0, 1.0), (2, 0, 1.0)]),
        _case("normal-boundary-exact-products", [smallest_normal] * (width * height),
              width=width, height=height, tile_cols=3, tile_rows=2,
              tile_keys=full_tiles, coefficients=[(0, 0, 0.5), (1, 0, 0.5)]),
        _case("raw-bit-random-multicoefficient", random_values,
              width=width, height=height, tile_cols=3, tile_rows=2,
              tile_keys=full_tiles, coefficients=random_coefficients),
    ]
    return {
        "cases": cases,
        "case_count": len(cases),
        "pixel_count": sum(len(case["expected"]) for case in cases),
        "reject_overflow": {
            "center_bits": _bits(float.fromhex("0x1.fffffffffffffp+1023")),
            "weight_bits": _bits(2.0),
        },
    }


sys_max = float.fromhex("0x1.fffffffffffffp+1023")
