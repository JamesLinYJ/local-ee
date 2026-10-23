"""Independent Fraction/NumPy fixtures for native matrix factorization."""
from __future__ import annotations

import json
import math
import struct
from fractions import Fraction
from typing import Any

import numpy as np


def _encode(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "NaN"
    return float(value).hex()


def _encode_input(value: float) -> str:
    return "NaN" if math.isnan(value) else float(value).hex()


def canonical_spec(op: str, rows: int, cols: int, rhs_cols: int,
                   operands: list[dict[str, int | str]]) -> str:
    return json.dumps({"v": 1, "op": op, "rows": rows, "cols": cols,
                       "rhs_cols": rhs_cols, "operands": operands},
                      sort_keys=True, separators=(",", ":"))


def _fraction_float(value: Fraction) -> float:
    try:
        return float(value)
    except OverflowError:
        return math.inf if value >= 0 else -math.inf


def _fraction_lu(matrix: np.ndarray) -> list[float] | None:
    size = matrix.shape[0]
    upper = [[Fraction.from_float(float(matrix[row, col])) for col in range(size)]
             for row in range(size)]
    lower = [[Fraction(int(row == col)) for col in range(size)] for row in range(size)]
    permutation = list(range(size))
    for pivot in range(size):
        # max returns the earliest row on ties, matching first-maximum partial pivoting.
        selected = max(range(pivot, size), key=lambda row: abs(upper[row][pivot]))
        if upper[selected][pivot] == 0:
            return None
        if selected != pivot:
            upper[pivot], upper[selected] = upper[selected], upper[pivot]
            permutation[pivot], permutation[selected] = permutation[selected], permutation[pivot]
            for col in range(pivot):
                lower[pivot][col], lower[selected][col] = lower[selected][col], lower[pivot][col]
        for row in range(pivot + 1, size):
            factor = upper[row][pivot] / upper[pivot][pivot]
            lower[row][pivot] = factor
            for col in range(pivot + 1, size):
                upper[row][col] -= factor * upper[pivot][col]
            upper[row][pivot] = Fraction()
    permutation_matrix = [[Fraction(int(permutation[row] == col)) for col in range(size)]
                          for row in range(size)]
    return [_fraction_float(value) for part in (lower, upper, permutation_matrix)
            for row in part for value in row]


def _reference(op: str, matrix: np.ndarray) -> list[float | None]:
    size = matrix.shape[0]
    output_count = (3 if op == "lu" else 1) * size * size
    if not np.isfinite(matrix).all():
        return [None] * output_count
    if op == "cholesky":
        if not np.array_equal(matrix, matrix.T):
            return [None] * output_count
        try:
            result = np.linalg.cholesky(matrix)
        except np.linalg.LinAlgError:
            return [None] * output_count
        flattened = [float(value) for value in result.reshape(-1)]
    else:
        flattened = _fraction_lu(matrix) or [None] * output_count
    if len(flattened) != output_count or not all(
        value is None or math.isfinite(value) for value in flattened
    ):
        return [None] * output_count
    return flattened


def _case(label: str, op: str, matrices: list[np.ndarray], *,
          absolute_tolerance: float = 0.0, relative_tolerance: float = 2e-14,
          require_nonzero: list[tuple[int, int]] | None = None) -> dict[str, Any]:
    size = matrices[0].shape[0]
    if any(matrix.shape != (size, size) for matrix in matrices):
        raise ValueError("factor fixtures must use a shared square shape")
    expected_pixels = [_reference(op, matrix) for matrix in matrices]
    output_count = len(expected_pixels[0])
    expected = [[_encode(expected_pixels[pixel][cell]) for pixel in range(len(matrices))]
                for cell in range(output_count)]
    checks = require_nonzero or []
    for band, pixel in checks:
        if expected_pixels[pixel][band] in (None, 0.0):
            raise ValueError("required nonzero output must be finite and nonzero")
    return {
        "label": label,
        "op": op,
        "rows": size,
        "cols": size,
        "rhs_cols": 0,
        "spec": canonical_spec(op, size, size, 0,
                               [{"band": index} for index in range(size * size)]),
        "input_bands": [[_encode_input(float(matrix.reshape(-1)[cell])) for matrix in matrices]
                        for cell in range(size * size)],
        "expected": expected,
        "absolute_tolerance": absolute_tolerance,
        "relative_tolerance": relative_tolerance,
        "require_nonzero": [[band, pixel] for band, pixel in checks],
        "oracle": "numpy" if op == "cholesky" else "fraction",
    }


def _invalid_specs() -> list[str]:
    valid_square = [{"band": index} for index in range(4)]
    return [
        canonical_spec("cholesky", 2, 3, 0, [{"band": index} for index in range(6)]),
        canonical_spec("lu", 2, 3, 0, [{"band": index} for index in range(6)]),
        canonical_spec("cholesky", 2, 2, 1, valid_square),
        canonical_spec("lu", 2, 2, 1, valid_square),
        canonical_spec("cholesky", 9, 9, 0, [{"band": index} for index in range(64)]),
        canonical_spec("lu", 5, 5, 0, [{"band": index} for index in range(25)]),
        canonical_spec("cholesky", 1, 1, 0, [{"constant": "3ff0000000000000"}]),
    ]


def make_fixture() -> dict[str, Any]:
    minimum_subnormal = float.fromhex("0x0.0000000000001p-1022")
    next_one = math.nextafter(1.0, math.inf)
    max_cholesky = np.eye(8, dtype=np.float64)
    for row in range(8):
        for col in range(row):
            max_cholesky[row, col] = max_cholesky[col, row] = float((row + 1) * (col + 1)) / 128.0
        max_cholesky[row, row] += float(row + 2)

    cases = [
        _case("cholesky_spd", "cholesky", [np.array([[4., 2.], [2., 3.]])]),
        _case("cholesky_exact_symmetry_rejects", "cholesky", [np.array([[2., 1.], [1. + 1e-15, 2.]])]),
        _case("cholesky_zero_pivot_masks_all", "cholesky", [np.array([[1., 1.], [1., 1.]])]),
        _case("cholesky_negative_pivot_masks_all", "cholesky", [np.diag([2., -1.])]),
        _case("cholesky_near_spd", "cholesky", [np.array([[1., 1.], [1., next_one]])],
              relative_tolerance=2e-14, absolute_tolerance=0.0,
              require_nonzero=[(3, 0)]),
        _case("cholesky_extreme_original_scale", "cholesky", [np.diag([1e308, 1e-308])],
              relative_tolerance=2e-14, require_nonzero=[(3, 0)]),
        _case("cholesky_subnormal_diagonal", "cholesky", [np.diag([minimum_subnormal, 4.])],
              relative_tolerance=2e-14, require_nonzero=[(0, 0)]),
        _case("cholesky_max_shape_64_cells", "cholesky", [max_cholesky]),
        _case("cholesky_nan_masks_all", "cholesky", [np.array([[2., 0.], [0., math.nan]])]),
        _case("lu_pivot_swap_and_first_tie", "lu", [np.array([[0., 2., 1.],
                                                                 [2., 3., 4.],
                                                                 [-2., 5., 7.]])]),
        _case("lu_later_swap_preserves_prior_l", "lu", [np.array([[2., 1., 1.],
                                                                  [4., 3., 3.],
                                                                  [1., 5., 6.]])]),
        _case("lu_near_singular_exact_rational", "lu", [np.array([[1., 1.], [1., next_one]])],
              relative_tolerance=0.0, absolute_tolerance=0.0,
              require_nonzero=[(7, 0)]),
        _case("lu_singular_pivot_masks_all", "lu", [np.array([[1., 2.], [2., 4.]])]),
        _case("lu_singular_nonbinary_pivot_masks_all", "lu", [np.array([[3., 3.], [1., 1.]])]),
        _case("lu_dependent_3x3_masks_all", "lu", [np.array([[1., 2., 3.],
                                                              [4., 5., 6.],
                                                              [5., 7., 9.]])]),
        _case("lu_subnormal_pivot_is_preserved", "lu", [np.diag([1., minimum_subnormal])],
              relative_tolerance=0.0, absolute_tolerance=0.0,
              require_nonzero=[(7, 0)]),
        _case("lu_overflow_masks_all_factors", "lu", [np.array([[1., 1e308], [-1., 1e308]])]),
        _case("lu_max_shape_output_48_cells", "lu", [np.array([[0., 1., 0., 2.],
                                                                 [1., 2., 3., 4.],
                                                                 [2., 1., 5., 3.],
                                                                 [3., 7., 2., 1.]])]),
    ]
    for case in cases:
        if case["op"] == "lu":
            # Fraction -> binary64 is correctly rounded; native output must match exactly.
            case["absolute_tolerance"] = 0.0
            case["relative_tolerance"] = 0.0
    return {
        "schema": "local-ee-matrix-factor-kernel-synthetic/v1",
        "case_count": len(cases),
        "pixel_count": sum(len(case["input_bands"][0]) for case in cases),
        "cases": cases,
        "invalid_specs": _invalid_specs(),
    }
