"""Raster linearFit semantics through the pinned SDK and local graph compiler."""
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point, shape

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


@pytest.fixture
def local():
    catalog = [{
        "id": "sentinel-2-l2a",
        "cube:dimensions": {"bands": {"values": ["x", "y"]}},
    }]
    ids = ["a", "b", "c", "d"]
    footprints = {
        item_id: {
            "type": "Polygon",
            "coordinates": [[[0, 0], [right, 0], [right, 1], [0, 1], [0, 0]]],
        }
        for item_id, right in zip(ids, [8, 8, 8, 9])
    }
    items = {"sentinel-2-l2a": [
        {
            "id": item_id,
            "bbox": [0, 0, 8 if item_id != "d" else 9, 1],
            "geometry": footprints[item_id],
            # Distinct observations can share one acquisition timestamp.
            "properties": {"system:index": item_id, "system:time_start": 1000},
        }
        for item_id in ids
    ]}

    # Rows are observations a, b, c and d; columns are independent pixels.
    # Pixels 0/1 have positive/negative slopes; 2 stresses centered arithmetic;
    # 3 has two complete pairs despite different x/y missing rows; 4 has one
    # complete pair; 5 has constant x; 6 has constant y; 7 is nonlinear so a
    # repeated explicit observation changes the fitted coefficients. Pixel 8
    # has finite values in all four arrays, but only frame d covers its center.
    x = np.array([
        [0, 0, 9998.5, np.nan, 0, 4, 0, 0, 0],
        [1, 1, 9999.5, 1, np.nan, 4, 1, 1, 1],
        [2, 2, 10000.5, 2, np.nan, 4, 2, 2, 2],
        [3, 3, 10001.5, 3, np.nan, 4, 3, 3, 3],
    ], dtype=np.float64)
    y = np.array([
        [1, 6, 999995.5, 1, 1, 1, 7, 0, 1],
        [3, 4, 999998.5, 3, np.nan, 2, 7, 1, 3],
        [5, 2, 1000001.5, np.nan, np.nan, 5, 7, 4, 5],
        [7, 0, 1000004.5, 7, np.nan, 8, 7, 2, 7],
    ], dtype=np.float64)
    arrays = {
        item_id: {"x": x[index], "y": y[index]}
        for index, item_id in enumerate(ids)
    }
    pixel_centers = np.array([[index + 0.5, 0.5] for index in range(9)])
    return catalog, items, arrays, pixel_centers, footprints


def encoded(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_value(ee, value, local):
    return compile_expression(encoded(ee, value), local[0], local[1])


def compile_raster(ee, value, local, arrays):
    result = compile_value(ee, value, local)
    assert result["kind"] == "image"
    validate(result["process_graph"])
    data, names, timed = evaluate_graph(
        result, arrays, grid=local[3], source_geometries=local[4])
    assert timed is False
    return result, data, names


def find_invocation(expression, function_name):
    if isinstance(expression, dict):
        if expression.get("functionName") == function_name:
            return expression
        for value in expression.values():
            found = find_invocation(value, function_name)
            if found is not None:
                return found
    elif isinstance(expression, (list, tuple)):
        for value in expression:
            found = find_invocation(value, function_name)
            if found is not None:
                return found
    return None


def test_collection_fit_keeps_same_day_observations_and_matches_closed_form(ee, local):
    collection = ee.ImageCollection("sentinel-2-l2a")
    fit = collection.reduce(ee.Reducer.linearFit())
    result, data, names = compile_raster(ee, fit, local, local[2])

    assert names == ["scale", "offset"]
    assert result["bands"] == names
    assert result["properties"] == {}
    assert set(result["source_item_ids"]) == {"a", "b", "c", "d"}
    for item_id in ("a", "b", "c"):
        geometry = shape(local[4][item_id])
        assert all(geometry.covers(Point(*center)) for center in local[3][:8])
        assert not geometry.covers(Point(*local[3][8]))
    assert shape(local[4]["d"]).covers(Point(*local[3][8]))
    # These are closed-form lines, including a negative slope and a large x/y
    # offset whose centered covariance is still exactly 3 * 5.
    np.testing.assert_allclose(data[0, [0, 1, 2, 3, 6]], [2, -2, 3, 2, 0],
                               rtol=2e-6, atol=2e-6)
    np.testing.assert_allclose(data[1, [0, 1, 2, 3, 6]], [1, 6, 970000, 1, 7],
                               rtol=2e-6, atol=2e-4)
    # Row deletion removes an observation when either input band is NoData;
    # pixel 8 has finite source values but only one spatially covering frame.
    assert np.isnan(data[:, [4, 5, 8]]).all()
    assert all(np.isfinite(local[2][item_id][band][8])
               for item_id in ("a", "b", "c", "d") for band in ("x", "y"))
    assert np.isfinite(data[:, 7]).all()
    np.testing.assert_allclose(data[:, 7], [0.9, 0.4], rtol=2e-6, atol=2e-6)


def test_from_images_preserves_explicit_repetition_and_union_footprint(ee, local):
    images = [ee.Image(item_id) for item_id in ["a", "b", "c", "d", "a"]]
    collection = ee.ImageCollection.fromImages(images)
    fit = collection.reduce(ee.Reducer.linearFit())
    result, data, names = compile_raster(ee, fit, local, local[2])

    assert names == ["scale", "offset"]
    assert result["properties"] == {}
    assert set(result["source_item_ids"]) == {"a", "b", "c", "d"}
    # In pixel 7, distinct rows give 9/10 and 2/5. Repeating a's (0, 0)
    # observation changes the fit to 33/34 and 4/17.
    np.testing.assert_allclose(data[:, 7], [33 / 34, 4 / 17], rtol=2e-6, atol=2e-6)

    geometry = compile_value(ee, fit.geometry(), local)["value"]
    footprint = shape(geometry)
    assert footprint.bounds == (0.0, 0.0, 9.0, 1.0)
    assert footprint.area == 9.0


def test_eight_frame_limit_is_inclusive(ee, local):
    images = [ee.Image(item_id) for item_id in ["a", "b", "c", "d"] * 2]
    fit = ee.ImageCollection.fromImages(images).reduce(ee.Reducer.linearFit())
    _, data, names = compile_raster(ee, fit, local, local[2])
    assert names == ["scale", "offset"]
    np.testing.assert_allclose(data[:, 0], [2, 1], rtol=2e-6, atol=2e-6)


def test_one_frame_compiles_but_insufficient_or_degenerate_pixels_are_masked(ee, local):
    fit = ee.ImageCollection.fromImages([ee.Image("a")]).reduce(ee.Reducer.linearFit())
    _, data, names = compile_raster(ee, fit, local, local[2])
    assert names == ["scale", "offset"]
    assert np.isnan(data).all()


def test_empty_input_is_rejected(ee, local):
    # No coefficient can be constructed from an empty sequence.
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, ee.ImageCollection.fromImages([]).reduce(
            ee.Reducer.linearFit()), local)


