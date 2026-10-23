"""Independent NumPy/Fraction fixtures for the native matrix-values kernel."""
from __future__ import annotations

import json
import math
import struct
from fractions import Fraction
from typing import Any

import numpy as np


def binary64_hex(value: float | int) -> str:
    return struct.pack(">d", float(value)).hex()


def _encode(value: float | int | None) -> str:
    if value is None or (isinstance(value, (float, np.floating)) and math.isnan(float(value))):
        return "NaN"
    return float(value).hex()


def _band(index: int) -> dict[str, int]:
    return {"band": index}


def _constant(value: float | int) -> dict[str, str]:
    return {"constant": binary64_hex(value)}


def canonical_spec(op: str, rows: int, cols: int, rhs_cols: int,
                   operands: list[dict[str, int | str]]) -> str:
    return json.dumps({
        "v": 1, "op": op, "rows": rows, "cols": cols,
        "rhs_cols": rhs_cols, "operands": operands,
    }, sort_keys=True, separators=(",", ":"))


def _gaussian_fraction_solve(matrix: list[list[Fraction]], rhs: list[list[Fraction]]) -> list[list[Fraction]]:
    size = len(matrix)
    width = len(rhs[0])
    work = [list(matrix[row]) + list(rhs[row]) for row in range(size)]
    for pivot in range(size):
        selected = next((row for row in range(pivot, size) if work[row][pivot]), None)
        if selected is None:
            raise ValueError("fraction oracle matrix is singular")
        work[pivot], work[selected] = work[selected], work[pivot]
        divisor = work[pivot][pivot]
        work[pivot] = [value / divisor for value in work[pivot]]
        for row in range(size):
            if row == pivot:
                continue
            factor = work[row][pivot]
            work[row] = [left - factor * right for left, right in zip(work[row], work[pivot])]
    return [row[size:size + width] for row in work]


