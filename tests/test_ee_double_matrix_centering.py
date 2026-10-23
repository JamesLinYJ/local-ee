"""Constant-column stabilization tests for explicit Double matrixSolve."""

import numpy as np
import pytest

from test_ee_double_array_solve import (
    ee, local, offline_only,
    _compile_raster,
    _design,
    _evaluate_pixel,
    _fraction_fit,
    _pixel_node_count,
    _response,
)
from gee.compat.earthengine import raster_matrix_solve as solve_module
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, const
from gee.compat.earthengine.raster_array_core import wrap_array_image
from gee.compat.earthengine.raster_matrix_solve import invoke_raster_matrix
from gee.ee_translate import UnsupportedEEError


def _literal_array(shape, values, cast="to_double", name="array"):
    return wrap_array_image(
        Image([], {}), shape,
        tuple(Pixel(cast, (const(float(value)),)) for value in values),
        const(True), name,
    )


def _direct_solve(left, right, translator=None):
    translator = translator or Translator([], {}, {})
    result = invoke_raster_matrix(translator, "Image.matrixSolve", {
        "image1": left,
        "image2": right,
    })
    return result, translator


def _pixel_ops(cells):
    seen = set()
    operations = set()

    def visit(pixel):
        if id(pixel) in seen:
            return
        seen.add(id(pixel))
        operations.add(pixel.op)
        for argument in pixel.args:
            if isinstance(argument, Pixel):
                visit(argument)

    for cell in cells:
        visit(cell)
    return operations


def test_nonfirst_nonunit_constant_column_centers_every_rhs_to_fraction_accuracy(ee, local):
    constant = 2.0
    intercepts = [2**40 + value for value in (0.25, 0.375, 0.5, 0.625, 0.75, 0.875)]
    slopes = [0.125, -0.25, 0.5, 0.75, -0.125, 0.25]
    for row in range(4):
        local["arrays"][local["item_id"]][f"y{row}"] = np.asarray([
            constant * intercepts[column] + slopes[column] * row
            for column in range(6)
        ], dtype=np.float64)
    local["arrays"][local["item_id"]]["y0"][1] = np.nan
    local["arrays"][local["item_id"]]["y2"][3] = np.nan

    design = _design(ee, [[0, constant], [1, constant],
                          [2, constant], [3, constant]])
    fitted = design.matrixSolve(_response(ee, 4)).arrayFlatten([
        ["slope", "offset"], ["rhs"],
    ])

    _result, actual, names = _compile_raster(ee, fitted, local)

    assert names == ["slope_rhs", "offset_rhs"]
    valid_columns = (0, 2, 4)
    expected = np.full((2, 6), np.nan)
    for column in valid_columns:
        samples = [local["arrays"][local["item_id"]][f"y{row}"][column]
                   for row in range(4)]
        response_intercept, response_slope = _fraction_fit(samples)
        expected[:, column] = [float(response_slope),
                               float(response_intercept / constant)]
    slope_error = np.abs(actual[0, list(valid_columns)]
                         - expected[0, list(valid_columns)])
    offset_error = np.abs(actual[1, list(valid_columns)]
                          - expected[1, list(valid_columns)])
    offset_ulp = np.spacing(np.abs(expected[1, list(valid_columns)]))
    assert float(np.max(slope_error)) <= 1e-7
    assert np.all(offset_error <= offset_ulp)
    assert np.isnan(actual[:, 1]).all()  # masked first observation invalidates full array
    assert np.isnan(actual[:, 3]).all()  # another masked observation has same whole-array rule
    assert np.isnan(actual[:, 5]).all()  # outside the source footprint


def test_float32_rhs_anchor_is_promoted_after_its_nested_rounding(ee, local):
    design = _design(ee, [[0, 2], [1, 2], [2, 2], [3, 2]])
    fitted = design.matrixSolve(_response(ee, 4, "float")).arrayFlatten(
        [["slope", "offset"], ["rhs"]],
    )

    _result, actual, _names = _compile_raster(ee, fitted, local)

    for column in (0, 1, 2, 4):
        samples = [float(np.float32(local["arrays"][local["item_id"]][f"y{row}"][column]))
                   for row in range(4)]
        response_intercept, response_slope = _fraction_fit(samples)
        expected = [float(response_slope), float(response_intercept / 2)]
        assert abs(actual[0, column] - expected[0]) <= 1e-7
        assert abs(actual[1, column] - expected[1]) <= np.spacing(abs(expected[1]))
    assert np.isnan(actual[:, 3]).all()
    assert np.isnan(actual[:, 5]).all()


