"""Pinned Python serialization and independent static-array numeric controls."""
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.compat.earthengine.array_values import StaticArray, invoke_array
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
    return invoke_array(Translator([], {}, {}), name, arguments)


def test_matrix_multiply_uses_exact_serialized_operands(ee):
    left = ee.Array([[1, 2], [3, 4]])
    right = ee.Array([[5, 6, 7], [8, 9, 10]])
    assert output(ee, left.matrixMultiply(right)) == [[21, 24, 27], [47, 54, 61]]
    assert output(ee, left.matrixMultiply([[1], [1]])) == [[3], [7]]


def test_integer_matrix_product_cannot_wrap_or_silently_round(ee):
    assert output(ee, ee.Array([[2**52, 1]]).matrixMultiply([[1], [1]])) == [[2**52 + 1]]
    with pytest.raises(UnsupportedEEError, match="exact Float64 domain"):
        output(ee, ee.Array([[2**53, 1]]).matrixMultiply([[1], [1]]))
    with pytest.raises(UnsupportedEEError, match="exact Float64 domain"):
        output(ee, ee.Array([[2**53]]).matrixMultiply([[2**53]]))


def test_static_array_is_not_implicitly_used_as_a_scalar_condition(ee):
    with pytest.raises(UnsupportedEEError, match="static"):
        output(ee, ee.Algorithms.If(ee.Array([0]), 1, 2))


def test_length_get_reshape_and_transpose_are_composable(ee):
    array = ee.Array([[10, 20, 30], [40, 50, 60]])
    assert output(ee, array.length().toList()) == [2, 3]
    assert output(ee, array.get([1, 2])) == 60
    assert output(ee, array.reshape([-1]).toList()) == [10, 20, 30, 40, 50, 60]
    assert output(ee, array.reshape([3, -1])) == [[10, 20], [30, 40], [50, 60]]
    assert output(ee, array.transpose()) == [[10, 40], [20, 50], [30, 60]]
    assert output(ee, array.matrixTranspose()) == [[10, 40], [20, 50], [30, 60]]
    cube = ee.Array([[[1, 2], [3, 4]], [[5, 6], [7, 8]]])
    assert output(ee, cube.transpose(0, 2)) == [[[1, 5], [3, 7]], [[2, 6], [4, 8]]]


def test_scalar_array_and_nested_dictionary_materialization(ee):
    assert output(ee, ee.Array(7).get([])) == 7
    assert output(ee, ee.Array(7).length()) == []
    assert output(ee, ee.Dictionary({"matrix": ee.Array([[2, 3]])})) == {"matrix": [[2, 3]]}
    assert output(ee, ee.List([ee.Array([3, 4])])) == [[3, 4]]


def test_inverse_matches_hand_calculated_solution_and_identity(ee):
    values = [[4, 7], [2, 6]]
    inverse = output(ee, ee.Array(values).matrixInverse())
    np.testing.assert_allclose(inverse, [[0.6, -0.7], [-0.2, 0.4]], atol=1e-14)
    # Independent residual uses scalar dot products rather than the inverse kernel.
    for row in range(2):
        for column in range(2):
            actual = sum(values[row][k] * inverse[k][column] for k in range(2))
            assert abs(actual - int(row == column)) < 1e-14


def test_matrix_solve_recovers_a_linear_model_and_least_squares_residual(ee):
    design = ee.Array([[1, 0], [1, 1], [1, 2]])
    fit = output(ee, design.matrixSolve([[1], [3], [5]]))
    np.testing.assert_allclose(fit, [[1], [2]], atol=1e-14)
    # Inconsistent observations: hand-derived normal equations give 1/2, 5/2.
    fit = output(ee, design.matrixSolve([[1], [2], [6]]))
    np.testing.assert_allclose(fit, [[0.5], [2.5]], atol=1e-14)
    residual = [sum([1, x][j] * fit[j][0] for j in range(2)) - y
                for x, y in zip([0, 1, 2], [1, 2, 6])]
    assert abs(sum(residual)) < 1e-14
    assert abs(sum(x * error for x, error in zip([0, 1, 2], residual))) < 1e-14


def test_pseudoinverse_matches_rank_one_closed_form(ee):
    # A = u v^T, A+ = v u^T / ((u^T u)(v^T v)).
    array = ee.Array([[1, 2], [2, 4], [3, 6]])
    expected = [[1 / 70, 2 / 70, 3 / 70], [2 / 70, 4 / 70, 6 / 70]]
    np.testing.assert_allclose(output(ee, array.matrixPseudoInverse()), expected, atol=1e-15)