def _fraction_least_squares(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    rows, cols = a.shape
    if rows < cols:
        raise ValueError("fraction oracle only handles full-column-rank shapes")
    exact_a = [[Fraction.from_float(float(a[r, c])) for c in range(cols)] for r in range(rows)]
    exact_b = [[Fraction.from_float(float(b[r, c])) for c in range(b.shape[1])] for r in range(rows)]
    gram = [[sum((exact_a[r][i] * exact_a[r][j] for r in range(rows)), Fraction())
             for j in range(cols)] for i in range(cols)]
    projected = [[sum((exact_a[r][i] * exact_b[r][j] for r in range(rows)), Fraction())
                  for j in range(b.shape[1])] for i in range(cols)]
    return np.array([[float(value) for value in row]
                     for row in _gaussian_fraction_solve(gram, projected)], dtype=np.float64)


def _fraction_inverse(a: np.ndarray) -> np.ndarray:
    size = a.shape[0]
    exact = [[Fraction.from_float(float(a[r, c])) for c in range(size)] for r in range(size)]
    identity = [[Fraction(int(r == c)) for c in range(size)] for r in range(size)]
    return np.array([[float(value) for value in row]
                     for row in _gaussian_fraction_solve(exact, identity)], dtype=np.float64)


def _fraction_ratio(value: float, numerator: float, denominator: float) -> float:
    exact = Fraction.from_float(float(value)) * Fraction.from_float(float(numerator))
    exact /= Fraction.from_float(float(denominator))
    try:
        return float(exact)
    except OverflowError:
        return math.inf if exact.numerator >= 0 else -math.inf


def _reference(op: str, a: np.ndarray, b: np.ndarray | None, oracle: str) -> list[float | None]:
    rows, cols = a.shape
    if not np.isfinite(a).all() or (b is not None and not np.isfinite(b).all()):
        output_cells = cols * (b.shape[1] if op == "solve" and b is not None else rows)
        return [None] * output_cells
    scale = float(np.max(np.abs(a)))
    output_cols = b.shape[1] if op == "solve" and b is not None else rows
    output_cells = cols * output_cols
    if scale == 0.0:
        return [None] * output_cells if op == "inverse" else [0.0] * output_cells

    normalized = a / scale
    singular = np.linalg.svd(normalized, compute_uv=False)
    threshold = max(rows, cols) * float(singular[0]) * (2.0 ** -52)
    rank = int(np.count_nonzero(singular > threshold))
    if op == "inverse" and rank < cols:
        return [None] * output_cells
    if op == "solve":
        assert b is not None
        if rank == 0:
            return [0.0] * output_cells
        if oracle == "fraction":
            result = _fraction_least_squares(a, b)
        else:
            pseudo = np.linalg.pinv(normalized, rcond=max(rows, cols) * (2.0 ** -52))
            result = np.empty((cols, b.shape[1]), dtype=np.float64)
            for row in range(cols):
                for rhs in range(b.shape[1]):
                    exact_dot = sum((Fraction.from_float(float(pseudo[row, r])) *
                                     Fraction.from_float(float(b[r, rhs]))
                                     for r in range(rows)), Fraction())
                    exact_dot /= Fraction.from_float(scale)
                    try:
                        result[row, rhs] = float(exact_dot)
                    except OverflowError:
                        result[row, rhs] = math.inf if exact_dot.numerator >= 0 else -math.inf
    else:
        if oracle == "fraction" and op == "inverse":
            pseudo = _fraction_inverse(a)
        else:
            pseudo = np.linalg.pinv(normalized, rcond=max(rows, cols) * (2.0 ** -52))
            pseudo = np.array([[_fraction_ratio(float(pseudo[r, c]), 1.0, scale)
                                for c in range(rows)] for r in range(cols)], dtype=np.float64)
        result = pseudo
    flattened = [float(value) for value in np.asarray(result).reshape(-1)]
    if not all(math.isfinite(value) for value in flattened):
        return [None] * output_cells
    return flattened


def _case(label: str, op: str, matrices: list[np.ndarray], rhs_matrices: list[np.ndarray] | None = None,
          *, operands: list[dict[str, int | str]] | None = None, oracle: str = "numpy",
          absolute_tolerance: float = 1e-12, relative_tolerance: float = 1e-10,
          require_nonzero: list[tuple[int, int]] | None = None) -> dict[str, Any]:
    rows, cols = matrices[0].shape
    rhs_cols = rhs_matrices[0].shape[1] if op == "solve" and rhs_matrices is not None else 0
    input_cells = rows * cols + (rows * rhs_cols if op == "solve" else 0)
    selected_operands = operands or [_band(index) for index in range(input_cells)]
    band_indices = sorted({int(item["band"]) for item in selected_operands if "band" in item})
    if not band_indices or band_indices != list(range(max(band_indices) + 1)):
        raise ValueError("fixture references must include contiguous source bands from zero")
    band_values: list[list[float]] = [[] for _ in band_indices]
    expected_pixels: list[list[float | None]] = []
    for pixel, a in enumerate(matrices):
        if a.shape != (rows, cols):
            raise ValueError("matrix fixture shapes must match")
        b = rhs_matrices[pixel] if op == "solve" and rhs_matrices is not None else None
        flattened = [float(value) for value in a.reshape(-1)]
        if op == "solve":
            assert b is not None and b.shape == (rows, rhs_cols)
            flattened.extend(float(value) for value in b.reshape(-1))
        pixel_bands: list[float | None] = [None] * len(band_indices)
        for position, operand in enumerate(selected_operands):
            raw = flattened[position]
            if "band" in operand:
                band = int(operand["band"])
                previous = pixel_bands[band]
                if previous is not None and struct.pack(">d", previous) != struct.pack(">d", raw):
                    raise ValueError("reused fixture band operands must refer to the same source value")
                pixel_bands[band] = raw
            else:
                expected_constant = struct.unpack(">d", bytes.fromhex(str(operand["constant"])))[0]
                if struct.pack(">d", expected_constant) != struct.pack(">d", raw):
                    raise ValueError("fixture constant operand differs from its matrix value")
        if any(value is None for value in pixel_bands):
            raise ValueError("every fixture source band must be referenced")
        for index, value in enumerate(pixel_bands):
            band_values[index].append(float(value))
        expected_pixels.append(_reference(op, a, b, oracle))

    output_cells = len(expected_pixels[0])
    nonzero_checks = require_nonzero or []
    for band, pixel in nonzero_checks:
        if not (0 <= band < output_cells and 0 <= pixel < len(expected_pixels)):
            raise ValueError("required nonzero output is outside the fixture result")
        expected_value = expected_pixels[pixel][band]
        if expected_value is None or expected_value == 0.0:
            raise ValueError("required nonzero output must have a finite nonzero oracle value")
    expected_bands = [
        [_encode(expected_pixels[pixel][cell]) for pixel in range(len(expected_pixels))]
        for cell in range(output_cells)
    ]
    return {
        "label": label,
        "op": op,
        "rows": rows,
        "cols": cols,
        "rhs_cols": rhs_cols,
        "spec": canonical_spec(op, rows, cols, rhs_cols, selected_operands),
        "input_bands": [[_encode(value) for value in band] for band in band_values],
        "expected": expected_bands,
        "absolute_tolerance": absolute_tolerance,
        "relative_tolerance": relative_tolerance,
        "require_nonzero": [[band, pixel] for band, pixel in nonzero_checks],
        "oracle": oracle,
    }


def _invalid_specs() -> list[str]:
    valid = canonical_spec("solve", 1, 1, 1, [_band(0), _band(1)])
    cases = [
        json.dumps({"v": 1, "op": "solve", "rows": 1, "cols": 1,
                    "rhs_cols": 1, "operands": [_band(0), _band(1)]}, separators=(",", ":")),
        valid.replace(",", ", ", 1),
        canonical_spec("solve", 0, 1, 1, [_band(0), _band(1)]),
        canonical_spec("solve", 9, 1, 1, [_band(0)] * 10),
        canonical_spec("unknown", 1, 1, 1, [_band(0), _band(1)]),
        canonical_spec("solve", 1, 1, 0, [_band(0)]),
        canonical_spec("inverse", 1, 2, 0, [_band(0), _band(1)]),
        canonical_spec("pinverse", 1, 1, 1, [_band(0), _band(1)]),
        canonical_spec("solve", 8, 8, 1, [_band(i) for i in range(72)]),
        canonical_spec("solve", 1, 1, 1, [_band(0), _band(2)]),
        canonical_spec("solve", 1, 1, 1, [_band(64), _band(0)]),
        canonical_spec("solve", 1, 1, 1, [_constant(1), _constant(2)]),
        canonical_spec("solve", 1, 1, 1,
                       [_band(0), {"constant": "7ff0000000000000"}]),
        canonical_spec("solve", 1, 1, 1,
                       [_band(0), {"constant": "ABCDEF0123456789"}]),
        " " * 8193,
        '{"cols":1,"cols":1,"op":"solve","operands":[],"rhs_cols":1,"rows":1,"v":1}',
    ]
    return cases


def make_fixture() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    cases.append(_case("solve_tall_multi_rhs_and_mask", "solve", [
        np.array([[1., 2.], [0., 1.], [2., 1.]]),
        np.array([[1., 0.], [0., 1.], [1., 1.]]),
    ], [
        np.array([[3., 1.], [1., 2.], [4., 0.]]),
        np.array([[1., 2.], [3., 4.], [math.nan, 6.]]),
    ]))
    cases.append(_case("solve_wide_minimum_norm", "solve", [
        np.array([[1., 0., 1.], [0., 1., 1.]]),
    ], [np.array([[2., 0.], [3., 4.]])]))
    cases.append(_case("solve_rank_deficient_minimum_norm", "solve", [
        np.array([[1., 2.], [2., 4.], [3., 6.]]),
    ], [np.array([[1.], [2.], [3.]])]))
    cases.append(_case("inverse_fraction_and_singular_mask", "inverse", [
        np.array([[4., 7.], [2., 6.]]),
        np.array([[1., 2.], [2., 4.]]),
    ], oracle="fraction"))
    cases.append(_case("pinverse_tall", "pinverse", [
        np.array([[1., 0.], [0., 1.], [1., 1.]]),
    ]))
    cases.append(_case("pinverse_wide", "pinverse", [
        np.array([[1., 0., 1.], [0., 1., 1.]]),
    ]))
    cases.append(_case("zero_matrix_solve", "solve", [
        np.zeros((2, 3)),
    ], [np.array([[5.], [-7.]])]))
    cases.append(_case("zero_matrix_pinverse", "pinverse", [np.zeros((2, 3))]))
    cases.append(_case("subnormal_matrix_and_scaled_rhs", "solve", [
        np.array([[float.fromhex("0x0.0000000000001p-1022"), 0.],
                  [0., float.fromhex("0x0.0000000000001p-1022")]]),
    ], [np.array([[float.fromhex("0x0.0000000000001p-1022"), 0.],
                  [0., float.fromhex("0x0.0000000000001p-1022")]])]))
    cases.append(_case("tiny_a_tiny_and_huge_rhs_columns", "solve", [
        np.array([[1e-16, 0.], [0., 1e-16]]),
    ], [np.array([[float.fromhex("0x0.0000000000001p-1022"), 0.],
                  [0., 1e292]])], absolute_tolerance=0.0, relative_tolerance=1e-12,
        require_nonzero=[(0, 0), (3, 0)]))
    cases.append(_case("huge_orthogonal_rhs_component", "solve", [
        np.array([[1e-308], [0.]]),
    ], [np.array([[float.fromhex("0x0.0000000000001p-1022")], [1e308]])],
        absolute_tolerance=0.0, relative_tolerance=1e-12, require_nonzero=[(0, 0)]))
    cases.append(_case("overflowing_scale_ratio_with_finite_result", "solve", [
        np.array([[1e-308], [0.]]),
    ], [np.array([[1.], [1e308]])]))
    cases.append(_case("overflow_result_masks_whole_matrix", "solve", [
        np.diag([1e-308, 1e-308]),
    ], [np.array([[1e308], [1e-308]])]))
    cases.append(_case("large_common_baseline_fraction_intercept_slope", "solve", [
        np.array([[1., 0.], [1., 1.], [1., 2.], [1., 3.]]),
    ], [np.array([[2.**40], [2.**40 + 3.], [2.**40 + 6.], [2.**40 + 9.]])],
        oracle="fraction", absolute_tolerance=1e-10, relative_tolerance=0.0))
    cases.append(_case("large_matrix_and_rhs_offsets", "solve", [
        np.array([[1e15, 0.], [0., 1e15]]),
    ], [np.array([[1e15 + 2., 3.], [4., 1e15 - 5.]])]))
    cutoff = 2.0 * float(np.finfo(np.float64).eps)
    boundary_values = [math.nextafter(cutoff, 0.0), cutoff, math.nextafter(cutoff, math.inf)]
    cases.append(_case("local_rank_threshold_below_exact_above", "solve", [
        np.diag([1.0, value]) for value in boundary_values
    ], [np.eye(2) for _ in boundary_values], absolute_tolerance=1e-7,
        relative_tolerance=1e-10))
    cases.append(_case("constant_operand_wire", "solve", [
        np.array([[1., 1.]]), np.array([[2., 1.]]),
    ], [np.array([[1.]]), np.array([[1.]])],
        operands=[_band(0), _constant(1.), _constant(1.)]))
    cases.append(_case("max_shape_and_band_63", "pinverse", [
        np.eye(8),
    ]))
    cases.append(_case("max_solve_input_cells_64", "solve", [
        np.pad(np.eye(7), ((0, 1), (0, 0))),
    ], [np.arange(1., 9.).reshape(8, 1)]))

    return {
        "schema": "local-ee-matrix-values-synthetic/v1",
        "case_count": len(cases),
        "pixel_count": sum(len(case["input_bands"][0]) for case in cases),
        "cases": cases,
        "invalid_specs": _invalid_specs(),
    }