def test_nonunit_constant_column_centers_multiple_rhs_columns():
    constant = 2.0
    design = np.asarray([[0, constant], [1, constant],
                         [2, constant], [3, constant]], dtype=np.float64)
    intercepts = [2**40 + 0.25, -(2**39) + 0.5]
    slopes = [0.125, -0.25]
    response = np.asarray([
        [constant * intercepts[column] + slopes[column] * row
         for column in range(2)]
        for row in range(4)
    ], dtype=np.float64)

    result, _translator = _direct_solve(
        _literal_array((4, 2), design.flat, name="lhs"),
        _literal_array((4, 2), response.flat, name="rhs"),
    )

    actual = np.asarray([_evaluate_pixel(cell) for cell in result.cells]).reshape((2, 2))
    expected = np.asarray([
        [float(_fraction_fit(response[:, column])[1]) for column in range(2)],
        [float(_fraction_fit(response[:, column])[0] / constant)
         for column in range(2)],
    ])
    slope_error = np.abs(actual[0] - expected[0])
    offset_error = np.abs(actual[1] - expected[1])
    assert float(np.max(slope_error)) <= 1e-7
    assert np.all(offset_error <= np.spacing(np.abs(expected[1])))


def test_no_nonzero_constant_predictor_keeps_the_original_pseudoinverse_path():
    design = np.asarray([[1, 2], [2, 1], [3, 4], [4, -1]], dtype=np.float64)
    response = np.asarray([2**40 + 0.25, 2**40 + 0.5,
                           2**40 + 0.75, 2**40 + 1.0], dtype=np.float64)
    left = _literal_array((4, 2), design.flat, name="lhs")
    right = _literal_array((4, 1), response, name="rhs")

    result, _translator = _direct_solve(left, right)

    actual = np.asarray([_evaluate_pixel(cell) for cell in result.cells])
    expected = np.linalg.lstsq(design, response, rcond=None)[0]
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-4)
    assert not _pixel_ops(result.cells).intersection({
        "absolute", "max2", "lte", "subtract",
    })


def test_overflow_guard_preserves_finite_opposite_sign_extreme_mean():
    left = _literal_array((2, 1), [1, 1], name="lhs")
    right = _literal_array((2, 1), [1e308, -1e308], name="rhs")

    result, _translator = _direct_solve(left, right)

    value = _evaluate_pixel(result.cells[0])
    assert np.isfinite(value)
    assert abs(value) < 1e293
    assert {"absolute", "max2", "lte"}.issubset(_pixel_ops(result.cells))


def test_finite_extreme_constant_predictor_uses_a_finite_anchor_scale():
    left = _literal_array((2, 1), [1e300, 1e300], name="lhs")
    right = _literal_array((2, 1), [1.5e300, 1.5e300], name="rhs")

    result, _translator = _direct_solve(left, right)

    assert _evaluate_pixel(result.cells[0]) == pytest.approx(1.5, abs=1e-14)


def test_centered_rank_failure_and_added_work_are_rejected_before_numpy(
        monkeypatch):
    deficient = _literal_array((3, 2), [2, 1, 2, 1, 2, 1], name="lhs")
    right = _literal_array((3, 1), [3, 3, 3], name="rhs")
    with pytest.raises(UnsupportedEEError, match="full column rank"):
        _direct_solve(deficient, right)

    constant = _literal_array((2, 1), [1, 1], name="lhs")
    pair = _literal_array((2, 1), [2, 4], name="rhs")
    translator = Translator([], {}, {})
    translator.steps = 49_900

    def unexpected_lstsq(*_args, **_kwargs):
        raise AssertionError("centering work was not precharged")

    monkeypatch.setattr(solve_module.np.linalg, "lstsq", unexpected_lstsq)
    with pytest.raises(UnsupportedEEError, match="compilation work budget"):
        _direct_solve(constant, pair, translator)
    assert translator.steps == 49_900
