"""Numeric regression behavior through the pinned Earth Engine SDK."""
import numpy as np
import pytest
from shapely.geometry import shape

from gee.ee_translate import UnsupportedEEError
from ee_raster_regression_helpers import (
    COLLECTION_ID,
    FRAME_IDS,
    RESPONSES,
    bundle,
    checked_fit,
    compile_raster,
    compile_value,
    encode,
    flattened,
    invocation,
    make_ee,
    make_local,
    numpy_reference,
)


@pytest.fixture
def ee():
    return make_ee()


@pytest.fixture
def local():
    return make_local()


def test_multivariate_coefficients_and_rms_match_independent_lstsq_with_spatial_masks(ee, local):
    ids = ("a", "b", "f")
    model = bundle(ee, ids, num_x=1, num_y=2)
    (coefficient_result, coefficient_data, coefficient_names, residual_result,
     residual_data, residual_names) = checked_fit(ee, model, local, 1, 2, ids)

    assert coefficient_names == ["through_origin_y0", "through_origin_y1"]
    assert residual_names == ["y0", "y1"]
    assert coefficient_result["properties"] == residual_result["properties"] == {}
    assert set(coefficient_result["source_item_ids"]) == set(ids)

    # A null in y1 removes that whole observation from every response's fit.
    common_rows = np.array([
        [local["arrays"][item]["x"][2], local["arrays"][item]["y0"][2]]
        for item in ids
        if np.isfinite(local["arrays"][item]["x"][2])
        and np.isfinite(local["arrays"][item]["y0"][2])
        and np.isfinite(local["arrays"][item]["y1"][2])
    ])
    y0_only_rows = np.asarray([
        [1, local["arrays"][item]["x"][2], local["arrays"][item]["y0"][2]]
        for item in ids
        if np.isfinite(local["arrays"][item]["y0"][2])
    ])
    common_beta = np.linalg.lstsq(common_rows[:, :1], common_rows[:, 1], rcond=None)[0]
    independent_y0 = np.linalg.lstsq(y0_only_rows[:, :1], y0_only_rows[:, 1], rcond=None)[0]
    np.testing.assert_allclose(coefficient_data[0, 2], common_beta[0], atol=2e-5)
    assert not np.isclose(coefficient_data[0, 2], independent_y0[0])

    # Earth Engine's residuals divide by all observations, not n minus p.
    rows = np.array([
        [local["arrays"][item]["x"][1], *[local["arrays"][item][f"y{i}"][1]
                                           for i in range(2)]]
        for item in ids
    ])
    beta = np.linalg.lstsq(rows[:, :1], rows[:, 1:], rcond=None)[0]
    squared_error = (rows[:, 1:] - rows[:, :1] @ beta) ** 2
    rms_n = np.sqrt(np.mean(squared_error, axis=0))
    rms_degrees_of_freedom = np.sqrt(np.sum(squared_error, axis=0) / (len(rows) - 1))
    np.testing.assert_allclose(residual_data[:, 1], rms_n, rtol=2e-5, atol=2e-5)
    assert not np.allclose(residual_data[:, 1], rms_degrees_of_freedom)

    # A nonzero constant predictor remains valid for through-origin fitting.
    assert np.isfinite(coefficient_data[:, 3]).all()
    # One-footprint and zero-denominator locations mask both result arrays.
    for pixel in (4, 5):
        assert np.isnan(coefficient_data[:, pixel]).all()
        assert np.isnan(residual_data[:, pixel]).all()

    coefficients, _ = flattened(ee, model, 1, 2)
    geometry = compile_value(ee, coefficients.geometry(), local)["value"]
    union = shape(geometry)
    assert union.bounds == (0.0, 0.0, 6.0, 1.0)
    assert union.area == 6.0


def test_through_origin_regression_uses_x_sum_squares_and_supports_four_responses(ee, local):
    ids = ("a", "b")
    collection = ee.ImageCollection.fromImages([
        ee.Image(item).select(["x", *RESPONSES]) for item in ids
    ])
    model = collection.reduce(ee.Reducer.linearRegression(numX=1, numY=4), parallelScale=1)
    (coefficient_result, coefficient_data, coefficient_names, residual_result,
     residual_data, residual_names) = checked_fit(ee, model, local, 1, 4, ids)

    assert coefficient_names == ["through_origin_y0", "through_origin_y1",
                                 "through_origin_y2", "through_origin_y3"]
    assert residual_names == list(RESPONSES)
    assert coefficient_result["properties"] == residual_result["properties"] == {}
    assert set(coefficient_result["source_item_ids"]) == set(ids)
    assert np.isfinite(coefficient_data[:, 3]).all()  # nonzero constant x remains valid
    assert np.isnan(coefficient_data[:, 5]).all()    # zero x gives zero denominator


