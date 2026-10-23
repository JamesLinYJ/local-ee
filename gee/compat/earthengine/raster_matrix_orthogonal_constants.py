"""Bounded source-free reduced QR and SVD folds for raster matrices."""
from __future__ import annotations

import math

from .array_core import charge_array
from .ir import fail


def _finite_factor(value, dtype, name):
    import numpy as np

    if not np.isfinite(value).all():
        fail(f"{name} constant factors must be finite Float64 values")
    if dtype == "to_float":
        with np.errstate(over="ignore", invalid="ignore"):
            value = value.astype(np.float32).astype(np.float64)
        if not np.isfinite(value).all():
            fail(f"{name} constant factors overflow Float32")
    return tuple(float(item) for item in value.flat)


def fold_constant_orthogonal_factors(
        translator, name, op, rows, cols, values, dtype):
    """Fold finite reduced factors without binding the result to a grid."""
    from gee.matrix_values_spec import matrix_factor_layout

    if op not in {"qr", "svd"}:
        fail(f"{name} constant orthogonal operation is unsupported")
    if (type(values) is not tuple or len(values) != rows * cols
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   for value in values)):
        fail(f"{name} source-free input must be a finite matrix")
    try:
        layout = matrix_factor_layout(op, rows, cols)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        fail(f"{name} constant factor layout is invalid: {error}")
    output_count = sum(shape[0] * shape[1] for _factor, shape in layout)
    rank = min(rows, cols)
    # Pay for dense input, reduced factorization and owned result copies before
    # NumPy creates any matrix or factor arrays.
    charge_array(
        translator,
        24 * rows * cols * rank + 8 * rows * cols + 6 * output_count + 32,
    )
    if op == "svd":
        from .raster_matrix_orthogonal_rank import exact_constant_rank

        exact_rank = exact_constant_rank(translator, values, rows, cols)

    import numpy as np

    matrix = np.asarray(values, dtype=np.float64).reshape((rows, cols))
    try:
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            if op == "qr":
                q, r = np.linalg.qr(matrix, mode="reduced")
                factors = (q, r)
            else:
                u, singular_values, vh = np.linalg.svd(matrix, full_matrices=False)
                if (not np.isfinite(singular_values).all()
                        or any(value <= 0 for value in singular_values[:exact_rank])):
                    fail(f"{name} constant SVD could not retain a finite positive singular direction")
                singular_values[exact_rank:] = 0.0
                factors = (u, np.diag(singular_values), vh.T)
    except np.linalg.LinAlgError:
        fail(f"{name} constant decomposition failed to converge")

    if len(factors) != len(layout) or any(
            type(factor.shape) is not tuple or tuple(factor.shape) != shape
            for factor, (_factor_name, shape) in zip(factors, layout)):
        fail(f"{name} constant decomposition returned an invalid factor shape")
    return tuple(
        _finite_factor(factor, dtype, name)
        for factor in factors
    )