@pytest.mark.parametrize("value", [[], [[], []], [[1], [2, 3]], [True], [float("nan")], [float("inf")], [2**54], ["3"]])
def test_constructor_rejects_unsupported_or_malformed_numeric_values(value):
    with pytest.raises(UnsupportedEEError):
        raw("Array", values=value)


def test_pixel_type_unknown_parameters_and_raw_lists_are_not_silently_cast():
    with pytest.raises(UnsupportedEEError, match="PixelType"):
        raw("Array", values=[1], pixelType="int")
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        raw("Array", values=[1], ignored=True)
    with pytest.raises(UnsupportedEEError, match="Expected a static ee.Array"):
        raw("Array.matrixMultiply", left=[[1]], right=[[2]])
    with pytest.raises(UnsupportedEEError, match="Unsupported static Array"):
        raw("Array.fake", array=raw("Array", values=[1]))


@pytest.mark.parametrize("operation", [
    lambda ee: ee.Array([[1, 2]]).matrixMultiply([[1, 2]]),
    lambda ee: ee.Array([1, 2]).matrixMultiply([1, 2]),
    lambda ee: ee.Array([[1, 2]]).matrixInverse(),
    lambda ee: ee.Array([[1, 2], [2, 4]]).matrixInverse(),
    lambda ee: ee.Array([[1, 2], [2, 4]]).matrixSolve([[1], [2]]),
    lambda ee: ee.Array([[1, 2]]).matrixSolve([[1]]),
    lambda ee: ee.Array([[1], [2]]).matrixSolve([[1]]),
    lambda ee: ee.Array([[1, 2]]).get([1, 0]),
    lambda ee: ee.Array([[1, 2]]).get([0]),
    lambda ee: ee.Array([[1, 2]]).get([0, -1]),
    lambda ee: ee.Array([[1, 2]]).transpose(axis1=2, axis2=0),
    lambda ee: ee.Array([[1, 2]]).reshape([3]),
    lambda ee: ee.Array([[1, 2]]).reshape([-1, -1]),
    lambda ee: ee.Array([[1, 2]]).reshape([0, 2]),
])
def test_shape_and_matrix_errors_are_explicit(ee, operation):
    with pytest.raises(UnsupportedEEError):
        output(ee, operation(ee))


def test_cell_rank_and_shared_work_limits_reject_before_expensive_operations():
    with pytest.raises(UnsupportedEEError, match="10000"):
        raw("Array", values=[0] * 10001)
    nested = [1]
    for _ in range(8):
        nested = [nested]
    with pytest.raises(UnsupportedEEError, match="rank"):
        raw("Array", values=nested)
    array = raw("Array", values=[[1.0] * 40] * 40)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        raw("Array.matrixMultiply", left=array, right=array)
    translator = Translator([], {}, {})
    translator.steps = 49999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_array(translator, "Array.matrixMultiply", {"left":array,"right":array})


def test_finite_result_guard_and_constructor_immutability():
    array = raw("Array", values=[[1e308]])
    with pytest.raises(UnsupportedEEError, match="finite"):
        raw("Array.matrixMultiply", left=array, right=array)
    assert isinstance(array, StaticArray)
    with pytest.raises(ValueError):
        array.data[0, 0] = 0


def test_layout_and_list_materialization_charge_shared_cell_work():
    translator = Translator([], {}, {})
    array = invoke_array(translator, "Array", {"values": [[1, 2], [3, 4]]})
    assert translator.steps == 4
    invoke_array(translator, "Array.toList", {"array": array})
    assert translator.steps == 8
    invoke_array(translator, "Array.transpose", {"array": array})
    assert translator.steps == 12
    invoke_array(translator, "Array.length", {"array": array})
    assert translator.steps == 14
    translator.steps = 49_998
    for name in ["Array", "Array.toList", "Array.transpose"]:
        arguments = {"values": [[1, 2], [3, 4]]} if name == "Array" else {"array": array}
        with pytest.raises(UnsupportedEEError, match="work budget"):
            invoke_array(translator, name, arguments)


def test_transpose_algorithms_reject_unknown_wire_arguments():
    array = raw("Array", values=[[1, 2]])
    for name in ["Array.transpose", "Array.matrixTranspose"]:
        with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
            raw(name, array=array, ignored=True)