def test_intercept_schema_requires_a_literal_one_and_rejects_data_that_merely_equals_one(ee, local):
    # The source band contains only ones in this sample, but its raster values
    # cannot prove to the compiler that it is the intercept literal.
    images = [ee.Image(item).select(["one_like", "x", "y0"]) for item in FRAME_IDS]
    not_literal = ee.ImageCollection.fromImages(images).reduce(
        ee.Reducer.linearRegression(numX=2, numY=1)
    )
    with pytest.raises(UnsupportedEEError, match="intercept|literal|constant"):
        compile_value(ee, not_literal.select("coefficients").arrayFlatten(
            [["intercept", "slope"], ["y0"]]), local)

    wrong_literal = bundle(ee, FRAME_IDS, num_x=2, num_y=1, intercept=2)
    with pytest.raises(UnsupportedEEError, match="intercept|literal|constant"):
        compile_value(ee, wrong_literal.select("coefficients").arrayFlatten(
            [["intercept", "slope"], ["y0"]]), local)

    expression = encode(ee, bundle(ee, FRAME_IDS, num_x=2, num_y=1))
    names = [node.get("functionName") for _, node in expression.get("scope", [])
             if isinstance(node, dict)]
    assert "Image.constant" in names and "Image.toFloat" in names


def test_one_two_and_three_observation_thresholds_differ_by_predictor_schema(ee, local):
    one = bundle(ee, ["a"], num_x=1, num_y=1)
    _, one_coeff_data, _, _, one_resid_data, _ = checked_fit(ee, one, local, 1, 1, ["a"])
    assert np.isnan(one_coeff_data).all() and np.isnan(one_resid_data).all()

    two = bundle(ee, ["a", "b"], num_x=1, num_y=1)
    _, through_coeff_data, _, _, through_resid_data, _ = checked_fit(
        ee, two, local, 1, 1, ["a", "b"]
    )
    assert np.isfinite(through_coeff_data).any()
    assert np.isfinite(through_resid_data).any()

    two_predictors = bundle(ee, ["a", "b"], num_x=2, num_y=1)
    _, intercept_coeff_data, _, _, intercept_resid_data, _ = checked_fit(
        ee, two_predictors, local, 2, 1, ["a", "b"]
    )
    assert np.isnan(intercept_coeff_data).all() and np.isnan(intercept_resid_data).all()

    three_predictors = bundle(ee, ["a", "b", "c"], num_x=2, num_y=1)
    checked_fit(ee, three_predictors, local, 2, 1, ["a", "b", "c"])


def test_same_day_observations_and_explicit_duplicate_frames_keep_their_weights(ee, local):
    collection = ee.ImageCollection(COLLECTION_ID).select(["x", "y0"])
    normal = collection.reduce(ee.Reducer.linearRegression(numX=1, numY=1))
    normal_coeff, _ = flattened(ee, normal, 1, 1)
    result, normal_data, _ = compile_raster(ee, normal_coeff, local)
    expected, _ = numpy_reference(local, FRAME_IDS, 1, 1)
    np.testing.assert_allclose(normal_data, expected, rtol=2e-5, atol=2e-5, equal_nan=True)
    assert set(result["source_item_ids"]) == set(FRAME_IDS)

    # Duplicate frames remain duplicate observations in the regression input.
    ids = [*FRAME_IDS, "a"]
    repeated = bundle(ee, ids, num_x=1, num_y=1)
    repeated_coeff, _ = flattened(ee, repeated, 1, 1)
    repeated_result, repeated_data, _ = compile_raster(ee, repeated_coeff, local)
    expected_repeated, _ = numpy_reference(local, ids, 1, 1)
    np.testing.assert_allclose(repeated_data, expected_repeated,
                               rtol=2e-5, atol=2e-5, equal_nan=True)
    assert set(repeated_result["source_item_ids"]) == set(FRAME_IDS)
    assert not np.isclose(repeated_data[0, 1], normal_data[0, 1])


def test_regression_bundle_requires_array_selection_for_outputs(ee, local):
    model = bundle(ee, FRAME_IDS, num_x=2, num_y=2)
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, model, local)
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, model.add(1), local)
    assert compile_value(ee, model.bandNames(), local)["value"] == [
        "coefficients", "residuals",
    ]
