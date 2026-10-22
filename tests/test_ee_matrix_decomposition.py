"""Pinned Python Array matrix API and independent static numeric controls."""
from math import sqrt
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.compat.earthengine.array_core import StaticArray
from gee.compat.earthengine.array_matrix_extra import invoke_matrix_extra
from gee.compat.earthengine.array_values import invoke_array
from gee.compat.earthengine.decoder import Translator


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def output(ee, value):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, [], {})["value"]


def raw(name, **arguments):
    return invoke_matrix_extra(Translator([], {}, {}), name, arguments)


def static(values):
    return invoke_array(Translator([], {}, {}), "Array", {"values": values})


def test_pinned_python_matrix_methods_serialize_actual_algorithm_names_and_arguments(ee):
    matrix = ee.Array([[4, 1], [1, 3]])
    cases = [
        ("Array.eigen", matrix.eigen(), "input"),
        ("Array.matrixCholeskyDecomposition", matrix.matrixCholeskyDecomposition(), "array"),
        ("Array.matrixDeterminant", matrix.matrixDeterminant(), "input"),
        ("Array.matrixTrace", matrix.matrixTrace(), "input"),
        ("Array.matrixDiagonal", matrix.matrixDiagonal(), "input"),
        ("Array.matrixToDiag", ee.Array([[1], [2]]).matrixToDiag(), "input"),
        ("Array.matrixFnorm", matrix.matrixFnorm(), "input"),
    ]
    for algorithm, value, argument in cases:
        encoded = ee.serializer.encode(value, for_cloud_api=False)
        invocations = [
            node for _, node in encoded["scope"]
            if isinstance(node, dict) and node.get("type") == "Invocation"
            and node.get("functionName") == algorithm
        ]
        assert len(invocations) == 1
        assert set(invocations[0]["arguments"]) == {argument}


def test_eigen_has_descending_values_row_vectors_and_independent_reconstruction(ee):
    matrix = [[4.0, 1.0], [1.0, 3.0]]
    result = output(ee, ee.Array(matrix).eigen())
    root5 = sqrt(5.0)
    lambda_hi, lambda_lo = (7 + root5) / 2, (7 - root5) / 2
    vector_hi = [sqrt((5 + root5) / 10), sqrt((5 - root5) / 10)]
    vector_lo = [-vector_hi[1], vector_hi[0]]
    expected = [
        [lambda_hi, *vector_hi],
        [lambda_lo, *vector_lo],
    ]
    np.testing.assert_allclose(result, expected, atol=2e-15)

    vectors = [row[1:] for row in result]
    assert result[0][0] > result[1][0]
    for row in vectors:
        pivot = max(range(len(row)), key=lambda index: abs(row[index]))
        assert row[pivot] > 0
    for left in range(2):
        for right in range(2):
            dot = sum(vectors[left][i] * vectors[right][i] for i in range(2))
            assert abs(dot - int(left == right)) < 2e-15
    for row in range(2):
        for column in range(2):
            reconstructed = sum(
                result[index][0] * vectors[index][row] * vectors[index][column]
                for index in range(2)
            )
            assert abs(reconstructed - matrix[row][column]) < 2e-15


def test_repeated_eigenvalues_keep_a_solver_basis_with_orthonormal_rows(ee):
    matrix = [[2, 0, 0], [0, 2, 0], [0, 0, 3]]
    result = output(ee, ee.Array(matrix).eigen())
    assert [row[0] for row in result] == [3, 2, 2]
    vectors = [row[1:] for row in result]
    for left in range(3):
        pivot = max(range(3), key=lambda index: abs(vectors[left][index]))
        assert vectors[left][pivot] > 0
        for right in range(3):
            dot = sum(vectors[left][i] * vectors[right][i] for i in range(3))
            assert abs(dot - int(left == right)) < 1e-14
    for row in range(3):
        for column in range(3):
            reconstructed = sum(
                result[index][0] * vectors[index][row] * vectors[index][column]
                for index in range(3)
            )
            assert abs(reconstructed - matrix[row][column]) < 1e-14


def test_cholesky_factor_uses_documented_lower_factor_and_reconstructs(ee):
    matrix = [
        [4, 12, -16],
        [12, 37, -43],
        [-16, -43, 98],
    ]
    expected_lower = [[2, 0, 0], [6, 1, 0], [-8, 5, 3]]
    result = output(ee, ee.Array(matrix).matrixCholeskyDecomposition())
    assert set(result) == {"L"}
    assert result["L"] == expected_lower
    for row in range(3):
        for column in range(3):
            reconstructed = sum(
                expected_lower[row][k] * expected_lower[column][k]
                for k in range(3)
            )
            assert reconstructed == matrix[row][column]


