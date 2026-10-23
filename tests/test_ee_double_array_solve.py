"""Focused synthetic graph checks for explicit Double raster-array solves."""
from fractions import Fraction
import json
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, const
from gee.compat.earthengine.raster_array_core import wrap_array_image
from gee.compat.earthengine.raster_matrix_solve import invoke_raster_matrix
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard

from ee_float64_graph_reference import evaluate_float64_graph


ROOT = Path(__file__).resolve().parents[1]
_ROW_NAMES = [f"y{index}" for index in range(8)]


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
        "coordinates": [[[0, 0], [5, 0], [5, 1], [0, 1], [0, 0]]],
    }
    catalog = [{
        "id": "sentinel-2-l2a",
        "cube:dimensions": {"bands": {"values": _ROW_NAMES}},
    }]
    item_id = "double-array-source"
    base = [2**40 + 0.25, 2**40 + 0.375, 2**40 + 0.5,
            2**40 + 0.625, 2**40 + 0.75, 2**40 + 0.875]
    slope = [0.125, -0.25, 0.5, 0.75, -0.125, 0.25]
    arrays = {item_id: {
        name: np.array([base[column] + slope[column] * row
                        for column in range(len(base))], dtype=np.float64)
        for row, name in enumerate(_ROW_NAMES)
    }}
    arrays[item_id]["y2"][3] = np.nan
    items = {"sentinel-2-l2a": [{
        "id": item_id,
        "bbox": [0, 0, 5, 1],
        "geometry": geometry,
        "properties": {"system:index": item_id, "system:time_start": 1000},
    }]}
    grid = np.array([[index + 0.5, 0.5] for index in range(6)])
    return {
        "catalog": catalog,
        "items": items,
        "arrays": arrays,
        "grid": grid,
        "geometries": {item_id: geometry},
        "item_id": item_id,
    }


def _encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def _compile_value(ee, value, local):
    return compile_expression(
        _encode(ee, value), local["catalog"], local["items"],
    )


def _compile_raster(ee, value, local):
    result = _compile_value(ee, value, local)
    assert result["kind"] == "image"
    validate(result["process_graph"])
    data, names, timed = evaluate_float64_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries=local["geometries"],
    )
    assert timed is False
    return result, data, names


def _first_image(ee):
    return ee.ImageCollection("sentinel-2-l2a").first()


def _design(ee, values, precision="double"):
    image = ee.Image.constant(ee.Array(values)).set("design_tag", "left")
    return image.toDouble() if precision == "double" else image.toFloat()


def _response(ee, row_count, precision="double"):
    source = _first_image(ee).select(_ROW_NAMES[:row_count])
    array = source.toArray()
    array = array.toDouble() if precision == "double" else array.toFloat()
    return array.toArray(axis=1)


def _fraction_fit(values):
    """Exact OLS reference for x=0..m-1 over the supplied binary64 samples."""
    y = [Fraction.from_float(float(value)) for value in values]
    x = list(range(len(y)))
    x_mean = Fraction(sum(x), len(x))
    y_mean = sum(y, Fraction()) / len(y)
    numerator = sum((Fraction(value) - x_mean) * (sample - y_mean)
                    for value, sample in zip(x, y))
    denominator = sum((Fraction(value) - x_mean) ** 2 for value in x)
    beta1 = numerator / denominator
    return y_mean - beta1 * x_mean, beta1


def test_to_double_casts_each_array_cell_and_keeps_shape_mask_name_and_metadata(ee, local):
    source = _first_image(ee).set("source_tag", "kept").select(["y0", "y2"])
    array = source.toArray().rename("double_bundle").toDouble()
    flattened = array.arrayFlatten([["first", "second"]])

    result, actual, names = _compile_raster(ee, flattened, local)

    assert names == ["first", "second"]
    assert result["properties"] == {
        "system:index": local["item_id"],
        "system:time_start": 1000,
        "source_tag": "kept",
    }
    expected = np.stack([
        local["arrays"][local["item_id"]]["y0"],
        local["arrays"][local["item_id"]]["y2"],
    ])
    expected[:, 3] = np.nan  # RasterArrayImage uses one mask for every cell.
    np.testing.assert_array_equal(actual[:, :5], expected[:, :5])
    assert np.isnan(actual[:, 5]).all()  # outside the source footprint
    assert np.isnan(actual[:, 3]).all()  # one invalid array cell masks the whole array


