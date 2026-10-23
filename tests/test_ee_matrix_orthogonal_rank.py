"""Exact rank guards SVD null directions without a floating tolerance."""
import numpy as np
import pytest

from ee_matrix_orthogonal_reference import _exact_binary_rank
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.raster_matrix_orthogonal_constants import fold_constant_orthogonal_factors
from gee.compat.earthengine.raster_matrix_orthogonal_rank import exact_constant_rank


@pytest.mark.parametrize("matrix,rank", [
    ([[0, 0, 0], [0, 0, 0]], 0),
    ([[0, 0, 1], [0, 2, 0]], 2),
    ([[1, 2], [2, 4], [3, 6]], 1),
    ([[1, 2, 3], [2, 4, 6]], 1),
    ([[1, 0], [0, 1e-20]], 2),
    ([[1, 1], [1, 1 + 2**-52]], 2),
    ([[0, 0, 0], [0, 0, 0], [0, 2, 0]], 1),
    ([[1, -2, 3], [2, 3, -1], [4, -1, 6]], 3),
])
def test_fraction_free_rank_matches_independent_fraction_elimination(matrix, rank):
    source = np.asarray(matrix, dtype=np.float64)
    assert _exact_binary_rank(source) == rank
    translator = Translator([], {}, {})
    assert exact_constant_rank(translator, tuple(source.flat), *source.shape) == rank
    assert 0 < translator.steps < 50_000


def test_random_small_dyadic_matrices_match_independent_fraction_rank():
    rng = np.random.default_rng(55)
    for rows, cols in [(4, 4), (8, 4), (4, 8), (3, 2), (1, 8)]:
        for _ in range(8):
            matrix = rng.integers(-4, 5, size=(rows, cols)).astype(float) / 16
            translator = Translator([], {}, {})
            assert exact_constant_rank(translator, tuple(matrix.flat), rows, cols) == _exact_binary_rank(matrix)


def test_uniform_subnormal_scale_does_not_artificially_enlarge_integer_width():
    tiny = float.fromhex("0x0.0000000000001p-1022")
    matrix = np.array([[tiny, 2 * tiny], [3 * tiny, 4 * tiny]])
    translator = Translator([], {}, {})
    assert exact_constant_rank(translator, tuple(matrix.flat), 2, 2) == 2
    assert translator.steps < 100


def test_rank_work_is_precharged_and_extreme_span_rejects_before_numpy(monkeypatch):
    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        exact_constant_rank(translator, (1.0, 0.0, 0.0, 1.0), 2, 2)
    assert translator.steps == 49_999

    def unexpected(*_args, **_kwargs):
        raise AssertionError("NumPy allocated before exact-rank work admission")

    monkeypatch.setattr(np, "asarray", unexpected)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        fold_constant_orthogonal_factors(
            Translator([], {}, {}), "SVD", "svd", 3, 3,
            (1e308, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1e-308), "to_double",
        )


def test_source_free_true_null_direction_is_exact_zero_not_lapack_noise(monkeypatch):
    matrix = np.array([[1.0, 2.0], [2.0, 4.0], [3.0, 6.0]])
    u, singular, vh = np.linalg.svd(matrix, full_matrices=False)
    singular[1] = 1e-16
    monkeypatch.setattr(np.linalg, "svd", lambda *a, **k: (u, singular.copy(), vh))
    factors = fold_constant_orthogonal_factors(
        Translator([], {}, {}), "SVD", "svd", 3, 2,
        tuple(float(value) for value in matrix.flat), "to_double",
    )
    u, s, v = (np.asarray(value).reshape(shape)
               for value, shape in zip(factors, [(3, 2), (2, 2), (2, 2)]))
    assert s[1, 1] == 0.0
    np.testing.assert_allclose(u @ s @ v.T, matrix, rtol=0, atol=3e-14)


def test_source_free_lost_positive_direction_is_rejected_instead_of_fabricated(monkeypatch):
    monkeypatch.setattr(np.linalg, "svd", lambda *a, **k: (np.eye(2), np.array([1.0, 0.0]), np.eye(2)))
    with pytest.raises(UnsupportedEEError, match="positive singular direction"):
        fold_constant_orthogonal_factors(
            Translator([], {}, {}), "SVD", "svd", 2, 2,
            (1.0, 0.0, 0.0, 1.0), "to_double",
        )
