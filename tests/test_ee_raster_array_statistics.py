"""Numeric and multi-output array-pixel reductions with independent references."""
from pathlib import Path
import warnings

import numpy as np
import pytest

from gee.compat.earthengine.ir import UnsupportedEEError
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


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


@pytest.fixture
def local():
    bands = ["red", "nir"]
    return {
        "catalog": [{"id": "sentinel-2-l2a", "cube:dimensions": {
            "bands": {"values": bands},
        }}],
        "items": {"sentinel-2-l2a": [{
            "id": "statistics-scene", "bbox": [0, 0, 4, 1],
            "properties": {"system:index": "statistics-scene", "system:time_start": 1},
        }]},
        "arrays": {"statistics-scene": {
            "red": np.asarray([1.0, 2.0, np.nan, 5.0]),
            "nir": np.asarray([3.0, np.nan, 7.0, 5.0]),
        }},
    }


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def first_vector(ee):
    return ee.ImageCollection("sentinel-2-l2a").first().toArray().toArray(1)


def matrix(ee):
    return ee.Image(ee.Array([[1, 2], [3, 4]])).matrixMultiply(first_vector(ee))


def mixed_and_raw_columns(ee):
    source = first_vector(ee)
    mixed = ee.Image(ee.Array([[1, 2], [3, 4]])).matrixMultiply(source)
    raw = ee.Image(ee.Array([[1, 0], [0, 1]])).matrixMultiply(source)
    return mixed.arrayCat(raw, 1)


def native_reduce_reference(arguments, graph_values):
    """Independent NumPy oracle for the new typed Float64 reduction process."""
    data, _, timed = graph_values[arguments["data"]["from_node"]]
    axis = 1 if timed else 0
    values = np.asarray(data, dtype=np.float64)
    operation = arguments["reducer"]
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        if operation == "product":
            reduced = np.nanprod(values, axis=axis)
        elif operation == "stdDev":
            reduced = np.nanstd(values, axis=axis, ddof=0)
        elif operation == "variance":
            reduced = np.nanvar(values, axis=axis, ddof=0)
        elif operation == "sampleVariance":
            reduced = np.nanvar(values, axis=axis, ddof=1)
        elif operation == "min":
            reduced = np.nanmin(values, axis=axis)
        elif operation == "max":
            reduced = np.nanmax(values, axis=axis)
        elif operation == "sum":
            reduced = np.nansum(values, axis=axis)
        elif operation == "mean":
            reduced = np.nanmean(values, axis=axis)
        elif operation == "count":
            reduced = np.isfinite(values).sum(axis=axis)
        elif operation in {"first", "last"}:
            ordered = values if operation == "first" else np.flip(values, axis=axis)
            valid = np.isfinite(ordered)
            index = np.argmax(valid, axis=axis)
            reduced = np.take_along_axis(
                ordered, np.expand_dims(index, axis=axis), axis=axis,
            ).squeeze(axis=axis)
            reduced = np.where(valid.any(axis=axis), reduced, np.nan)
        elif operation == "median":
            reduced = np.nanmedian(values, axis=axis)
        elif operation == "sd":
            reduced = np.nanstd(values, axis=axis, ddof=1)
        else:
            raise AssertionError(f"unhandled reference operation {operation}")
    return reduced, ["v"], timed


def compile_raster(ee, expression, local):
    graph = compile_expression(encode(ee, expression), local["catalog"], local["items"])
    values, names, timed = evaluate_graph(
        graph, local["arrays"],
        process_handlers={"local_ee_reduce_bands": native_reduce_reference},
    )
    assert timed is False
    return graph, values, names


def process_ancestry(graph, reference):
    process_graph = graph["process_graph"]

    def references(value):
        if isinstance(value, dict):
            source = value.get("from_node")
            if isinstance(source, str):
                yield source
            else:
                for child in value.values():
                    yield from references(child)
        elif isinstance(value, (tuple, list)):
            for child in value:
                yield from references(child)

    pending = ([reference] if isinstance(reference, str)
               else list(references(reference)))
    seen = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        node = process_graph[current]
        pending.extend(references(node.get("arguments", {})))
    return seen


@pytest.mark.parametrize("name,expected", [
    ("product", [105.0, np.nan, np.nan, 525.0]),
    ("stdDev", [4.0, np.nan, np.nan, 10.0]),
    ("variance", [16.0, np.nan, np.nan, 100.0]),
    ("sampleVariance", [32.0, np.nan, np.nan, 200.0]),
])
def test_numeric_statistics_match_independent_reference_and_keep_whole_mask(
        ee, local, name, expected):
    expression = matrix(ee).arrayReduce(getattr(ee.Reducer, name)(), [0])
    graph, values, names = compile_raster(
        ee, expression.arrayFlatten([["row"], ["column"]]), local,
    )
    assert names == ["row_column"]
    np.testing.assert_allclose(values, [expected], equal_nan=True)
    reducers = [node["arguments"]["reducer"]
                for node in graph["process_graph"].values()
                if node["process_id"] == "local_ee_reduce_bands"]
    assert reducers == [name]
    assert any(node["process_id"] == "local_ee_to_double"
               for node in graph["process_graph"].values())


