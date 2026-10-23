"""Independent Fraction/Decimal whole-grid references for neighborhood SPI probes."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, localcontext
from fractions import Fraction
import json
import math
import struct


def _bits(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{struct.unpack('>Q', struct.pack('>d', value))[0]:016x}"


def _float(bits: str | None) -> float | None:
    if bits is None:
        return None
    return struct.unpack(">d", int(bits, 16).to_bytes(8, "big"))[0]


def _stddev(value: Fraction) -> float:
    if value == 0:
        return 0.0
    with localcontext() as context:
        context.prec = 240
        decimal_value = Decimal(value.numerator) / Decimal(value.denominator)
        return float(decimal_value.sqrt())


def _reduce(samples: list[tuple[float, float]], operation: str) -> float | None:
    if not samples:
        return None
    values = [value for value, _ in samples]
    weights = [Fraction.from_float(weight) for _, weight in samples]
    exact_values = [Fraction.from_float(value) for value in values]
    if operation == "count":
        return float(len(samples))
    if operation == "min":
        return min(values)
    if operation == "max":
        return max(values)
    if operation == "sum":
        return float(sum((weight * value for weight, value in zip(weights, exact_values)), Fraction()))
    if operation == "mean":
        return float(sum((weight * value for weight, value in zip(weights, exact_values)), Fraction()) / sum(weights))
    if operation in {"variance", "stdDev", "sampleVariance", "sampleStdDev"}:
        if operation.startswith("sample") and len(samples) < 2:
            return None
        total_weight = sum(weights)
        mean = sum((weight * value for weight, value in zip(weights, exact_values)), Fraction()) / total_weight
        variance = sum((weight * (value - mean) ** 2 for weight, value in zip(weights, exact_values)), Fraction())
        if operation.startswith("sample"):
            # The sample variants require unit weights and divide by n - 1.
            variance /= len(samples) - 1
        else:
            variance /= total_weight
        return _stddev(variance) if operation.endswith("StdDev") or operation == "stdDev" else float(variance)
    if operation == "product":
        product = math.prod(exact_values)
        return float(product)
    if operation == "median":
        ordered = sorted(exact_values)
        middle = len(ordered) // 2
        value = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        return float(value)
    if operation == "mode":
        frequencies = Counter(values)
        highest = max(frequencies.values())
        return min(value for value, frequency in frequencies.items() if frequency == highest)
    raise AssertionError(f"unhandled reference operation: {operation}")


def _reference(
    values: list[float | None], *, width: int, height: int, tile_cols: int, tile_rows: int,
    tile_keys: list[tuple[int, int]], coefficients: list[tuple[int, int, float]],
    operation: str, skip_masked: bool,
) -> list[float | None]:
    available = set(tile_keys)
    output: list[float | None] = [None] * (width * height)
    for tile_col, tile_row in available:
        for local_row in range(tile_rows):
            y = tile_row * tile_rows + local_row
            for local_col in range(tile_cols):
                x = tile_col * tile_cols + local_col
                center = values[y * width + x]
                if center is None and skip_masked:
                    continue
                samples = []
                for dx, dy, weight in coefficients:
                    neighbor_x = x + dx
                    neighbor_y = y + dy
                    if not (0 <= neighbor_x < width and 0 <= neighbor_y < height):
                        continue
                    if (neighbor_x // tile_cols, neighbor_y // tile_rows) not in available:
                        continue
                    value = values[neighbor_y * width + neighbor_x]
                    if value is not None:
                        samples.append((value, weight))
                try:
                    output[y * width + x] = _reduce(samples, operation)
                except OverflowError as error:
                    raise AssertionError("fixture unexpectedly overflows its final Float64 result") from error
    return output


def _spec(coefficients: list[tuple[int, int, float]], operation: str, skip_masked: bool) -> str:
    ordered = sorted(coefficients, key=lambda value: (value[1], value[0]))
    encoded = [[dx, dy, _bits(weight)] for dx, dy, weight in ordered]
    payload = {"coefficients": encoded, "operation": operation,
               "skip_masked": skip_masked, "v": 1}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _case(
    name: str, values: list[float | None], *, width: int, height: int, tile_cols: int,
    tile_rows: int, tile_keys: list[tuple[int, int]], coefficients: list[tuple[int, int, float]],
    operation: str, skip_masked: bool = True,
) -> dict:
    expected = _reference(values, width=width, height=height, tile_cols=tile_cols,
                          tile_rows=tile_rows, tile_keys=tile_keys, coefficients=coefficients,
                          operation=operation, skip_masked=skip_masked)
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
        "operation": operation,
        "skip_masked": skip_masked,
        "spec": _spec(coefficients, operation, skip_masked),
        "expected": [_bits(value) for value in expected],
    }


def make_fixture() -> dict:
    width, height = 6, 4
    all_keys = [(0, 0), (1, 0), (0, 1), (1, 1)]
    values = [float(index - 9) for index in range(width * height)]
    values[2] = None
    values[10] = None
    weighted = [(-1, 0, 0.5), (0, 0, 2.0), (1, 0, 1.25)]
    unit = [(-1, 0, 1.0), (0, 0, 1.0), (1, 0, 1.0)]
    maximum = float.fromhex("0x1.fffffffffffffp+1023")
    minimum_subnormal = math.ulp(0.0)
    cancellation = [1.0 if col % 2 == 0 else -1.0
                    for _row in range(height) for col in range(width)]
    near_large = [1.0e16, 1.0e16 + 2.0, 1.0e16 + 4.0]
    near_large += [1.0e16 + float((index % 3) * 2) for index in range(width * height - len(near_large))]
    tiny_weights = [(0, 0, minimum_subnormal), (1, 0, maximum)]
    huge_magnitudes = [maximum, -maximum] + [float(index) for index in range(width * height - 2)]
    cases = [
        _case("weighted-sum-exact-cancellation", cancellation, width=width, height=height,
              tile_cols=3, tile_rows=2, tile_keys=all_keys,
              coefficients=[(0, 0, 1.0e308), (1, 0, 1.0e308), (2, 0, 1.0e-308)], operation="sum"),
        _case("weighted-mean-overflowing-intermediates", huge_magnitudes, width=width, height=height,
              tile_cols=3, tile_rows=2, tile_keys=all_keys,
              coefficients=[(0, 0, 1.0e308), (1, 0, 1.0e308)], operation="mean"),
        _case("weighted-mean-subnormal-and-huge-weights", huge_magnitudes, width=width, height=height,
              tile_cols=3, tile_rows=2, tile_keys=all_keys, coefficients=tiny_weights, operation="mean"),
        _case("count-ignores-weight-magnitude", values, width=width, height=height,
              tile_cols=3, tile_rows=2, tile_keys=all_keys, coefficients=weighted, operation="count"),
        _case("minimum-ignores-weight-magnitude", values, width=width, height=height,
              tile_cols=3, tile_rows=2, tile_keys=all_keys, coefficients=weighted, operation="min"),
        _case("maximum-ignores-weight-magnitude", values, width=width, height=height,
              tile_cols=3, tile_rows=2, tile_keys=all_keys, coefficients=weighted, operation="max"),
        _case("weighted-variance-large-common-offset", near_large, width=width, height=height,
              tile_cols=3, tile_rows=2, tile_keys=all_keys,
              coefficients=[(-1, 0, 1.0), (0, 0, 2.0), (1, 0, 1.0)], operation="variance"),
        _case("weighted-stddev-tiny-weights", huge_magnitudes, width=width, height=height,
              tile_cols=3, tile_rows=2, tile_keys=all_keys,
              coefficients=[(0, 0, minimum_subnormal), (1, 0, 1.0)], operation="stdDev"),
        _case("sample-variance", values, width=width, height=height,
              tile_cols=3, tile_rows=2, tile_keys=all_keys, coefficients=unit, operation="sampleVariance"),
        _case("sample-stddev", values, width=width, height=height,
              tile_cols=3, tile_rows=2, tile_keys=all_keys, coefficients=unit, operation="sampleStdDev"),
        _case("sample-single-support-no-data", values, width=width, height=height,
              tile_cols=3, tile_rows=2, tile_keys=all_keys, coefficients=[(0, 0, 1.0)],
              operation="sampleVariance"),
        _case("product-subnormal-rounding", [minimum_subnormal, 0.5, 2.0] + [1.0] * 21,
              width=width, height=height, tile_cols=3, tile_rows=2, tile_keys=all_keys,
              coefficients=[(0, 0, 1.0), (1, 0, 1.0), (2, 0, 1.0)], operation="product"),
        _case("median-overflow-safe-even", [-maximum, maximum] + [0.0] * 22,
              width=width, height=height, tile_cols=3, tile_rows=2, tile_keys=all_keys,
              coefficients=[(0, 0, 1.0), (1, 0, 1.0)], operation="median"),
        _case("mode-lowest-frequency-tie", [1.0, 2.0, 3.0] + [4.0] * 21,
              width=width, height=height, tile_cols=3, tile_rows=2, tile_keys=all_keys,
              coefficients=[(0, 0, 1.0), (1, 0, 1.0), (2, 0, 1.0)], operation="mode"),
        _case("skip-masked-center", [None, 9.0] + [float(index) for index in range(22)],
              width=width, height=height, tile_cols=3, tile_rows=2, tile_keys=all_keys,
              coefficients=[(-1, 0, 1.0), (1, 0, 1.0)], operation="mean", skip_masked=True),
        _case("fill-only-existing-masked-centers", [None, 9.0] + [float(index) for index in range(22)],
              width=width, height=height, tile_cols=3, tile_rows=2, tile_keys=all_keys,
              coefficients=[(-1, 0, 1.0), (1, 0, 1.0)], operation="mean", skip_masked=False),
        _case("empty-support-is-no-data", [None] * 24, width=width, height=height,
              tile_cols=3, tile_rows=2, tile_keys=all_keys, coefficients=[(0, 0, 1.0)],
              operation="count", skip_masked=False),
        _case("missing-tile-is-omitted", values, width=width, height=height,
              tile_cols=3, tile_rows=2, tile_keys=[(0, 0), (0, 1), (1, 1)],
              coefficients=[(0, 0, 1.0), (1, 0, 1.0)], operation="mean"),
        _case("radius-zero-direct", values, width=width, height=height,
              tile_cols=3, tile_rows=2, tile_keys=all_keys, coefficients=[(0, 0, 1.0)], operation="mean"),
    ]
    return {
        "cases": cases,
        "case_count": len(cases),
        "pixel_count": sum(len(case["expected"]) for case in cases),
        "reject_overflow": {"value_bits": _bits(maximum), "weight_bits": _bits(2.0)},
        "reject_bad_variance": {"value_bits": _bits(1.0)},
    }
