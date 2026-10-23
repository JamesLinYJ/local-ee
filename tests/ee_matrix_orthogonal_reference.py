"""Source-free NumPy oracle for compact per-pixel QR and SVD factors.

The oracle specifies local compact shapes and checks finite inputs/results. It
does not require its LAPACK bases or QR signs to match another solver.
"""
from __future__ import annotations

from fractions import Fraction

import numpy as np


_MAX_AXIS = 8
_MAX_CELLS = 64


def _checked_matrix(op: str, matrix: np.ndarray) -> np.ndarray:
    if op not in {"qr", "svd"}:
        raise ValueError("orthogonal matrix reference supports qr and svd")
    try:
        source = np.asarray(matrix, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("matrix input must contain binary64 values") from error
    if source.ndim != 2 or not source.shape[0] or not source.shape[1]:
        raise ValueError("matrix input must be nonempty and rank two")
    rows, cols = source.shape
    if rows > _MAX_AXIS or cols > _MAX_AXIS:
        raise ValueError("matrix axes must be in1..8")
    p = min(rows, cols)
    output_cells = (
        rows * p + p * cols if op == "qr"
        else rows * p + p * p + cols * p
    )
    if rows * cols > _MAX_CELLS or output_cells > _MAX_CELLS:
        raise ValueError("matrix input and combined factors must fit64 cells")
    if not np.isfinite(source).all():
        raise ValueError("matrix input must contain only finite values")
    return source.copy()


def _exact_binary_rank(matrix: np.ndarray) -> int:
    """Find rank of the represented binary64 values without a tolerance."""
    work = [
        [Fraction.from_float(float(value)) for value in row]
        for row in matrix
    ]
    rows, columns = matrix.shape
    rank = 0
    for column in range(columns):
        pivot = next((row for row in range(rank, rows) if work[row][column]), None)
        if pivot is None:
            continue
        work[rank], work[pivot] = work[pivot], work[rank]
        pivot_value = work[rank][column]
        for row in range(rank + 1, rows):
            value = work[row][column]
            if not value:
                continue
            scale = value / pivot_value
            for remaining in range(column + 1, columns):
                work[row][remaining] -= scale * work[rank][remaining]
            work[row][column] = Fraction(0)
        rank += 1
        if rank == rows:
            break
    return rank


def orthogonal_matrix_result(
    op: str, matrix: np.ndarray,
) -> tuple[np.ndarray, ...] | None:
    """Return compact ``(Q, R)`` or ``(U, S, V)`` factors, or ``None``.

    QR uses reduced dimensions ``Q(m,p), R(p,n)``. SVD uses ``U(m,p),
    S(p,p), V(n,p)`` with ``A = U @ S @ V.T`` and ``p=min(m,n)``. Factors
    are returned separately so callers can concatenate their row-major cells
    in the v1 wire order. Rank-deficient, zero and repeated-singular-value
    matrices remain valid. The routine intentionally makes no claim that a
    different numerical library will choose the same signs or bases.
    """
    source = _checked_matrix(op, matrix)
    try:
        with np.errstate(all="ignore"):
            if op == "qr":
                q, r = np.linalg.qr(source, mode="reduced")
                factors = (q, r)
            else:
                u, singular_values, vh = np.linalg.svd(source, full_matrices=False)
                exact_rank = _exact_binary_rank(source)
                if exact_rank == len(singular_values) and np.any(singular_values == 0.0):
                    # A floating backend cannot provide an independent positive
                    # direction when its singular value has underflowed to zero.
                    return None
                # LAPACK may emit a roundoff-sized ghost for an exact null
                # direction. Preserve the binary-rational rank contract without
                # borrowing any native factorization code.
                singular_values[exact_rank:] = 0.0
                factors = (u, np.diag(singular_values), vh.T)
    except np.linalg.LinAlgError:
        return None
    if any(not np.isfinite(factor).all() for factor in factors):
        return None
    return tuple(np.asarray(factor, dtype=np.float64) for factor in factors)