def test_minmax_field_axis_expands_in_row_major_output_order(ee, local):
    array = mixed_and_raw_columns(ee).toArray(2)
    reduced = array.arrayReduce(ee.Reducer.minMax(), [0], 2)
    graph, values, names = compile_raster(
        ee,
        reduced.arrayFlatten([["reduced"], ["mixed", "raw"], ["minimum", "maximum"]]),
        local,
    )
    assert names == [
        "reduced_mixed_minimum", "reduced_mixed_maximum",
        "reduced_raw_minimum", "reduced_raw_maximum",
    ]
    expected = np.asarray([
        [7, np.nan, np.nan, 15], [15, np.nan, np.nan, 35],
        [1, np.nan, np.nan, 5], [3, np.nan, np.nan, 5],
    ], dtype=np.float64)
    np.testing.assert_allclose(values, expected, equal_nan=True)
    reducers = [node["arguments"]["reducer"]
                for node in graph["process_graph"].values()
                if node["process_id"] == "local_ee_reduce_bands"]
    assert reducers == ["min", "max", "min", "max"]


def test_first_to_array_minmax_retains_float64_above_float32_and_native_data_path(
        ee, local):
    local["arrays"] = {"statistics-scene": {
        "red": np.asarray([16_777_217, 16_777_218, 16_777_221, 16_777_225],
                           dtype=np.float64),
        "nir": np.asarray([16_777_219, 16_777_220, 16_777_223, 16_777_229],
                           dtype=np.float64),
    }}
    array = ee.ImageCollection("sentinel-2-l2a").first().toArray().toArray(1)
    reduced = array.arrayReduce(ee.Reducer.minMax(), [0], 1)
    graph, values, names = compile_raster(
        ee, reduced.arrayFlatten([["single"], ["minimum", "maximum"]]), local,
    )
    assert names == ["single_minimum", "single_maximum"]
    np.testing.assert_array_equal(
        values,
        [[16_777_217, 16_777_218, 16_777_221, 16_777_225],
         [16_777_219, 16_777_220, 16_777_223, 16_777_229]],
    )

    process_graph = graph["process_graph"]
    reductions = [node for node in process_graph.values()
                  if node["process_id"] == "local_ee_reduce_bands"]
    assert [node["arguments"]["reducer"] for node in reductions] == ["min", "max"]
    for node in reductions:
        ancestry = process_ancestry(graph, node["arguments"]["data"])
        process_ids = {process_graph[key]["process_id"] for key in ancestry}
        assert "local_ee_to_double" in process_ids
        assert "load_collection" in process_ids
        assert "apply" not in process_ids


def test_reducing_multiple_axes_keeps_singletons_and_field_order(ee, local):
    array = mixed_and_raw_columns(ee).toArray(2)
    reduced = array.arrayReduce(ee.Reducer.minMax(), [0, 1], 2)
    _, values, names = compile_raster(
        ee,
        reduced.arrayFlatten([
            ["reduced"], ["column"], ["minimum", "maximum"],
        ]),
        local,
    )
    assert names == [
        "reduced_column_minimum", "reduced_column_maximum",
    ]
    np.testing.assert_allclose(
        values, [[1, np.nan, np.nan, 5], [15, np.nan, np.nan, 35]],
        equal_nan=True,
    )


def test_first_last_preserve_reduction_axis_and_output_order(ee, local):
    reducer = ee.Reducer.first().combine(
        ee.Reducer.last(), sharedInputs=True,
    )
    array = matrix(ee).toArray(2)
    reduced = array.arrayReduce(reducer, [0], 2)
    graph, values, names = compile_raster(
        ee,
        reduced.arrayFlatten([["row"], ["column"], ["first", "last"]]),
        local,
    )
    assert names == ["row_column_first", "row_column_last"]
    np.testing.assert_allclose(
        values,
        [[7, np.nan, np.nan, 15], [15, np.nan, np.nan, 35]],
        equal_nan=True,
    )
    reducers = [node["arguments"]["reducer"]
                for node in graph["process_graph"].values()
                if node["process_id"] == "local_ee_reduce_bands"]
    assert reducers == ["first", "last"]


def test_first_last_results_keep_array_wide_mask_when_one_cell_is_valid(ee, local):
    image = ee.ImageCollection("sentinel-2-l2a").first()
    array = image.select(["red"]).toArray().arrayCat(
        image.select(["nir"]).toArray(), 0,
    )
    for reducer_name, expected in [
        ("first", [1.0, np.nan, np.nan, 5.0]),
        ("last", [3.0, np.nan, np.nan, 5.0]),
    ]:
        reduced = array.arrayReduce(getattr(ee.Reducer, reducer_name)(), [0])
        _, values, names = compile_raster(
            ee, reduced.arrayFlatten([["selected"]]), local,
        )
        assert names == ["selected"]
        np.testing.assert_allclose(values, [expected], equal_nan=True)


