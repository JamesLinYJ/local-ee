"""Synthetic raster data and SDK/NumPy helpers for regression tests."""
from pathlib import Path

import numpy as np
from shapely.geometry import Point, shape

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
# This accepted alias is only used by the local source resolver. All fixture
# metadata, geometries, and per-band values are synthetic; no catalog data is read.
COLLECTION_ID = "sentinel-2-l2a"
FRAME_IDS = tuple("abcdef")
RESPONSES = ("y0", "y1", "y2", "y3")
GRID = np.array([
    [0.5, 0.5], [1.5, 0.5], [2.5, 0.5], [3.5, 0.5], [5.5, 0.5], [4.5, 0.5],
])


def make_ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def make_local():
    def rectangle(east):
        return {"type": "Polygon", "coordinates": [[[0, 0], [east, 0], [east, 1],
                [0, 1], [0, 0]]]}

    geometries = {frame: rectangle(5 if frame != "f" else 6) for frame in FRAME_IDS}
    catalog = [{"id": COLLECTION_ID, "cube:dimensions": {"bands": {
        "values": ["x", "one_like", *RESPONSES]}}}]
    items = {COLLECTION_ID: [{
        "id": frame, "bbox": [0, 0, 5 if frame != "f" else 6, 1],
        "geometry": geometries[frame],
        # All observations share one time; identity and repetition still matter.
        "properties": {"system:index": frame, "system:time_start": 1000},
    } for frame in FRAME_IDS]}
    # Rows are frames, columns are six grid points. A null in y1/pixel2 removes
    # that observation from the common row set for every response.
    x = np.array([
        [-2, -2, -2, 4, 1, 0], [-1, -1, -1, 4, 2, 0],
        [0, 0, 0, 4, 3, 0], [1, 1, 1, 4, 4, 0],
        [2, 2, 2, 4, 5, 0], [3, 3, 3, 4, 6, 0],
    ], dtype=np.float64)
    values = {
        "y0": [[-1, 1, 3, 1, 0, 1], [1, 3, 4, 2, 1, 3],
               [3, 4, 4, 5, 2, 2], [5, 8, 2, 8, 3, 5],
               [7, 5, 5, 9, 4, 4], [9, 9, 10, 10, 5, 0]],
        "y1": [[-2, 2, 1, 2, 7, 3], [-1.5, -1, None, 4, 6, 1],
               [-1, 1, 2, 1, 5, 4], [-.5, 3, -2, 8, 4, 2],
               [0, 8, 6, 3, 3, 6], [.5, 2, 3, 0, 2, 5]],
        "y2": [[0, 3, 1, 0, 1, 8], [1, 0, 4, 0, 2, 4],
               [4, 1, 0, 2, 3, 1], [9, 4, 3, 4, 4, 5],
               [16, 2, -1, 6, 5, 3], [25, 2, 2, 8, 6, 2]],
        "y3": [[-2, 5, 0, 9, 2, 0], [0, 4, 0, 6, 4, 3],
               [3, 3, 1, 5, 6, 2], [3, 2, 5, 2, 8, 4],
               [1, 1, 3, 1, 10, 7], [8, 0, 1, 7, 12, 1]],
    }
    arrays = {
        frame: {"x": x[index], "one_like": np.ones(len(GRID)),
                **{name: np.array([np.nan if v is None else v for v in values[name][index]])
                   for name in RESPONSES}}
        for index, frame in enumerate(FRAME_IDS)
    }
    return {
        "catalog": catalog,
        "items": items,
        "arrays": arrays,
        "grid": GRID,
        "geometries": geometries,
    }


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_value(ee, value, local):
    return compile_expression(encode(ee, value), local["catalog"], local["items"])


def compile_raster(ee, value, local):
    result = compile_value(ee, value, local)
    assert result["kind"] == "image"
    validate(result["process_graph"])
    data, names, timed = evaluate_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries=local["geometries"],
    )
    assert timed is False
    return result, data, names