def test_schema_order_frame_limit_and_reducer_errors_are_explicit(ee, local):
    base = ee.Image("a").select(["x", "y"])
    valid = ee.Image("b").select(["x", "y"])
    invalid_frames = [
        ee.ImageCollection.fromImages([base.select("x"), valid]),
        ee.ImageCollection.fromImages([base, valid.select(["y", "x"])]),
        ee.ImageCollection.fromImages([base, valid.select(["x", "y"], ["x", "z"])]),
        ee.ImageCollection.fromImages([base, valid.select(["x", "y"]).addBands(
            valid.select("x").rename("extra"))]),
        ee.ImageCollection.fromImages([base.toArray(), valid.toArray()]),
    ]
    for collection in invalid_frames:
        with pytest.raises(UnsupportedEEError):
            compile_value(ee, collection.reduce(ee.Reducer.linearFit()), local)

    too_many = ee.ImageCollection.fromImages([ee.Image("a")] * 9)
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, too_many.reduce(ee.Reducer.linearFit()), local)
    regression = ee.ImageCollection("sentinel-2-l2a").reduce(
        ee.Reducer.linearRegression(numX=1, numY=1))
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, regression, local)


def test_parallel_scale_unknown_arguments_and_explicit_float64_reject(ee, local):
    collection = ee.ImageCollection("sentinel-2-l2a")
    _, default_scale, _ = compile_raster(
        ee, collection.reduce(ee.Reducer.linearFit(), parallelScale=1), local, local[2])
    np.testing.assert_allclose(default_scale[0, 0], 2, rtol=2e-6, atol=2e-6)
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, collection.reduce(ee.Reducer.linearFit(), parallelScale=2), local)

    expression = encoded(ee, collection.reduce(ee.Reducer.linearFit()))
    invocation = find_invocation(expression, "ImageCollection.reduce")
    assert invocation is not None
    invocation["arguments"]["ignored"] = 7
    with pytest.raises(UnsupportedEEError):
        compile_expression(expression, local[0], local[1])

    expression = encoded(ee, collection.reduce(ee.Reducer.linearFit()))
    invocation = find_invocation(expression, "Reducer.linearFit")
    assert invocation is not None
    invocation["arguments"]["ignored"] = 7
    with pytest.raises(UnsupportedEEError):
        compile_expression(expression, local[0], local[1])

    double = ee.ImageCollection.fromImages([
        ee.Image("a").toDouble(), ee.Image("b").toDouble(),
    ]).reduce(ee.Reducer.linearFit())
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, double, local)


def test_compilation_work_and_process_graph_node_limits_remain_bounded(ee, local):
    # The serialized payload stays below the 1 MB input cap while argument
    # traversal alone exceeds the existing 50,000-step compiler budget.
    expression = encoded(ee, ee.ImageCollection("sentinel-2-l2a").reduce(
        ee.Reducer.linearFit()))
    invocation = find_invocation(expression, "ImageCollection.reduce")
    assert invocation is not None
    invocation["arguments"]["ignored"] = [[0] * 9_000 for _ in range(6)]
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        compile_expression(expression, local[0], local[1])

    # Four shallow two-band arithmetic chains exceed the process graph's
    # 500-node boundary while keeping decoder traversal below its work limit.
    images = []
    for index, item_id in enumerate(("a", "b", "c", "d")):
        image = ee.Image(item_id)
        for _ in range(20):
            image = image.add(index + 1)
        images.append(image)
    sequence = ee.ImageCollection.fromImages(images)
    with pytest.raises(UnsupportedEEError, match="500 nodes"):
        compile_value(ee, sequence.reduce(ee.Reducer.linearFit()), local)
