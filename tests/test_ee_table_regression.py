"""Pinned table-regression serialization and independent static controls."""
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.table_reducers import (
    TableReducer,
    invoke_reduce_columns,
    invoke_table_reducer,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def output(ee, value):
    encoded = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(encoded, [], {})["value"]


def feature_collection(rows):
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None, "properties": row}
            for row in rows
        ],
    }


def invoke(reducer, rows, selectors, **arguments):
    translator = Translator([], {}, {})
    return invoke_reduce_columns(
        translator,
        "Collection.reduceColumns",
        {"collection": feature_collection(rows), "reducer": reducer,
         "selectors": selectors, **arguments},
    )


def test_official_sdk_serializes_regression_and_coefficients_compose_as_ee_array(ee):
    fc = ee.FeatureCollection([
        ee.Feature(None, {"x0": 1, "x1": 0, "y0": 5, "y1": 1}),
        ee.Feature(None, {"x0": 1, "x1": 1, "y0": 7, "y1": 2}),
        ee.Feature(None, {"x0": 1, "x1": 2, "y0": 9, "y1": 3}),
        ee.Feature(None, {"x0": 1, "x1": 3, "y0": 11, "y1": 4}),
    ])
    result = fc.reduceColumns(
        reducer=ee.Reducer.linearRegression(numX=2, numY=2),
        selectors=["x0", "x1", "y0", "y1"],
    )
    fit = output(ee, result)
    np.testing.assert_allclose(fit["coefficients"], [[5.0, 1.0], [2.0, 1.0]], atol=1e-14)
    np.testing.assert_allclose(fit["residuals"], [0.0, 0.0], atol=1e-14)
    # This exercises the internal typed array before public JSON conversion.
    assert output(ee, ee.Array(result.get("coefficients")).get([1, 0])) == 2


def test_regression_rms_uses_all_valid_observations_and_each_response_column(ee):
    rows = [
        {"intercept": 1, "x": 0, "y0": 1, "y1": 2},
        {"intercept": 1, "x": 1, "y0": 2, "y1": 4},
        {"intercept": 1, "x": 2, "y0": 6, "y1": 4},
    ]
    fc = ee.FeatureCollection([ee.Feature(None, row) for row in rows])
    result = fc.reduceColumns(
        reducer=ee.Reducer.linearRegression(2, 2),
        selectors=["intercept", "x", "y0", "y1"],
    )
    fit = output(ee, result)
    np.testing.assert_allclose(fit["coefficients"], [[0.5, 7 / 3], [2.5, 1.0]], atol=1e-14)
    # The first residual column is (0.5, -1, 0.5); the second is
    # (-1/3, 2/3, -1/3). RMS divides by all three observations.
    np.testing.assert_allclose(fit["residuals"], [np.sqrt(1.5 / 3), np.sqrt(2) / 3], atol=1e-14)


def test_linear_fit_returns_slope_and_offset_for_the_two_selected_inputs(ee):
    fc = ee.FeatureCollection([
        ee.Feature(None, {"x": 0, "y": 1}),
        ee.Feature(None, {"x": 1, "y": 3}),
        ee.Feature(None, {"x": 2, "y": 5}),
    ])
    result = fc.reduceColumns(reducer=ee.Reducer.linearFit(), selectors=["x", "y"])
    fit = output(ee, result)
    np.testing.assert_allclose([fit["scale"], fit["offset"]], [2.0, 1.0], atol=1e-14)


def test_null_and_missing_selected_properties_skip_whole_rows(ee):
    fc = ee.FeatureCollection([
        ee.Feature(None, {"intercept": 1, "x": 0, "y": 1}),
        ee.Feature(None, {"intercept": 1, "x": None, "y": 2}),
        ee.Feature(None, {"intercept": 1, "x": 1, "y": 3}),
        ee.Feature(None, {"intercept": 1, "x": 2}),
        ee.Feature(None, {"intercept": 1, "x": 3, "y": 7}),
    ])
    result = fc.reduceColumns(
        reducer=ee.Reducer.linearRegression(2),
        selectors=["intercept", "x", "y"],
    )
    fit = output(ee, result)
    np.testing.assert_allclose(fit["coefficients"], [[1.0], [2.0]], atol=1e-14)
    np.testing.assert_allclose(fit["residuals"], [0.0], atol=1e-14)


@pytest.mark.parametrize("rows,num_x", [
    ([{"x0": 1, "x1": 0, "y": 1}, {"x0": 1, "x1": 1, "y": 3}], 2),
    ([{"x0": 1, "x1": 2, "y": 1}, {"x0": 1, "x1": 2, "y": 3},
      {"x0": 1, "x1": 2, "y": 5}], 2),
])
def test_underdetermined_or_rank_deficient_design_returns_both_outputs_null(rows, num_x):
    reducer = TableReducer("linearRegression", num_x, 1)
    result = invoke(reducer, rows, ["x0", "x1", "y"])
    assert result == {"coefficients": None, "residuals": None}


