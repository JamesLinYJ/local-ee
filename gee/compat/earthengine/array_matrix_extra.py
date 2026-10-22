"""Bounded static matrix decomposition and scalar operations.

Eigenvectors follow NumPy/LAPACK's basis within repeated-eigenvalue spaces.
Eigenpairs are emitted in descending value order; each returned row vector is
sign-normalized so its first largest-magnitude component is positive. The
ordering and sign rule are local presentation choices; the degenerate basis is
solver-dependent and neither policy claims GEE or EJML parity.
"""
from __future__ import annotations

import math

import numpy as np

from .array_core import (
    MAX_ARRAY_CELLS,
    charge_array,
    finite_float_sum,
    require_matrix,
    wrap_array,
)
from .ir import fail


ARRAY_MATRIX_FUNCTIONS = frozenset({
    "Array.eigen",
    "Array.matrixCholeskyDecomposition",
    "Array.matrixDeterminant",
    "Array.matrixTrace",
    "Array.matrixDiagonal",
    "Array.matrixToDiag",
    "Array.matrixFnorm",
})


def _square(matrix, operation):
    if matrix.shape[0] != matrix.shape[1]:
        fail(f"{operation} requires a square matrix")
    return matrix.shape[0]


def _required(arguments, name, parameter):
    if parameter not in arguments:
        fail(f"{name} requires the {parameter} argument")
    return arguments[parameter]


def _finite_number(value, operation):
    result = float(value)
    if not math.isfinite(result):
        fail(f"{operation} must produce a finite real number")
    return result


def _float_matrix(matrix):
    # Call only after the caller has checked shapes and charged work.
    return np.asarray(matrix, dtype=np.float64)


def _work_cubic(n, factor=4):
    # A conservative upper estimate for a dense factorization/eigensolve,
    # including result materialization. Python integers avoid estimate overflow.
    return factor * n * n * n + 2 * n * n + n


def invoke_matrix_extra(translator, name, arguments):
    """Evaluate the listed pinned static matrix algorithms only."""
    if name not in ARRAY_MATRIX_FUNCTIONS:
        fail(f"Unsupported static Array matrix operation: {name}")

    if name == "Array.matrixCholeskyDecomposition":
        translator.allowed(arguments, {"array"})
        matrix = require_matrix(
            _required(arguments, name, "array"),
        )
        n = _square(matrix, "Array.matrixCholeskyDecomposition")
        if not np.array_equal(matrix, matrix.T):
            fail("Array.matrixCholeskyDecomposition requires an exactly symmetric matrix")
        charge_array(translator, _work_cubic(n, factor=2))
        try:
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                lower = np.linalg.cholesky(_float_matrix(matrix))
        except np.linalg.LinAlgError:
            fail("Array.matrixCholeskyDecomposition requires a positive-definite matrix")
        return {"L": wrap_array(lower)}

    translator.allowed(arguments, {"input"})
    matrix = require_matrix(_required(arguments, name, "input"))

    if name == "Array.eigen":
        n = _square(matrix, "Array.eigen")
        if n * (n + 1) > MAX_ARRAY_CELLS:
            fail("Array.eigen result exceeds 10000 cells")
        if not np.array_equal(matrix, matrix.T):
            fail("Array.eigen currently requires an exactly symmetric matrix")
        charge_array(translator, _work_cubic(n))
        try:
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                values, vectors = np.linalg.eigh(_float_matrix(matrix))
        except np.linalg.LinAlgError:
            fail("Array.eigen failed to converge")
        # eigh returns ascending eigenvalues and column eigenvectors. Stable
        # descending order preserves the solver order for exact ties.
        order = np.argsort(-values, kind="stable")
        result = np.empty((n, n + 1), dtype=np.float64)
        for row, index in enumerate(order):
            vector = vectors[:, index].copy()
            pivot = int(np.argmax(np.abs(vector)))  # first index breaks ties
            if vector[pivot] < 0:
                vector *= -1.0
            result[row, 0] = values[index]
            result[row, 1:] = vector
        return wrap_array(result)

    if name == "Array.matrixDeterminant":
        n = _square(matrix, "Array.matrixDeterminant")
        charge_array(translator, _work_cubic(n, factor=2))
        try:
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                determinant = np.linalg.det(_float_matrix(matrix))
        except np.linalg.LinAlgError:
            fail("Array.matrixDeterminant failed to converge")
        return _finite_number(determinant, "Array.matrixDeterminant")

    if name == "Array.matrixTrace":
        diagonal_length = min(matrix.shape)
        charge_array(translator, matrix.size + diagonal_length)
        return finite_float_sum(matrix[index, index] for index in range(diagonal_length))

    if name == "Array.matrixDiagonal":
        diagonal_length = min(matrix.shape)
        output_cells = diagonal_length
        if output_cells > MAX_ARRAY_CELLS:
            fail("Array.matrixDiagonal result exceeds 10000 cells")
        charge_array(translator, matrix.size + output_cells)
        # Earth Engine represents this result as a single column.
        return wrap_array(np.diag(matrix).reshape((diagonal_length, 1)))

    if name == "Array.matrixToDiag":
        if matrix.shape[1] != 1:
            fail("Array.matrixToDiag requires a single-column matrix")
        n = matrix.shape[0]
        if n * n > MAX_ARRAY_CELLS:
            fail("Array.matrixToDiag result exceeds 10000 cells")
        charge_array(translator, matrix.size + n * n)
        return wrap_array(np.diag(matrix[:, 0]))

    # The Frobenius norm is defined as sqrt(sum(x*x)); hypot evaluates the
    # same real norm with scaling so finite values near 1e308 do not overflow
    # merely from squaring an intermediate.
    charge_array(translator, matrix.size)
    try:
        norm = math.hypot(*(float(value) for value in matrix.flat))
    except OverflowError:
        fail("Array.matrixFnorm must produce a finite real number")
    return _finite_number(norm, "Array.matrixFnorm")