def test_double_matrix_solve_preserves_large_offsets_and_the_shared_array_mask(ee, local):
    design = _design(ee, [[1, 0], [1, 1], [1, 2], [1, 3]])
    response = _response(ee, 4)
    fit = design.matrixSolve(response).arrayFlatten(
        [["intercept", "slope"], ["rhs"]],
    )

    result, actual, names = _compile_raster(ee, fit, local)

    assert names == ["intercept_rhs", "slope_rhs"]
    assert result["properties"] == {"design_tag": "left"}
    assert result["source_item_ids"] == [local["item_id"]]
    expected = np.full((2, 6), np.nan)
    valid_columns = (0, 1, 2, 4)
    for column in valid_columns:
        samples = [local["arrays"][local["item_id"]][f"y{row}"][column]
                   for row in range(4)]
        expected[:, column] = [float(value) for value in _fraction_fit(samples)]
    intercept_error = np.abs(actual[0, list(valid_columns)] - expected[0, list(valid_columns)])
    intercept_ulp = np.spacing(np.abs(expected[0, list(valid_columns)]))
    slope_error = np.abs(actual[1, list(valid_columns)] - expected[1, list(valid_columns)])
    assert np.all(intercept_error <= intercept_ulp)
    assert float(np.max(slope_error)) <= 1e-7
    assert np.isnan(actual[:, 3]).all()
    assert np.isnan(actual[:, 5]).all()


@pytest.mark.parametrize(
    ("left_precision", "right_precision"),
    [("double", "float"), ("float", "double")],
)
def test_matrix_solve_promotes_mixed_explicit_casts_to_double(
        ee, local, left_precision, right_precision):
    for band, values in (("y0", [0.125, 1.125, -2.5, 4.75, 0.5, 3.0]),
                         ("y1", [2.25, -1.5, 3.125, 0.25, -0.75, 5.0])):
        local["arrays"][local["item_id"]][band] = np.asarray(values, dtype=np.float64)
    left = _design(ee, [[1, 0], [0, 1]], left_precision)
    right = _response(ee, 2, right_precision)
    fitted = left.matrixSolve(right).arrayFlatten(
        [["first", "second"], ["rhs"]],
    )

    _result, actual, names = _compile_raster(ee, fitted, local)

    assert names == ["first_rhs", "second_rhs"]
    expected = np.stack([
        np.asarray(local["arrays"][local["item_id"]]["y0"], dtype=np.float64),
        np.asarray(local["arrays"][local["item_id"]]["y1"], dtype=np.float64),
    ])
    if right_precision == "float":
        expected = expected.astype(np.float32).astype(np.float64)
    np.testing.assert_array_equal(actual[:, :5], expected[:, :5])
    assert np.isnan(actual[:, 5]).all()


def test_outer_double_cast_does_not_restore_a_nested_float32_rounding(ee, local):
    local["arrays"][local["item_id"]]["y0"] = np.full(6, 16777216.0)
    design = ee.Image.constant(ee.Array([[16777217]])).toFloat().toDouble()
    response = _response(ee, 1)
    fitted = design.matrixSolve(response).arrayFlatten([["scale"], ["rhs"]])

    _result, actual, _names = _compile_raster(ee, fitted, local)

    np.testing.assert_allclose(actual[0, :5], 1.0, rtol=0, atol=0)
    assert np.isnan(actual[0, 5])


def test_double_rank_cutoff_and_full_rank_boundaries_are_computed_from_float64(ee, local):
    local["arrays"][local["item_id"]]["y0"] = np.full(6, 5.0)
    local["arrays"][local["item_id"]]["y1"] = np.full(6, 5.0 + 2e-8)
    close_design = [[1.0, 1.0], [1.0, 1.0 + 1e-8]]
    fitted = _design(ee, close_design).matrixSolve(
        _response(ee, 2),
    ).arrayFlatten([["intercept", "slope"], ["rhs"]])
    _result, actual, _names = _compile_raster(ee, fitted, local)
    np.testing.assert_allclose(actual[:, :3], [[3.0] * 3, [2.0] * 3],
                               rtol=0, atol=3e-7)

    local["arrays"][local["item_id"]]["y0"] = np.asarray(
        [2, 4, 6, 8, 10, 12], dtype=np.float64,
    )
    local["arrays"][local["item_id"]]["y1"] = np.asarray(
        [3, 1, -1, 5, 7, 9], dtype=np.float64,
    )
    deficient = _design(ee, [[1, 1], [2, 2]]).matrixSolve(
        _response(ee, 2),
    ).arrayFlatten([["first", "second"], ["rhs"]])
    result, actual, names = _compile_raster(ee, deficient, local)
    assert names == ["first_rhs", "second_rhs"]
    native = [node for node in result["process_graph"].values()
              if node["process_id"] == "local_ee_matrix_values"]
    assert len(native) == 1
    spec = json.loads(native[0]["arguments"]["spec"])
    assert (spec["op"], spec["rows"], spec["cols"], spec["rhs_cols"]) == (
        "solve", 2, 2, 1,
    )
    expected = np.full((2, 6), np.nan)
    for column in range(5):
        b0 = Fraction.from_float(float(local["arrays"][local["item_id"]]["y0"][column]))
        b1 = Fraction.from_float(float(local["arrays"][local["item_id"]]["y1"][column]))
        minimum_norm = float((b0 + 2 * b1) / 10)
        expected[:, column] = [minimum_norm, minimum_norm]
    np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-7, equal_nan=True)

    with pytest.raises(UnsupportedEEError, match="real raster source"):
        _compile_value(
            ee,
            _design(ee, [[1, 1], [2, 2]]).matrixSolve(
                ee.Image.constant(ee.Array([[2], [4]])).toDouble(),
            ),
            local,
        )