def test_determinant_trace_diagonal_to_diagonal_and_frobenius_norm(ee):
    matrix = ee.Array([[4, 7], [2, 6]])
    assert output(ee, matrix.matrixDeterminant()) == pytest.approx(10.0)
    assert output(ee, ee.Array([[1, 2], [3, 4]]).matrixDeterminant()) == pytest.approx(-2.0)
    assert output(ee, matrix.matrixTrace()) == pytest.approx(10.0)
    assert output(ee, matrix.matrixDiagonal()) == [[4], [6]]
    assert output(ee, ee.Array([[3], [4]]).matrixToDiag()) == [[3, 0], [0, 4]]
    assert output(ee, matrix.matrixFnorm()) == pytest.approx(sqrt(105.0))


def test_rectangular_trace_and_diagonal_and_scaled_large_frobenius_norm(ee):
    matrix = ee.Array([[1, 2, 3], [4, 5, 6]])
    assert output(ee, matrix.matrixTrace()) == 6
    assert output(ee, matrix.matrixDiagonal()) == [[1], [5]]
    huge = output(ee, ee.Array([[1e308, 1e308]]).matrixFnorm())
    assert huge == pytest.approx(sqrt(2) * 1e308, rel=2e-16)
    assert np.isfinite(huge)
    cancellation = [[1e308, 0, 0], [0, 1e308, 0], [0, 0, -1e308]]
    assert output(ee, ee.Array(cancellation).matrixTrace()) == 1e308
    with pytest.raises(UnsupportedEEError, match="finite"):
        output(ee, ee.Array([[1e308, 0], [0, 1e308]]).matrixTrace())


@pytest.mark.parametrize("operation", [
    lambda ee: ee.Array([[1, 2], [3, 4]]).eigen(),
    lambda ee: ee.Array([[1, 2], [2, 1]]).matrixCholeskyDecomposition(),
    lambda ee: ee.Array([[1, 2, 3], [4, 5, 6]]).matrixDeterminant(),
    lambda ee: ee.Array([[1, 2]]).matrixToDiag(),
])
def test_asymmetric_indefinite_and_invalid_shapes_are_rejected(ee, operation):
    with pytest.raises(UnsupportedEEError):
        output(ee, operation(ee))


def test_unknown_arguments_nonsquare_shapes_and_nonfinite_results_reject():
    matrix = StaticArray(np.array([[1.0, 0.0], [0.0, 1.0]]))
    with pytest.raises(UnsupportedEEError, match="Unsupported static Array"):
        raw("Array.fake", input=matrix)
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        raw("Array.matrixTrace", input=matrix, ignored=True)
    with pytest.raises(UnsupportedEEError, match="requires the input argument"):
        raw("Array.matrixTrace")
    with pytest.raises(UnsupportedEEError, match="requires the array argument"):
        raw("Array.matrixCholeskyDecomposition")
    with pytest.raises(UnsupportedEEError, match="square matrix"):
        raw("Array.eigen", input=StaticArray(np.array([[1.0, 2.0]])))
    with pytest.raises(UnsupportedEEError, match="finite"):
        raw("Array.matrixDeterminant", input=StaticArray(np.diag([1e308, 1e308])))


def test_empty_and_nonfinite_array_values_fail_at_the_shared_array_boundary():
    for values in ([], [[float("inf")]], [[float("nan")]]):
        with pytest.raises(UnsupportedEEError):
            invoke_array(Translator([], {}, {}), "Array", {"values": values})


def test_decomposition_and_output_budgets_are_preflighted():
    column = static([[float(index)] for index in range(101)])
    with pytest.raises(UnsupportedEEError, match="result exceeds 10000 cells"):
        raw("Array.matrixToDiag", input=column)

    too_large_eigen = static(np.eye(100).tolist())
    with pytest.raises(UnsupportedEEError, match="result exceeds 10000 cells"):
        raw("Array.eigen", input=too_large_eigen)

    matrix = static([[1, 0], [0, 1]])
    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_matrix_extra(
            translator, "Array.matrixFnorm", {"input": matrix},
        )

    too_costly = static(np.eye(24).tolist())
    with pytest.raises(UnsupportedEEError, match="work budget"):
        raw("Array.eigen", input=too_costly)
