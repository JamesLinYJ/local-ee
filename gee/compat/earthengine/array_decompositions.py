"""Bounded square static matrix QR, LU, and singular-value decompositions.

QR and SVD use NumPy/LAPACK. Their signs and bases in repeated singular-value
spaces are local solver results and are not guaranteed to match Earth Engine's
EJML implementation. LU uses first-maximum partial pivoting as a local policy.
"""
from __future__ import annotations

import numpy as np

from .array_core import MAX_ARRAY_CELLS, charge_array, require_matrix, wrap_array
from .ir import fail


ARRAY_DECOMPOSITION_FUNCTIONS = frozenset({
    "Array.matrixQRDecomposition",
    "Array.matrixLUDecomposition",
    "Array.matrixSingularValueDecomposition",
})


def _required(arguments, name):
    if "array" not in arguments:
        fail(f"{name} requires the array argument")
    return arguments["array"]


def _square(matrix, name):
    if matrix.shape[0] != matrix.shape[1]:
        fail(f"{name} currently requires a square matrix")
    return matrix.shape[0]


def _preflight(translator, name, n):
    outputs, factor = {
        "Array.matrixQRDecomposition": (2, 4),
        "Array.matrixLUDecomposition": (3, 2),
        "Array.matrixSingularValueDecomposition": (3, 8),
    }[name]
    output_cells = outputs * n * n
    if output_cells > MAX_ARRAY_CELLS:
        fail(f"{name} combined result exceeds 10000 cells")
    # Charge a conservative dense-factorization bound plus materialization
    # before making Float64 copies or invoking NumPy's numerical kernels.
    charge_array(translator, factor * n * n * n + 6 * n * n)


def _float_matrix(matrix):
    # Called only after shape, output-cell and shared-work preflight checks.
    return np.asarray(matrix, dtype=np.float64)


def _finite(result, name):
    if not np.isfinite(result).all():
        fail(f"{name} must produce finite Float64 results")
    return result


def _lu(matrix, name):
    """Return P, L, U with P @ matrix = L @ U, using partial pivoting."""
    n = matrix.shape[0]
    upper = matrix.copy()
    lower = np.eye(n, dtype=np.float64)
    permutation = np.eye(n, dtype=np.int64)
    for column in range(n):
        # np.argmax selects the first maximum, including exact pivot ties.
        pivot_row = column + int(np.argmax(np.abs(upper[column:, column])))
        if pivot_row != column:
            upper[[column, pivot_row], :] = upper[[pivot_row, column], :]
            permutation[[column, pivot_row], :] = permutation[[pivot_row, column], :]
            if column:
                lower[[column, pivot_row], :column] = lower[[pivot_row, column], :column]

        pivot = upper[column, column]
        if pivot == 0.0:
            fail(f"{name} encountered an exact zero pivot; singular LU is unsupported")
        if not np.isfinite(pivot):
            fail(f"{name} must produce finite Float64 results")
        for row in range(column + 1, n):
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                multiplier = upper[row, column] / pivot
                lower[row, column] = multiplier
                upper[row, column] = 0.0
                upper[row, column + 1:] -= multiplier * upper[column, column + 1:]
            if not np.isfinite(lower[row, column]) or not np.isfinite(upper[row, column:]).all():
                fail(f"{name} must produce finite Float64 results")
    return permutation, lower, upper


def invoke_decomposition(translator, name, arguments):
    """Evaluate one supported static matrix decomposition."""
    if name not in ARRAY_DECOMPOSITION_FUNCTIONS:
        fail(f"Unsupported static Array decomposition: {name}")
    translator.allowed(arguments, {"array"})
    matrix = require_matrix(_required(arguments, name))
    n = _square(matrix, name)
    _preflight(translator, name, n)

    source = _float_matrix(matrix)
    if name == "Array.matrixLUDecomposition":
        permutation, lower, upper = _lu(source, name)
        return {
            "L": wrap_array(_finite(lower, name)),
            "U": wrap_array(_finite(upper, name)),
            "P": wrap_array(permutation),
        }

    try:
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            if name == "Array.matrixQRDecomposition":
                q, r = np.linalg.qr(source, mode="complete")
                return {"Q": wrap_array(_finite(q, name)),
                        "R": wrap_array(_finite(r, name))}
            u, singular_values, vh = np.linalg.svd(source, full_matrices=True)
    except np.linalg.LinAlgError:
        fail(f"{name} failed to converge")

    return {
        "U": wrap_array(_finite(u, name)),
        "S": wrap_array(_finite(np.diag(singular_values), name)),
        "V": wrap_array(_finite(vh.T, name)),
    }