def test_double_solver_accepts_finite_extreme_inputs_and_rejects_oversized_coefficients(
        ee, local):
    local["arrays"][local["item_id"]]["y0"] = np.full(6, 1.5e300)
    fitted = _design(ee, [[1e300]]).matrixSolve(
        _response(ee, 1),
    ).arrayFlatten([["scale"], ["rhs"]])
    _result, actual, _names = _compile_raster(ee, fitted, local)
    np.testing.assert_allclose(actual[0, :5], 1.5, rtol=0, atol=1e-14)

    with pytest.raises(UnsupportedEEError, match=r"\+/-2\^53 constant range"):
        _compile_value(
            ee,
            _design(ee, [[1e-300]]).matrixSolve(_response(ee, 1)),
            local,
        )


def test_upper_matrixsolve_dimensions_fit_the_original_cell_and_work_budgets():
    m, n, k = 8, 4, 4
    coordinates = np.linspace(-1.0, 1.0, m)
    design = np.asarray([
        [1.0, x, x * x, x * x * x] for x in coordinates
    ], dtype=np.float64)
    coefficients = np.asarray([
        [2.0, -1.0, 0.5, 3.0],
        [0.5, 2.0, 0.3, -1.0],
        [0.25, -0.5, 1.2, 0.2],
        [-0.75, 0.25, 0.5, 1.0],
    ], dtype=np.float64)
    response = design @ coefficients
    left_image = wrap_array_image(
        Image([], {}), (m, n),
        tuple(Pixel("to_double", (const(float(value)),)) for value in design.flat),
        const(True), "lhs",
    )
    right_image = wrap_array_image(
        Image([], {}), (m, k),
        tuple(Pixel("to_double", (const(float(value)),)) for value in response.flat),
        const(True), "rhs",
    )
    translator = Translator([], {}, {})

    result = invoke_raster_matrix(translator, "Image.matrixSolve", {
        "image1": left_image,
        "image2": right_image,
    })

    actual = np.asarray([[_evaluate_pixel(pixel) for pixel in result.cells[row * k:(row + 1) * k]]
                         for row in range(n)])
    assert len(left_image.cells) + len(right_image.cells) == 64
    assert result.shape == (n, k)
    assert translator.steps < 50_000
    assert _pixel_node_count(result.cells) < 500
    np.testing.assert_allclose(actual, coefficients, rtol=0, atol=2e-12)

    float_right = wrap_array_image(
        Image([], {}), (m, k),
        tuple(Pixel("to_float", (const(float(np.float32(value))),))
              for value in response.flat),
        const(True), "rhs-float",
    )
    mixed_translator = Translator([], {}, {})
    mixed_result = invoke_raster_matrix(mixed_translator, "Image.matrixSolve", {
        "image1": left_image,
        "image2": float_right,
    })
    assert mixed_translator.steps == translator.steps
    assert _pixel_node_count(mixed_result.cells) < 500


def _evaluate_pixel(pixel):
    if pixel.op == "constant":
        return pixel.args[0]
    if pixel.op == "to_double":
        return float(_evaluate_pixel(pixel.args[0]))
    if pixel.op == "to_float":
        return np.float32(_evaluate_pixel(pixel.args[0])).item()
    if pixel.op == "absolute":
        return abs(_evaluate_pixel(pixel.args[0]))
    if pixel.op == "max2":
        return max(_evaluate_pixel(pixel.args[0]), _evaluate_pixel(pixel.args[1]))
    if pixel.op == "lte":
        return _evaluate_pixel(pixel.args[0]) <= _evaluate_pixel(pixel.args[1])
    if pixel.op == "and":
        return bool(_evaluate_pixel(pixel.args[0]) and _evaluate_pixel(pixel.args[1]))
    if pixel.op == "multiply":
        return _evaluate_pixel(pixel.args[0]) * _evaluate_pixel(pixel.args[1])
    if pixel.op == "subtract":
        return _evaluate_pixel(pixel.args[0]) - _evaluate_pixel(pixel.args[1])
    if pixel.op == "add":
        return _evaluate_pixel(pixel.args[0]) + _evaluate_pixel(pixel.args[1])
    raise AssertionError(f"unexpected Pixel op: {pixel.op}")


def _pixel_node_count(cells):
    seen = set()

    def visit(pixel):
        if id(pixel) in seen:
            return
        seen.add(id(pixel))
        for argument in pixel.args:
            if isinstance(argument, Pixel):
                visit(argument)

    for cell in cells:
        visit(cell)
    return len(seen)
