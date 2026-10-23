"""Reduced QR/SVD constant folds, reconstruction and bounded rejection."""
from __future__ import annotations

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import UnsupportedEEError, const
from gee.compat.earthengine.raster_array_bands import RasterArrayBands
from gee.compat.earthengine.raster_matrix_decomposition import (
    invoke_raster_matrix_decomposition,
)
from gee.compat.earthengine.raster_matrix_orthogonal_constants import (
    fold_constant_orthogonal_factors,
)
from ee_matrix_factor_compiler_helpers import array, cell_values


def _factorize(op, matrix, *, cast="to_double", mask=None):
    name = ("Image.matrixQRDecomposition" if op == "qr"
            else "Image.matrixSingularValueDecomposition")
    return invoke_raster_matrix_decomposition(
        Translator([], {}, {}), name,
        {"image": array(matrix, cast=cast, mask=mask)},
    )


def _values(bundle):
    assert isinstance(bundle, RasterArrayBands)
    return {factor.name: cell_values(factor) for factor in bundle.arrays}


@pytest.mark.parametrize("matrix", [
    np.array([[1.0, 2.0, -1.0], [2.0, 0.0, 3.0], [4.0, -2.0, 1.0]]),
    np.array([[1.0, 2.0, 3.0], [2.0, 4.0, 6.0]]),
    np.zeros((2, 3)),
])
def test_source_free_reduced_qr_and_svd_reconstruct_and_are_orthogonal(matrix):
    qr = _values(_factorize("qr", matrix))
    q, r = qr["Q"], qr["R"]
    np.testing.assert_allclose(q.T @ q, np.eye(min(matrix.shape)), atol=2e-12)
    np.testing.assert_allclose(q @ r, matrix, atol=2e-12)

    svd = _values(_factorize("svd", matrix))
    u, singular, v = svd["U"], svd["S"], svd["V"]
    np.testing.assert_allclose(u.T @ u, np.eye(min(matrix.shape)), atol=2e-12)
    np.testing.assert_allclose(v.T @ v, np.eye(min(matrix.shape)), atol=2e-12)
    np.testing.assert_allclose(u @ singular @ v.T, matrix, atol=2e-12)
    assert all(np.isfinite(value).all() for value in (*qr.values(), *svd.values()))


def test_source_free_factors_keep_metadata_without_inventing_a_grid():
    matrix = np.array([[1.0, 2.0], [3.0, 5.0], [8.0, 13.0]])
    bundle = _factorize("svd", matrix)
    assert bundle.image.source is None
    assert bundle.image.props == {"matrix_tag": "kept"}
    assert [factor.shape for factor in bundle.arrays] == [(3, 2), (2, 2), (2, 2)]
    assert all(factor.image is bundle.image for factor in bundle.arrays)


def test_float32_inputs_and_final_factors_are_checked_at_their_boundaries():
    matrix = np.array([[2.0, -1.0, 4.0], [3.0, 5.0, 2.0]], dtype=np.float64)
    rounded = matrix.astype(np.float32).astype(np.float64)
    for op in ("qr", "svd"):
        factors = _values(_factorize(op, matrix, cast="to_float"))
        assert all(np.isfinite(value).all() for value in factors.values())
        if op == "qr":
            np.testing.assert_allclose(factors["Q"] @ factors["R"], rounded, atol=1e-6)
        else:
            np.testing.assert_allclose(
                factors["U"] @ factors["S"] @ factors["V"].T,
                rounded, atol=1e-6,
            )

    maximum = float(np.finfo(np.float32).max)
    with pytest.raises(UnsupportedEEError, match="overflow Float32"):
        _factorize("svd", np.full((2, 2), maximum), cast="to_float")


def test_source_free_mask_and_work_budget_fail_before_numpy_allocation(monkeypatch):
    matrix = (1.0, 2.0, 3.0, 4.0)
    translator = Translator([], {}, {})
    translator.steps = 49_999

    def unexpected(*_args, **_kwargs):
        raise AssertionError("NumPy allocation occurred before work precharge")

    monkeypatch.setattr(np, "asarray", unexpected)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        fold_constant_orthogonal_factors(
            translator, "Image.matrixQRDecomposition", "qr", 2, 2,
            matrix, "to_double",
        )

    with pytest.raises(UnsupportedEEError, match="masked source-free"):
        invoke_raster_matrix_decomposition(
            Translator([], {}, {}), "Image.matrixQRDecomposition",
            {"image": array(np.eye(2), mask=const(False))},
        )
