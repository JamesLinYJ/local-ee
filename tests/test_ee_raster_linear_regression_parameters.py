"""Limits and input-schema rejection cases for raster linearRegression."""
import numpy as np
import pytest

from gee.ee_translate import UnsupportedEEError, compile_expression
from ee_raster_regression_helpers import (
    FRAME_IDS,
    bundle,
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


def test_eight_frame_boundary_is_supported_and_nine_frames_reject(ee, local):
    ids = [*FRAME_IDS, "a", "b"]
    model = bundle(ee, ids, num_x=1, num_y=1)
    coefficients, residuals = flattened(ee, model, 1, 1)
    _, coefficient_data, _ = compile_raster(ee, coefficients, local)
    _, residual_data, _ = compile_raster(ee, residuals, local)
    expected_coeff, expected_resid = numpy_reference(local, ids, 1, 1)
    np.testing.assert_allclose(coefficient_data, expected_coeff,
                               rtol=2e-5, atol=2e-5, equal_nan=True)
    np.testing.assert_allclose(residual_data, expected_resid,
                               rtol=2e-5, atol=2e-5, equal_nan=True)

    too_many = bundle(ee, [*ids, "c"], num_x=1, num_y=1)
    coefficients, _ = flattened(ee, too_many, 1, 1)
    with pytest.raises(UnsupportedEEError, match="8 frames"):
        compile_value(ee, coefficients, local)


@pytest.mark.parametrize(("num_x", "num_y"), [
    (0, 1), (3, 1), (1, 0), (1, 5), (True, 1), (1, False), (1.5, 1),
])
def test_regression_parameter_bounds_and_types_are_explicit(ee, local, num_x, num_y):
    expression = bundle(ee, FRAME_IDS, num_x=num_x, num_y=num_y)
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, expression, local)


def test_parallel_scale_accepts_default_or_one_and_rejects_other_values(ee, local):
    model = bundle(ee, FRAME_IDS, num_x=1, num_y=1, parallel_scale=None)
    coefficients, _ = flattened(ee, model, 1, 1)
    _, default_data, _ = compile_raster(ee, coefficients, local)
    expected, _ = numpy_reference(local, FRAME_IDS, 1, 1)
    np.testing.assert_allclose(default_data, expected, rtol=2e-5, atol=2e-5, equal_nan=True)

    for scale in (2, 0, False):
        expression = bundle(ee, FRAME_IDS, num_x=1, num_y=1, parallel_scale=scale)
        coefficients, _ = flattened(ee, expression, 1, 1)
        with pytest.raises(UnsupportedEEError):
            compile_value(ee, coefficients, local)


def test_same_scalar_band_names_order_and_counts_are_required(ee, local):
    reducer = ee.Reducer.linearRegression(numX=1, numY=1)
    wrong_count = ee.ImageCollection.fromImages([
        ee.Image("a").select(["x"]),
    ]).reduce(reducer)
    reordered = ee.ImageCollection.fromImages([
        ee.Image("a").select(["x", "y0"]),
        ee.Image("b").select(["y0", "x"]),
    ]).reduce(reducer)
    renamed = ee.ImageCollection.fromImages([
        ee.Image("a").select(["x", "y0"]),
        ee.Image("b").select(["x", "y0"], ["other_x", "y0"]),
    ]).reduce(reducer)
    array_frame = ee.ImageCollection.fromImages([
        ee.Image("a").select(["x", "y0"]).toArray(),
    ]).reduce(reducer)
    for result in (wrong_count, reordered, renamed, array_frame):
        with pytest.raises(UnsupportedEEError):
            compile_value(ee, result.select("coefficients").arrayFlatten(
                [["x"], ["y0"]]), local)


def test_explicit_float64_input_is_rejected_by_scalar_callback_backend(ee, local):
    images = [ee.Image(item).select(["x", "y0"]).toDouble() for item in FRAME_IDS]
    model = ee.ImageCollection.fromImages(images).reduce(
        ee.Reducer.linearRegression(numX=1, numY=1)
    )
    coefficients, _ = flattened(ee, model, 1, 1)
    with pytest.raises(UnsupportedEEError, match="Float64"):
        compile_value(ee, coefficients, local)


def test_unknown_wire_arguments_and_shared_work_budget_are_enforced(ee, local):
    model = bundle(ee, FRAME_IDS, num_x=1, num_y=1)
    coefficients, _ = flattened(ee, model, 1, 1)
    expression = encode(ee, coefficients)
    reduce_node = invocation(expression, "ImageCollection.reduce")
    assert reduce_node is not None
    reduce_node["arguments"]["ignored"] = 7
    with pytest.raises(UnsupportedEEError, match="algorithm arguments"):
        compile_expression(expression, local["catalog"], local["items"])

    expression = encode(ee, coefficients)
    reducer_node = invocation(expression, "Reducer.linearRegression")
    assert reducer_node is not None
    reducer_node["arguments"]["ignored"] = 7
    with pytest.raises(UnsupportedEEError, match="algorithm arguments"):
        compile_expression(expression, local["catalog"], local["items"])

    expression = encode(ee, coefficients)
    reduce_node = invocation(expression, "ImageCollection.reduce")
    reduce_node["arguments"]["ignored"] = [[0] * 9000 for _ in range(6)]
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        compile_expression(expression, local["catalog"], local["items"])


def test_process_graph_still_enforces_the_existing_500_node_limit(ee, local):
    images = []
    for offset, item_id in enumerate(("a", "b", "c", "d")):
        image = ee.Image(item_id).select(["x", "y0"])
        for _ in range(40):
            image = image.add(offset + 1)
        images.append(image)
    model = ee.ImageCollection.fromImages(images).reduce(
        ee.Reducer.linearRegression(numX=1, numY=1)
    )
    coefficients, _ = flattened(ee, model, 1, 1)
    with pytest.raises(UnsupportedEEError, match="500 nodes"):
        compile_value(ee, coefficients, local)