def test_linear_fit_returns_null_when_two_parameters_cannot_be_identified():
    reducer = TableReducer("linearFit", 1, 1)
    assert invoke(reducer, [{"x": 2, "y": 1}], ["x", "y"]) == {
        "scale": None, "offset": None,
    }
    assert invoke(reducer, [{"x": 2, "y": 1}, {"x": 2, "y": 4}], ["x", "y"]) == {
        "scale": None, "offset": None,
    }


def test_empty_input_and_malformed_selectors_have_explicit_results():
    reducer = TableReducer("linearRegression", 2, 1)
    assert invoke(reducer, [], ["x0", "x1", "y"]) == {
        "coefficients": None, "residuals": None,
    }
    with pytest.raises(UnsupportedEEError, match="non-empty property names"):
        invoke(reducer, [], ["x0", "", "y"])


@pytest.mark.parametrize("args", [
    {"numX": 0}, {"numX": 1, "numY": 0}, {"numX": True},
    {"numX": 1, "numY": 1, "ignored": 4}, {"numY": 1},
    {"numX": 32, "numY": 1},
])
def test_linear_regression_constructor_rejects_invalid_shape_or_parameters(args):
    with pytest.raises(UnsupportedEEError):
        invoke_table_reducer(Translator([], {}, {}), "Reducer.linearRegression", args)


def test_reducer_input_count_and_weight_selectors_are_never_dropped():
    reducer = TableReducer("linearRegression", 1, 1)
    with pytest.raises(UnsupportedEEError, match="exactly 2 selectors"):
        invoke(reducer, [{"x": 0, "y": 1}], ["x"])
    with pytest.raises(UnsupportedEEError, match="Weighted table regression"):
        invoke(reducer, [{"x": 0, "y": 1, "w": 3}], ["x", "y"],
               weightSelectors=["w"])


def test_nested_table_selectors_reject_instead_of_silently_dropping_all_rows(ee):
    collection = ee.FeatureCollection([
        ee.Feature(None, {"nested": {"x": 1}, "y": 3}),
        ee.Feature(None, {"nested": {"x": 2}, "y": 5}),
    ])
    with pytest.raises(UnsupportedEEError, match="flat property selectors"):
        output(ee, collection.reduceColumns(ee.Reducer.linearFit(), ["nested.x", "y"]))


@pytest.mark.parametrize("bad", [True, "2", float("inf"), float("nan"), 10**1000])
def test_non_numeric_boolean_and_nonfinite_properties_fail_explicitly(bad):
    reducer = TableReducer("linearFit", 1, 1)
    with pytest.raises(UnsupportedEEError, match="finite numeric|finite"):
        invoke(reducer, [{"x": 0, "y": 1}, {"x": 1, "y": bad}], ["x", "y"])


def test_only_bounded_inline_featurecollections_are_accepted():
    reducer = TableReducer("linearFit", 1, 1)
    with pytest.raises(UnsupportedEEError, match="inline FeatureCollection"):
        invoke_reduce_columns(
            Translator([], {}, {}), "Collection.reduceColumns",
            {"collection": [], "reducer": reducer, "selectors": ["x", "y"]},
        )
    rows = [{"x": i, "y": 2 * i} for i in range(1001)]
    with pytest.raises(UnsupportedEEError, match="1000 inline features"):
        invoke(reducer, rows, ["x", "y"])


def test_row_scan_and_least_squares_share_compilation_work_budget():
    x_columns = [f"x{index}" for index in range(30)]
    selectors = [*x_columns, "y"]
    reducer = TableReducer("linearRegression", 30, 1)
    rows = [{**{key: i for key in x_columns}, "y": 2 * i + 1}
            for i in range(100)]
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke(reducer, rows, selectors)
    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_reduce_columns(
            translator, "Collection.reduceColumns",
            {"collection": feature_collection(rows), "reducer": reducer,
             "selectors": selectors},
        )


def test_property_and_selector_scan_is_charged_before_scanning_keys():
    translator = Translator([], {}, {})
    translator.steps = 49_990
    properties = {f"field_{index}": index for index in range(10)}
    properties.update({"x": 0, "y": 1})
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_reduce_columns(
            translator, "Collection.reduceColumns",
            {"collection": feature_collection([properties]),
             "reducer": TableReducer("linearFit", 1, 1), "selectors": ["x", "y"]},
        )