def test_shared_input_combine_and_set_outputs_use_actual_fields(ee, local):
    reducer = ee.Reducer.sum().combine(
        ee.Reducer.product(), outputPrefix="combined_", sharedInputs=True,
    ).setOutputs(["total", "joined_product"])
    expression = matrix(ee).toArray(2).arrayReduce(reducer, [0], 2)
    graph, values, names = compile_raster(
        ee, expression.arrayFlatten([["row"], ["column"], ["total", "product"]]), local,
    )
    assert names == ["row_column_total", "row_column_product"]
    np.testing.assert_allclose(
        values,
        [[22, np.nan, np.nan, 50], [105, np.nan, np.nan, 525]],
        equal_nan=True,
    )
    reducers = [node["arguments"]["reducer"]
                for node in graph["process_graph"].values()
                if node["process_id"] == "local_ee_reduce_bands"]
    assert reducers == ["sum", "product"]


def test_sample_variance_with_a_single_array_sample_is_nodata(ee, local):
    one_sample = matrix(ee).arraySlice(0, 0, 1)
    reduced = one_sample.arrayReduce(ee.Reducer.sampleVariance(), [0])
    _, values, names = compile_raster(
        ee, reduced.arrayFlatten([["row"], ["column"]]), local,
    )
    assert names == ["row_column"]
    np.testing.assert_array_equal(np.isnan(values), np.ones((1, 4), dtype=bool))


def test_set_outputs_can_rename_minmax_and_drop_a_field(ee, local):
    renamed = ee.Reducer.minMax().setOutputs(["low", "high"])
    array = matrix(ee).toArray(2)
    _, values, names = compile_raster(
        ee, array.arrayReduce(renamed, [0], 2).arrayFlatten(
            [["row"], ["column"], ["low", "high"]],
        ), local,
    )
    assert names == ["row_column_low", "row_column_high"]
    np.testing.assert_allclose(
        values,
        [[7, np.nan, np.nan, 15], [15, np.nan, np.nan, 35]],
        equal_nan=True,
    )

    only_high = ee.Reducer.minMax().setOutputs([None, "high"])
    _, selected, selected_names = compile_raster(
        ee, array.arrayReduce(only_high, [0], 2).arrayFlatten(
            [["row"], ["column"], ["high"]],
        ), local,
    )
    assert selected_names == ["row_column_high"]
    np.testing.assert_allclose(selected, [[15, np.nan, np.nan, 35]], equal_nan=True)


def test_legacy_reducers_keep_callback_precision_and_accept_single_field_axis(ee, local):
    value = matrix(ee)
    legacy = value.arrayReduce(ee.Reducer.sampleStdDev(), [0])
    graph, values, names = compile_raster(
        ee, legacy.arrayFlatten([["row"], ["column"]]), local,
    )
    assert names == ["row_column"]
    np.testing.assert_allclose(
        values,
        [[np.sqrt(32), np.nan, np.nan, np.sqrt(200)]],
        equal_nan=True,
    )
    assert not any(node["process_id"] == "local_ee_reduce_bands"
                   for node in graph["process_graph"].values())

    explicit_field = value.toArray(2).arrayReduce(ee.Reducer.sum(), [0], 2)
    graph, explicit, names = compile_raster(
        ee, explicit_field.arrayFlatten([["row"], ["column"], ["sum"]]), local,
    )
    assert names == ["row_column_sum"]
    np.testing.assert_allclose(explicit, [[22, np.nan, np.nan, 50]], equal_nan=True)
    assert not any(node["process_id"] == "local_ee_reduce_bands"
                   for node in graph["process_graph"].values())


@pytest.mark.parametrize("make_expression,reason", [
    (lambda ee, value: value.arrayReduce(ee.Reducer.minMax(), [0]), "fieldAxis"),
    (lambda ee, value: value.arrayReduce(ee.Reducer.sum(), [0], 0), "overlap"),
    (lambda ee, value: value.arrayReduce(ee.Reducer.sum(), [1], 0), "length 1"),
    (lambda ee, value: value.arrayReduce(ee.Reducer.sum(), [0], 2), "outside"),
    (lambda ee, value: value.arrayReduce(ee.Reducer.sum(), [0], -1), ">= 0"),
    (lambda ee, value: value.arrayReduce(ee.Reducer.sum(), [0], True), "integer"),
])
def test_invalid_field_axis_layouts_reject(ee, local, make_expression, reason):
    with pytest.raises(UnsupportedEEError, match=reason):
        expression = make_expression(ee, matrix(ee))
        compile_raster(ee, expression.arrayFlatten([["row"], ["column"]]), local)


def test_nonshared_and_nonnumeric_reducers_reject(ee, local):
    matrix_image = matrix(ee).toArray(2)
    reducers = [
        ee.Reducer.mean().combine(ee.Reducer.product(), sharedInputs=False),
        ee.Reducer.frequencyHistogram(),
        ee.Reducer.linearRegression(1),
    ]
    for reducer in reducers:
        with pytest.raises(UnsupportedEEError, match="numeric|input|single"):
            expression = matrix_image.arrayReduce(reducer, [0], 2)
            compile_raster(
                ee, expression.arrayFlatten([["row"], ["column"], ["out"]]), local,
            )
