"""Per-pixel Image.matrixSolve through the pinned SDK and local compiler."""
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
DESIGN = [[1, 0], [1, 1], [1, 2]]
OUTPUT_LABELS = [["intercept", "slope"], ["rhs"]]


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
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [4, 0], [4, 1], [0, 1], [0, 0]]],
    }
    catalog = [{
        "id": "sentinel-2-l2a",
        "cube:dimensions": {"bands": {"values": ["y0", "y1", "y2"]}},
    }]
    items = {"sentinel-2-l2a": [
        {"id": item_id, "bbox": [0, 0, 4, 1], "geometry": geometry,
         "properties": {"system:index": item_id, "system:time_start": timestamp}}
        for item_id, timestamp in (("a", 1000), ("b", 2000))
    ]}
    arrays = {
        "a": {
            "y0": np.array([1, -2, 3, 0, 5], dtype=float),
            "y1": np.array([3, -5, np.nan, 5, 9], dtype=float),
            "y2": np.array([5, -8, 9, 12, 13], dtype=float),
        },
        "b": {
            "y0": np.array([10, 20, 30, 40, 50], dtype=float),
            "y1": np.array([12, 23, 34, 45, 56], dtype=float),
            "y2": np.array([14, 26, 38, 50, 62], dtype=float),
        },
    }
    grid = np.array([[index + 0.5, 0.5] for index in range(5)])
    return {
        "catalog": catalog,
        "items": items,
        "arrays": arrays,
        "grid": grid,
        "geometries": {"a": geometry, "b": geometry},
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


def first_image(ee):
    return ee.ImageCollection("sentinel-2-l2a").first()


def design_image(ee, matrix=DESIGN):
    return ee.Image.constant(ee.Array(matrix)).toFloat().set("design_tag", "left")


def response_column(ee, image=None, bands=("y0", "y1", "y2")):
    source = first_image(ee) if image is None else image
    return source.select(list(bands)).toFloat().toArray().toArray(axis=1)


def fractions_for_three_samples(values):
    """Closed-form OLS for rows at x=0,1,2, independent of the solver."""
    y0, y1, y2 = map(Fraction, values)
    return (Fraction(5 * y0 + 2 * y1 - y2, 6), Fraction(y2 - y0, 2))


def test_sdk_matrix_solve_fits_a_nonorthogonal_design_with_whole_array_mask_and_metadata(ee, local):
    design_values = [[1, 0], [1, 1], [1, 2]]
    rhs_values = {key: values.copy() for key, values in local["arrays"]["a"].items()}
    matrix = design_image(ee, design_values)
    response = response_column(ee)
    fit = matrix.matrixSolve(response)
    flattened = fit.arrayFlatten(OUTPUT_LABELS)
    encoded = encode(ee, flattened)
    calls = [node for _, node in encoded["scope"]
             if isinstance(node, dict) and node.get("type") == "Invocation"]
    solve = [node for node in calls if node.get("functionName") == "Image.matrixSolve"]
    assert len(solve) == 1
    assert set(solve[0]["arguments"]) == {"image1", "image2"}
    assert sum(node.get("functionName") == "Image.toFloat" for node in calls) >= 2

    result, actual, bands = compile_raster(ee, flattened, local)
    assert bands == ["intercept_rhs", "slope_rhs"]
    assert result["properties"] == {"design_tag": "left"}
    assert result["source_item_ids"] == ["a"]

    expected = np.full((2, 5), np.nan)
    for pixel in (0, 1, 3):
        if pixel == 1:
            values = [-2, -5, -8]
        elif pixel == 3:
            values = [0, 5, 12]
        else:
            values = [1, 3, 5]
        expected[:, pixel] = [float(value) for value in fractions_for_three_samples(values)]
    np.testing.assert_allclose(actual, expected, atol=2e-6, rtol=2e-7, equal_nan=True)
    # A missing source row masks the complete solve at pixel 2; the sample
    # center at x=4.5 lies outside the sole source footprint.
    assert np.isnan(actual[:, 2]).all()
    assert np.isnan(actual[:, 4]).all()
    for name, before in rhs_values.items():
        np.testing.assert_array_equal(local["arrays"]["a"][name], before)
    assert design_values == DESIGN


def test_multiple_rhs_columns_keep_row_major_order_and_share_the_response_mask(ee, local):
    source = response_column(ee)
    transform = ee.Image.constant(ee.Array([[1, -2]])).toFloat()
    two_responses = source.matrixMultiply(transform).toFloat()
    labels = [["intercept", "slope"], ["original", "negative_double"]]
    value = design_image(ee).matrixSolve(two_responses).arrayFlatten(labels)
    result, actual, names = compile_raster(ee, value, local)

    assert names == [
        "intercept_original", "intercept_negative_double",
        "slope_original", "slope_negative_double",
    ]
    assert result["source_item_ids"] == ["a"]
    expected_first = np.array([
        [1, -2, np.nan, -1 / 3, np.nan],
        [-2, 4, np.nan, 2 / 3, np.nan],
        [2, -3, np.nan, 6, np.nan],
        [-4, 6, np.nan, -12, np.nan],
    ], dtype=float)
    np.testing.assert_allclose(actual, expected_first, atol=2e-6, rtol=2e-7, equal_nan=True)


def test_explicit_double_source_can_be_narrowed_at_the_array_boundary(ee, local):
    source = first_image(ee).select(["y0", "y1", "y2"]).toDouble()
    narrowed = source.toArray().toArray(axis=1).toFloat()
    flattened = design_image(ee).matrixSolve(narrowed).arrayFlatten(OUTPUT_LABELS)
    expression = encode(ee, flattened)
    names = [node.get("functionName") for _, node in expression["scope"]
             if isinstance(node, dict) and node.get("type") == "Invocation"]
    assert "Image.toDouble" in names and names.count("Image.toFloat") >= 2

    _, actual, _ = compile_raster(ee, flattened, local)
    expected = np.array([[1, -2, np.nan, -1 / 3, np.nan],
                         [2, -3, np.nan, 6, np.nan]])
    np.testing.assert_allclose(actual, expected, atol=2e-6, equal_nan=True)


def test_float32_design_rounding_is_applied_before_the_least_squares_solve(ee, local):
    local["arrays"]["a"]["y0"] = np.array([2**24, 2**25, 3 * 2**24, 4 * 2**24, 5 * 2**24],
                                           dtype=float)
    source = first_image(ee).select(["y0"]).toFloat().toArray().toArray(axis=1)
    design = ee.Image.constant(ee.Array([[16777217]])).toFloat()
    output = design.matrixSolve(source).arrayFlatten([["scale"], ["rhs"]])
    _, actual, names = compile_raster(ee, output, local)

    assert names == ["scale_rhs"]
    rounded_design = float(np.float32(16777217))
    expected = np.array([[2**24 / rounded_design, 2**25 / rounded_design,
                          3 * 2**24 / rounded_design, 4 * 2**24 / rounded_design,
                          np.nan]])
    np.testing.assert_allclose(actual, expected, atol=1e-7, rtol=1e-7, equal_nan=True)
    assert rounded_design == 16777216.0


def test_real_max_shape_multirhs_graph_respects_the_existing_500_node_cap(ee, local):
    names = [f"row_{index}" for index in range(8)]
    catalog = [{"id": "sentinel-2-l2a",
                "cube:dimensions": {"bands": {"values": names}}}]
    geometry = local["geometries"]["a"]
    items = {"sentinel-2-l2a": [{
        "id": "wide", "bbox": [0, 0, 4, 1], "geometry": geometry,
        "properties": {"system:index": "wide", "system:time_start": 1000},
    }]}

    # The first four rows are an identity basis. The remaining rows provide
    # independent checks on the four columns without introducing conditioning.
    design = np.array([
        [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1],
        [1, 1, 1, 1], [1, -1, 1, -1], [1, 1, -1, -1], [1, -1, -1, 1],
    ], dtype=float)
    beta = np.array([1, -2, 3, 4], dtype=float)
    sample_scale = np.array([1, 2, -1, 0.5, 1], dtype=float)
    row_values = np.outer(design @ beta, sample_scale)
    wide_local = {
        "catalog": catalog,
        "items": items,
        "arrays": {"wide": {name: row_values[index]
                            for index, name in enumerate(names)}},
        "grid": local["grid"],
        "geometries": {"wide": geometry},
    }

    first = ee.ImageCollection("sentinel-2-l2a").first()
    vector = first.select(names).toFloat().toArray().toArray(axis=1)
    scales = ee.Image.constant(ee.Array([[1, 2, -1, 0.5]])).toFloat()
    rhs = vector.matrixMultiply(scales).toFloat()
    labels = [[f"beta_{index}" for index in range(4)],
              ["y", "twice_y", "negative_y", "half_y"]]
    result_image = (ee.Image.constant(ee.Array(design.tolist())).toFloat()
                    .matrixSolve(rhs).arrayFlatten(labels))

    # These dimensions and all 64 input cells are valid, but this real
    # per-cell callback graph exceeds the preserved 500-node limit.
    with pytest.raises(UnsupportedEEError, match="500 nodes"):
        compile_value(ee, result_image, wide_local)


def test_same_solver_keeps_each_mapped_image_frame_before_time_reduction(ee, local):
    design = design_image(ee)

    def solve_frame(image):
        return (design.matrixSolve(response_column(ee, image=image))
                .arrayFlatten(OUTPUT_LABELS))

    solved = ee.ImageCollection("sentinel-2-l2a").limit(2).map(solve_frame)
    mean = solved.mean()
    result, actual, names = compile_raster(ee, mean, local)

    assert names == ["intercept_rhs", "slope_rhs"]
    assert result["source_item_ids"] == ["a", "b"]
    expected = np.array([
        [5.5, 9.0, 30.0, float(Fraction(119, 6)), np.nan],
        [2.0, 0.0, 4.0, 5.5, np.nan],
    ])
    np.testing.assert_allclose(actual, expected, atol=3e-6, rtol=3e-7, equal_nan=True)