def frame(ee, item_id, num_x, num_y, intercept=1):
    image = ee.Image(item_id)
    responses = [f"y{index}" for index in range(num_y)]
    if num_x == 1:
        return image.select(["x", *responses])
    destination = image.select(["x"])
    literal = ee.Image.constant(intercept).rename("intercept").toFloat()
    with_intercept = destination.addBands(literal)
    with_responses = with_intercept.addBands(image.select(responses))
    return with_responses.select(["intercept", "x", *responses])


def source_collection(ee, ids, num_x, num_y, intercept=1):
    images = [frame(ee, item_id, num_x, num_y, intercept) for item_id in ids]
    return ee.ImageCollection.fromImages(images)


def bundle(ee, ids=FRAME_IDS, num_x=2, num_y=2, *, intercept=1, parallel_scale=1):
    collection = source_collection(ee, ids, num_x, num_y, intercept)
    reducer = ee.Reducer.linearRegression(numX=num_x, numY=num_y)
    if parallel_scale is None:
        return collection.reduce(reducer)
    return collection.reduce(reducer, parallelScale=parallel_scale)


def flattened(ee, regression, num_x, num_y):
    predictor_labels = ["through_origin"] if num_x == 1 else ["intercept", "slope"]
    response_labels = [f"y{index}" for index in range(num_y)]
    coefficients = regression.select("coefficients").arrayFlatten(
        [predictor_labels, response_labels]
    )
    residuals = regression.select("residuals").arrayFlatten([response_labels])
    return coefficients, residuals


def complete_rows(local, ids, pixel, num_x, num_y):
    rows = []
    for item_id in ids:
        geometry = shape(local["geometries"][item_id])
        if not geometry.covers(Point(*local["grid"][pixel])):
            continue
        values = local["arrays"][item_id]
        vector = [values["x"][pixel]] + [values[f"y{i}"][pixel] for i in range(num_y)]
        if not np.isfinite(vector).all():
            continue
        rows.append(([1.0, vector[0]] if num_x == 2 else [vector[0]]) + vector[1:])
    return np.asarray(rows, dtype=np.float64).reshape((-1, num_x + num_y))


def numpy_reference(local, ids, num_x, num_y):
    coefficients = np.full((num_x, num_y, len(GRID)), np.nan, dtype=np.float64)
    residuals = np.full((num_y, len(GRID)), np.nan, dtype=np.float64)
    for pixel in range(len(GRID)):
        rows = complete_rows(local, ids, pixel, num_x, num_y)
        n = len(rows)
        if num_x == 1:
            valid = n > 1 and np.sum(rows[:, 0] ** 2) > 0
        else:
            valid = n > 2 and np.var(rows[:, 1]) > 0
        if not valid:
            continue
        design, response = rows[:, :num_x], rows[:, num_x:]
        beta, _, rank, _ = np.linalg.lstsq(design, response, rcond=None)
        if rank < num_x:
            continue
        error = response - design @ beta
        coefficients[:, :, pixel] = beta
        # Earth Engine's documented regression residuals are RMS, divisor n.
        residuals[:, pixel] = np.sqrt(np.mean(error ** 2, axis=0))
    return coefficients.reshape((num_x * num_y, len(GRID))), residuals


def checked_fit(ee, regression, local, num_x, num_y, ids):
    coefficients, residuals = flattened(ee, regression, num_x, num_y)
    coefficient_result, coefficient_data, coefficient_names = compile_raster(
        ee, coefficients, local
    )
    residual_result, residual_data, residual_names = compile_raster(ee, residuals, local)
    expected_coefficients, expected_residuals = numpy_reference(local, ids, num_x, num_y)
    np.testing.assert_allclose(coefficient_data, expected_coefficients,
                               rtol=2e-5, atol=2e-5, equal_nan=True)
    np.testing.assert_allclose(residual_data, expected_residuals,
                               rtol=2e-5, atol=2e-5, equal_nan=True)
    return (coefficient_result, coefficient_data, coefficient_names,
            residual_result, residual_data, residual_names)


def invocation(value, name):
    if isinstance(value, dict):
        if value.get("type") == "Invocation" and value.get("functionName") == name:
            return value
        for child in value.values():
            found = invocation(child, name)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for child in value:
            found = invocation(child, name)
            if found is not None:
                return found
    return None
