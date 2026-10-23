"""Deterministic tile cases for native compact QR/SVD factor validation."""
from __future__ import annotations

import json
import math
from typing import Any


def _encode(value: float) -> str:
    return "NaN" if math.isnan(value) else float(value).hex()


def canonical_spec(op: str, rows: int, cols: int, operands: list[dict[str, int]]) -> str:
    return json.dumps({"v": 1, "op": op, "rows": rows, "cols": cols,
                       "rhs_cols": 0, "operands": operands},
                      sort_keys=True, separators=(",", ":"))


def _case(label: str, op: str, matrix: list[list[float]], rank: int, *, mask: bool = False,
          singular_values: list[float] | None = None) -> dict[str, Any]:
    rows = len(matrix)
    cols = len(matrix[0])
    if rows == 0 or cols == 0 or any(len(row) != cols for row in matrix):
        raise ValueError("orthogonal fixtures require non-empty rectangular matrices")
    if op not in {"qr", "svd"}:
        raise ValueError("orthogonal fixture operations must be qr or svd")
    operands = [{"band": index} for index in range(rows * cols)]
    result = {
        "label": label,
        "op": op,
        "rows": rows,
        "cols": cols,
        "rank": rank,
        "mask": mask,
        "spec": canonical_spec(op, rows, cols, operands),
        "input_bands": [[_encode(matrix[index // cols][index % cols])]
                        for index in range(rows * cols)],
    }
    if singular_values is not None:
        result["singular_values"] = [float(value).hex() for value in singular_values]
    return result


def _invalid_specs() -> list[str]:
    def spec(op: str, rows: int, cols: int, rhs: int = 0) -> str:
        cells = rows * cols
        operands = [{"band": index} for index in range(cells)]
        result = {"v": 1, "op": op, "rows": rows, "cols": cols,
                  "rhs_cols": rhs, "operands": operands}
        return json.dumps(result, sort_keys=True, separators=(",", ":"))

    return [
        spec("qr", 2, 2, 1),
        spec("svd", 2, 2, 1),
        spec("qr", 8, 8),
        spec("svd", 8, 8),
        spec("qr", 9, 1),
        spec("svd", 1, 9),
    ]


def make_fixture() -> dict[str, Any]:
    minimum = math.ulp(0.0)
    next_one = math.nextafter(1.0, math.inf)
    tall_8x4 = [[float(row + col + 1) if row == col else 0.0
                 for col in range(4)] for row in range(8)]
    wide_4x8 = [[float(row + col + 1) if row == col else 0.0
                 for col in range(8)] for row in range(4)]
    dense_7x5 = [
        [8.0, 1.0, 1.0, 1.0, 1.0],
        [1.0, 8.0, 1.0, 1.0, 1.0],
        [1.0, 1.0, 8.0, 1.0, 1.0],
        [1.0, 1.0, 1.0, 8.0, 1.0],
        [1.0, 1.0, 1.0, 1.0, 8.0],
        [2.0, 3.0, 4.0, 5.0, 6.0],
        [6.0, 5.0, 4.0, 3.0, 2.0],
    ]
    cases = [
        _case("qr_square", "qr", [[3.0, 1.0], [4.0, 2.0]], 2),
        _case("qr_tall", "qr", [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]], 2),
        _case("qr_wide", "qr", [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], 2),
        _case("qr_rank_deficient", "qr", [[1.0, 2.0], [2.0, 4.0], [3.0, 6.0]], 1),
        _case("qr_dense_7x5_output_60", "qr", dense_7x5, 5),
        _case("qr_zero", "qr", [[0.0, 0.0], [0.0, 0.0]], 0),
        _case("qr_tiny_trailing_diagonal", "qr", [[1.0, 1.0], [0.0, minimum]], 2),
        _case("qr_extreme_magnitude", "qr", [[1e308, 1e308], [1e308, -1e308]], 2),
        _case("qr_8x4_mixed_extreme_outside_budget", "qr",
              [[1e308, 0.0, 0.0, 0.0],
               [0.0, 1.0, 0.0, 0.0],
               [0.0, 0.0, 1.0, 0.0],
               [0.0, 0.0, 0.0, minimum],
               [0.0, 0.0, 0.0, 0.0],
               [0.0, 0.0, 0.0, 0.0],
               [0.0, 0.0, 0.0, 0.0],
               [0.0, 0.0, 0.0, 0.0]], 4),
        _case("qr_norm_overflow_masks_whole_factor", "qr",
              [[1.7e308, 0.0], [1.7e308, 1.0]], 2, mask=True),
        _case("svd_square", "svd", [[3.0, 0.0], [0.0, 1.0]], 2),
        _case("svd_tall", "svd", [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]], 2),
        _case("svd_wide", "svd", [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], 2),
        _case("svd_rank_deficient", "svd", [[1.0, 2.0], [2.0, 4.0]], 1),
        _case("svd_zero", "svd", [[0.0, 0.0], [0.0, 0.0]], 0),
        _case("svd_repeated_singular_values", "svd", [[1.0, 0.0], [0.0, 1.0]], 2),
        _case("svd_near_full_rank_exact_rank", "svd", [[1.0, 1.0], [1.0, next_one]], 2),
        _case("svd_extreme_diagonal_keeps_subnormal", "svd",
              [[1e308, 0.0], [0.0, minimum]], 2),
        _case("svd_reduction_overflow_fallback", "svd",
              [[1e308, 1e308], [0.0, 1e-20]], 2,
              singular_values=[math.sqrt(2.0) * 1e308, 1e-20 / math.sqrt(2.0)]),
        _case("svd_subnormal_right_rotation", "svd",
              [[1e308, 1e-308], [0.0, 1e-308]], 2,
              singular_values=[1e308, 1e-308]),
        _case("svd_rank_deficient_tiny_active_direction", "svd",
              [[1e100, 1e100, 2e100], [0.0, 1e-200, 1e-200], [0.0, 0.0, 0.0]], 2,
              singular_values=[math.sqrt(6.0) * 1e100, 1e-200 / math.sqrt(2.0), 0.0]),
        _case("svd_norm_overflow_masks_whole_factor", "svd",
              [[1.7e308, 1.7e308], [0.0, 0.0]], 1, mask=True),
        _case("svd_8x4_output_exactly_64", "svd", tall_8x4, 4),
        _case("svd_4x8_output_exactly_64", "svd", wide_4x8, 4),
        _case("svd_nan_masks_whole_factor", "svd", [[1.0, 0.0], [0.0, math.nan]], 0,
              mask=True),
    ]
    return {
        "schema": "local-ee-matrix-orthogonal-kernel-synthetic/v1",
        "case_count": len(cases),
        "output_cell_counts": [
            (case["rows"] * min(case["rows"], case["cols"])
             + min(case["rows"], case["cols"]) * case["cols"])
            if case["op"] == "qr" else
            (case["rows"] * p + p * p + case["cols"] * p)
            for case in cases
            for p in [min(case["rows"], case["cols"])]
        ],
        "pixel_count": len(cases),
        "cases": cases,
        "invalid_specs": _invalid_specs(),
    }
