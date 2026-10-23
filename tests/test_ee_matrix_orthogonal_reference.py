"""Shape and independent numerical invariants of the compact QR/SVD oracle."""
import numpy as np
import pytest

from ee_matrix_orthogonal_reference import orthogonal_matrix_result


@pytest.mark.parametrize("matrix", [
    np.asarray([[1.0, 2.0], [3.0, 4.0], [5.0, 7.0]]),
    np.asarray([[1.0, 0.0, 2.0], [0.0, 1.0, 3.0]]),
    np.asarray([[1.0, 2.0], [2.0, 4.0], [3.0, 6.0]]),
    np.zeros((3, 2)),
    np.asarray([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]),
])
def test_reference_factors_reconstruct_and_have_orthogonal_columns(matrix):
    rows, cols = matrix.shape
    p = min(rows, cols)

    q, r = orthogonal_matrix_result("qr", matrix)
    assert q.shape == (rows, p)
    assert r.shape == (p, cols)
    np.testing.assert_allclose(q @ r, matrix, rtol=2e-14, atol=2e-14)
    np.testing.assert_allclose(q.T @ q, np.eye(p), rtol=0, atol=2e-14)
    np.testing.assert_allclose(np.tril(r, -1), 0, rtol=0, atol=2e-14)

    u, singular, v = orthogonal_matrix_result("svd", matrix)
    assert u.shape == (rows, p)
    assert singular.shape == (p, p)
    assert v.shape == (cols, p)
    np.testing.assert_allclose(u @ singular @ v.T, matrix, rtol=2e-14, atol=2e-14)
    np.testing.assert_allclose(u.T @ u, np.eye(p), rtol=0, atol=2e-14)
    np.testing.assert_allclose(v.T @ v, np.eye(p), rtol=0, atol=2e-14)
    np.testing.assert_allclose(singular, np.diag(np.diag(singular)), atol=0)
    assert np.all(np.diag(singular) >= 0)
    assert np.all(np.diff(np.diag(singular)) <= 0)


def test_repeated_and_zero_singular_values_are_valid_without_basis_comparison():
    repeated = np.asarray([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])
    u, s, v = orthogonal_matrix_result("svd", repeated)
    np.testing.assert_allclose(np.diag(s), [1.0, 1.0], atol=0)
    np.testing.assert_allclose(u @ s @ v.T, repeated, atol=0)

    zero = np.zeros((2, 3))
    u, s, v = orthogonal_matrix_result("svd", zero)
    np.testing.assert_array_equal(s, np.zeros((2, 2)))
    np.testing.assert_allclose(u.T @ u, np.eye(2), atol=0)
    np.testing.assert_allclose(v.T @ v, np.eye(2), atol=0)


def test_reference_canonicalizes_exact_binary_null_directions_without_tolerance():
    rank_one = np.asarray([[1.0, 2.0], [2.0, 4.0], [3.0, 6.0]])
    u, singular, v = orthogonal_matrix_result("svd", rank_one)
    np.testing.assert_array_equal(np.diag(singular)[1:], [0.0])
    np.testing.assert_allclose(u @ singular @ v.T, rank_one, rtol=0, atol=2e-14)

    near_singular_but_full_rank = np.diag([1.0, 1e-20])
    _u, singular, _v = orthogonal_matrix_result("svd", near_singular_but_full_rank)
    assert singular[1, 1] > 0.0


def test_reference_reports_when_numpy_loses_a_mathematically_positive_direction():
    # Exact binary64 determinant is nonzero, but this NumPy/LAPACK backend
    # returns a zero small singular value for the extreme dynamic range.
    matrix = np.asarray([[1e308, 1e-308], [0.0, 1e-308]])
    assert orthogonal_matrix_result("svd", matrix) is None


@pytest.mark.parametrize("op,matrix", [
    ("qr", np.eye(8)),  # combined compact factors exceed64 cells
    ("svd", np.eye(8)),
    ("svd", np.ones((5, 8))),  # input40 cells, compact output90 cells
    ("qr", np.ones((9, 1))),
])
def test_reference_rejects_shapes_over_axis_or_combined_output_limits(op, matrix):
    with pytest.raises(ValueError, match="axes|64 cells"):
        orthogonal_matrix_result(op, matrix)


@pytest.mark.parametrize("op,matrix", [
    ("qr", np.empty((0, 1))), ("svd", np.empty((2, 0))),
    ("qr", np.ones((2, 2, 1))), ("other", np.eye(2)),
])
def test_reference_rejects_invalid_operation_or_empty_nonmatrix_shape(op, matrix):
    with pytest.raises(ValueError):
        orthogonal_matrix_result(op, matrix)


@pytest.mark.parametrize("op", ["qr", "svd"])
def test_reference_does_not_turn_nonfinite_source_values_into_factors(op):
    with pytest.raises(ValueError, match="finite"):
        orthogonal_matrix_result(op, [[1.0, np.nan], [0.0, 1.0]])
