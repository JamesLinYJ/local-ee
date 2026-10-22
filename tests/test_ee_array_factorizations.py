"""Pinned SDK static QR, pivoted LU and SVD with independent identities."""
from math import sqrt
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def output(ee, value):
    return compile_expression(encode(ee, value), [], {})["value"]


def invocations(expression):
    """Return SDK scope invocations without rebuilding the expression."""
    if expression.get("type") != "CompoundValue":
        return []
    return [node for _, node in expression["scope"]
            if isinstance(node, dict) and node.get("type") == "Invocation"]


def assert_orthogonal(matrix, tolerance=3e-14):
    matrix = np.asarray(matrix, dtype=float)
    np.testing.assert_allclose(matrix.T @ matrix, np.eye(matrix.shape[0]),
                               atol=tolerance, rtol=tolerance)


def test_pinned_sdk_serializes_required_array_argument_and_compiles_typed_factor_maps(ee):
    matrix = ee.Array([[12, -51, 4], [6, 167, -68], [-4, 24, -41]])
    methods = [
        ("matrixQRDecomposition", "Array.matrixQRDecomposition", {"Q", "R"}),
        ("matrixLUDecomposition", "Array.matrixLUDecomposition", {"L", "U", "P"}),
        ("matrixSingularValueDecomposition", "Array.matrixSingularValueDecomposition",
         {"U", "S", "V"}),
    ]
    for method, algorithm, keys in methods:
        value = getattr(matrix, method)()
        expression = encode(ee, value)
        calls = [call for call in invocations(expression)
                 if call.get("functionName") == algorithm]
        assert len(calls) == 1
        assert set(calls[0]["arguments"]) == {"array"}
        result = compile_expression(expression, [], {})["value"]
        assert set(result) == keys
        for factor in result.values():
            assert np.asarray(factor).shape == (3, 3)
            assert np.isfinite(factor).all()


def test_qr_matches_hand_diagonal_and_reconstructs_the_classic_three_by_three(ee):
    source = np.array([
        [12.0, -51.0, 4.0],
        [6.0, 167.0, -68.0],
        [-4.0, 24.0, -41.0],
    ])
    factors = output(ee, ee.Array(source.tolist()).matrixQRDecomposition())
    q, r = np.asarray(factors["Q"]), np.asarray(factors["R"])

    # Hand-computed column norms are 14, 175 and 35; solver signs may vary.
    np.testing.assert_allclose(np.abs(np.diag(r)), [14, 175, 35], atol=2e-13)
    np.testing.assert_allclose(np.tril(r, -1), 0, atol=2e-13)
    assert_orthogonal(q)
    np.testing.assert_allclose(q @ r, source, atol=3e-13, rtol=3e-15)


def test_svd_matches_two_by_two_closed_form_and_reconstructs(ee):
    source = np.array([[4.0, 0.0], [3.0, -5.0]])
    factors = output(ee, ee.Array(source.tolist()).matrixSingularValueDecomposition())
    u, singular, v = (np.asarray(factors[key]) for key in ("U", "S", "V"))

    # The eigenvalues of AᵀA are 40 and 10, so these singular values are exact.
    expected = np.array([2 * sqrt(10), sqrt(10)])
    np.testing.assert_allclose(np.diag(singular), expected, atol=2e-14, rtol=2e-15)
    np.testing.assert_allclose(singular, np.diag(np.diag(singular)), atol=2e-14)
    assert np.all(np.diag(singular) >= 0)
    assert np.all(np.diff(np.diag(singular)) <= 0)
    assert_orthogonal(u)
    assert_orthogonal(v)
    np.testing.assert_allclose(u @ singular @ v.T, source, atol=2e-14, rtol=2e-15)


