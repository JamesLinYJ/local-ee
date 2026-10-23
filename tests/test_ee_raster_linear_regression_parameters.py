"""Limits and input-schema rejection cases for raster linearRegression."""
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
import json

import numpy as np
import pytest

from gee.ee_translate import UnsupportedEEError, compile_expression
from ee_float64_graph_reference import evaluate_float64_graph
from ee_raster_regression_helpers import (
    FRAME_IDS,
    bundle,
    complete_rows,
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


def test_explicit_float64_regression_requires_common_grid_when_projection_is_missing(
    ee, local,
):
    images = [ee.Image(item).select(["x", "y0"]).toDouble() for item in FRAME_IDS]
    model = ee.ImageCollection.fromImages(images).reduce(
        ee.Reducer.linearRegression(numX=1, numY=1)
    )
    coefficients, _ = flattened(ee, model, 1, 1)
    with pytest.raises(UnsupportedEEError, match="proj:code/epsg and proj:transform"):
        compile_value(ee, coefficients, local)


def fraction_through_origin_reference(local, item_ids, *, residual=False):
    """Exact rational fit, with a high-precision square root for its RMS."""
    coefficients = np.full((1, len(local["grid"])), np.nan, dtype=np.float64)
    for pixel in range(len(local["grid"])):
        rows = complete_rows(local, item_ids, pixel, num_x=1, num_y=1)
        x_values = [Fraction.from_float(float(value)) for value in rows[:, 0]]
        y_values = [Fraction.from_float(float(value)) for value in rows[:, 1]]
        denominator = sum(value * value for value in x_values)
        if len(x_values) < 2 or denominator == 0:
            continue
        numerator = sum(x * y for x, y in zip(x_values, y_values))
        beta = numerator / denominator
        if residual:
            squared = sum((y - beta * x)**2 for x, y in zip(x_values, y_values))
            mean_squared = squared / len(x_values)
            with localcontext() as context:
                context.prec = 80
                value = Decimal(mean_squared.numerator) / Decimal(mean_squared.denominator)
                coefficients[0, pixel] = float(value.sqrt())
        else:
            coefficients[0, pixel] = float(beta)
    return coefficients


def test_aligned_float64_through_origin_coefficients_keep_masks_and_large_offsets(ee, local):
    local = deepcopy(local)
    ids = ("a", "b", "c")
    for item in local["items"]["sentinel-2-l2a"]:
        item["properties"].update({
            "proj:code": "EPSG:32649",
            "proj:transform": [1, 0, 0, 0, -1, 1],
        })

    # Adjacent predictors remain distinct in Float64 at this common offset;
    # the final cell is deliberately degenerate. One response is missing so
    # the fit also checks per-observation mask intersection.
    base = float(2**26)
    perturbations = (-16.0, 0.0, 16.0)
    for index, item_id in enumerate(ids):
        predictor = np.full(len(local["grid"]), base + index, dtype=np.float64)
        predictor[-1] = 0.0
        response = 2.0 * predictor + perturbations[index]
        if item_id == "b":
            response[1] = np.nan
        local["arrays"][item_id]["x"] = predictor
        local["arrays"][item_id]["y0"] = response

    images = [ee.Image(item).select(["x", "y0"]).toDouble() for item in ids]
    model = ee.ImageCollection.fromImages(images).reduce(
        ee.Reducer.linearRegression(numX=1, numY=1)
    )
    coefficients, residuals = flattened(ee, model, 1, 1)
    result = compile_value(ee, coefficients, local)
    assert result["bands"] == ["through_origin_y0"]
    assert result["source_item_ids"] == list(ids)
    assert not any(node["process_id"] == "local_ee_to_float"
                   for node in result["process_graph"].values())
    double_ops = {
        json.loads(node["arguments"]["spec"])["op"]
        for node in result["process_graph"].values()
        if node["process_id"] == "local_ee_integer_values"
    }
    assert {"multiply", "divide", "gt"} <= double_ops

    actual, names, timed = evaluate_float64_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries=local["geometries"],
    )
    expected = fraction_through_origin_reference(local, ids)
    assert names == ["through_origin_y0"] and not timed
    # The reference uses exact fractions over the supplied binary64 values;
    # the raster reducer's independent floating accumulation is checked to
    # within a few ULPs at coefficient magnitude two.
    np.testing.assert_allclose(actual, expected, rtol=2e-15, atol=2e-15,
                               equal_nan=True)
    assert np.isfinite(actual[0, 0])
    assert np.isfinite(actual[0, 1])  # Two observations remain after masking b.
    assert np.isnan(actual[0, 4])      # Outside all three source geometries.
    assert np.isnan(actual[0, 5])      # Zero predictor norm is undefined.
    # Immutable lineage facts are shared without caching the source-grid
    # validation. The original three-frame residual now fits unchanged caps.
    residual_result = compile_value(ee, residuals, local)
    actual_rms, names, timed = evaluate_float64_graph(
        residual_result, local["arrays"], grid=local["grid"],
        source_geometries=local["geometries"],
    )
    expected_rms = fraction_through_origin_reference(local, ids, residual=True)
    assert names == ["y0"] and not timed
    np.testing.assert_allclose(actual_rms, expected_rms, rtol=2e-15, atol=2e-15,
                               equal_nan=True)
    assert len(residual_result["process_graph"]) <= 500


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