@pytest.mark.parametrize("source", [
    [[1.0, 2.0], [2.0, 4.0]],  # rank one
    [[0.0, 0.0], [0.0, 0.0]],  # zero matrix
    [[0.0, -2.0], [2.0, 0.0]],  # repeated singular values
])
def test_qr_and_svd_reconstruct_degenerate_and_repeated_singular_value_inputs(ee, source):
    source = np.asarray(source, dtype=float)
    qr = output(ee, ee.Array(source.tolist()).matrixQRDecomposition())
    q, r = np.asarray(qr["Q"]), np.asarray(qr["R"])
    assert_orthogonal(q)
    np.testing.assert_allclose(np.tril(r, -1), 0, atol=2e-14)
    np.testing.assert_allclose(q @ r, source, atol=2e-14)

    svd = output(ee, ee.Array(source.tolist()).matrixSingularValueDecomposition())
    u, s, v = (np.asarray(svd[key]) for key in ("U", "S", "V"))
    sigma = np.diag(s)
    assert np.all(sigma >= 0)
    assert np.all(np.diff(sigma) <= 0)
    np.testing.assert_allclose(s, np.diag(sigma), atol=2e-14)
    assert_orthogonal(u)
    assert_orthogonal(v)
    np.testing.assert_allclose(u @ s @ v.T, source, atol=3e-14)


def test_lu_uses_two_partial_pivots_swaps_prior_lower_columns_and_reconstructs(ee):
    source = np.array([[0.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 10.0]])
    result = output(ee, ee.Array(source.tolist()).matrixLUDecomposition())
    lower, upper, permutation = (np.asarray(result[key]) for key in ("L", "U", "P"))

    # Pivot rows 2, then 0, then 1; the second pivot swaps an already-built
    # lower-triangular column, which catches implementations that omit it.
    np.testing.assert_array_equal(permutation, [[0, 0, 1], [1, 0, 0], [0, 1, 0]])
    np.testing.assert_allclose(lower, [[1, 0, 0], [0, 1, 0], [4 / 7, 3 / 14, 1]],
                               atol=2e-15)
    np.testing.assert_allclose(upper, [[7, 8, 10], [0, 2, 3], [0, 0, -5 / 14]],
                               atol=2e-15)
    np.testing.assert_allclose(permutation @ source, lower @ upper, atol=2e-15)


def test_lu_keeps_the_first_row_when_partial_pivot_magnitudes_tie(ee):
    source = np.array([[1.0, 2.0], [-1.0, 3.0]])
    result = output(ee, ee.Array(source.tolist()).matrixLUDecomposition())
    lower, upper, permutation = (np.asarray(result[key]) for key in ("L", "U", "P"))
    np.testing.assert_array_equal(permutation, np.eye(2))
    np.testing.assert_allclose(lower, [[1, 0], [-1, 1]], atol=1e-15)
    np.testing.assert_allclose(upper, [[1, 2], [0, 5]], atol=1e-15)
    np.testing.assert_allclose(permutation @ source, lower @ upper, atol=1e-15)


def test_typed_dictionary_get_and_if_factors_remain_composable_arrays(ee):
    source = [[4, 0], [3, -5]]
    matrix = ee.Array(source)
    decomposition = ee.Dictionary(matrix.matrixQRDecomposition())
    q = ee.Array(decomposition.get("Q"))
    r = ee.Array(decomposition.get("R"))
    direct = q.matrixMultiply(r)
    selected_q = ee.Array(ee.Algorithms.If(True, decomposition.get("Q"),
                                            decomposition.get("Q")))
    conditional = selected_q.matrixMultiply(r)

    direct_expression = encode(ee, direct)
    conditional_expression = encode(ee, conditional)
    assert {call["functionName"] for call in invocations(direct_expression)} >= {
        "Array.matrixQRDecomposition", "Dictionary.get", "Array.matrixMultiply"
    }
    assert {call["functionName"] for call in invocations(conditional_expression)} >= {
        "Array.matrixQRDecomposition", "Dictionary.get", "If", "Array.matrixMultiply"
    }
    np.testing.assert_allclose(output(ee, direct), source, atol=1e-14)
    np.testing.assert_allclose(output(ee, conditional), source, atol=1e-14)
