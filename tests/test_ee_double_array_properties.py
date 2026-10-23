"""Explicit Float64 stages for bounded raster arrays and matrix properties."""
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, const
from gee.compat.earthengine.raster_array_core import wrap_array_image
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from ee_float64_graph_reference import evaluate_float64_graph


ROOT = Path(__file__).resolve().parents[1]
GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [5, 0], [5, 1], [0, 1], [0, 0]]],
}
MATRIX_BANDS = ["m00", "m01", "m10", "m11"]
ACCUM_BANDS = ["a0", "a1", "a2"]


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
    arrays = {
        "zero_seed": np.asarray([-1.25, -5e-324, -0.0, np.nan, -2.5]),
        "m00": np.asarray([16777217., 1e308, 3e-320, 5., 1.]),
        "m01": np.asarray([9., 1e308, 4e-320, 0., np.nan]),
        "m10": np.asarray([2., 0., 0., 0., 3.]),
        "m11": np.asarray([1., -1e308, 0., 2., 4.]),
        "a0": np.asarray([16777217., 1e308, 5e-324, 3., 1.]),
        "a1": np.asarray([1., 1e308, 5e-324, -2., np.nan]),
        "a2": np.asarray([-16777216., -1e308, 0., 4., 1.]),
    }
    bands = ["zero_seed"] + MATRIX_BANDS + ACCUM_BANDS
    item = {
        "id": "double-array-scene", "bbox": [0, 0, 5, 1],
        "geometry": GEOMETRY,
        "properties": {
            "system:index": "double-array-scene", "system:time_start": 1000,
            "proj:code": "EPSG:32649",
            "proj:transform": [10, 0, 220000, 0, -10, 3420000],
        },
    }
    return {
        "catalog": [{"id": "sentinel-2-l2a", "cube:dimensions": {
            "bands": {"values": bands},
        }}],
        "items": {"sentinel-2-l2a": [item]},
        "arrays": {"double-array-scene": arrays},
        "grid": np.asarray([[index + .5, .5] for index in range(5)]),
        "geometry": GEOMETRY,
    }


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_value(ee, value, local):
    return compile_expression(encode(ee, value), local["catalog"], local["items"])


def compile_raster(ee, value, local):
    result = compile_value(ee, value, local)
    values, names, timed = evaluate_float64_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries={"double-array-scene": local["geometry"]},
    )
    assert timed is False
    return result, values, names


def source_array(ee, image, bands, shape, name, precision="double"):
    selected = image.select(list(bands))
    if precision == "double":
        selected = selected.toDouble()
    elif precision == "float":
        selected = selected.toFloat()
    elif precision == "float_then_double":
        selected = selected.toFloat().toDouble()
    elif precision == "double_then_float":
        selected = selected.toDouble().toFloat()
    elif precision != "uncast":
        raise AssertionError(f"unknown fixture precision {precision!r}")
    array = selected.toArray()
    dimensions = ee.Image.constant(ee.Array(list(shape)))
    return array.arrayReshape(dimensions, len(shape)).rename([name])


def _fraction_float(value):
    try:
        result = float(value)
    except OverflowError:
        return np.nan
    return result if np.isfinite(result) else np.nan


def _matrix_values(local):
    arrays = local["arrays"]["double-array-scene"]
    return np.stack([arrays[name] for name in MATRIX_BANDS], axis=1).reshape(5, 2, 2)


def test_double_matrix_trace_determinant_and_scaled_norm_keep_precision_and_mask(
        ee, local):
    source = ee.ImageCollection("sentinel-2-l2a").first().set("matrix_owner", "kept")
    matrix = source_array(ee, source, MATRIX_BANDS, (2, 2), "matrix")
    values = _matrix_values(local)

    trace_result, trace, trace_names = compile_raster(ee, matrix.matrixTrace(), local)
    determinant_result, determinant, determinant_names = compile_raster(
        ee, matrix.matrixDeterminant(), local,
    )
    norm_result, norm, norm_names = compile_raster(ee, matrix.matrixFnorm(), local)

    for result, actual, names in (
            (trace_result, trace, trace_names),
            (determinant_result, determinant, determinant_names),
            (norm_result, norm, norm_names)):
        assert result["bands"] == names == ["matrix"]
        assert result["properties"]["matrix_owner"] == "kept"
        assert result["source_item_ids"] == ["double-array-scene"]
        assert any(node["process_id"] == "local_ee_integer_values"
                   for node in result["process_graph"].values())

    exact_trace = np.asarray([
        _fraction_float(Fraction.from_float(float(row[0, 0]))
                        + Fraction.from_float(float(row[1, 1])))
        for row in values
    ])
    exact_determinant = np.asarray([
        _fraction_float(
            Fraction.from_float(float(row[0, 0]))
            * Fraction.from_float(float(row[1, 1]))
            - Fraction.from_float(float(row[0, 1]))
            * Fraction.from_float(float(row[1, 0]))
        ) if np.isfinite(row).all() else np.nan
        for row in values
    ])
    exact_trace[4] = exact_determinant[4] = np.nan
    np.testing.assert_array_equal(trace[0], exact_trace)
    # This small polynomial reference validates local staged arithmetic; it
    # does not claim determinant cancellation or Google/LU parity.
    exact_determinant[1] = np.nan  # A nonfinite native result becomes NoData.
    np.testing.assert_array_equal(determinant[0], exact_determinant)

    expected_norm = np.hypot.reduce(np.abs(values).reshape(5, 4), axis=1)
    expected_norm[4] = np.nan
    assert norm[0, 1] == pytest.approx(np.sqrt(3.) * 1e308, rel=2e-16)
    assert norm[0, 2] == pytest.approx(5e-320, rel=2e-15)
    np.testing.assert_allclose(norm[0], expected_norm, rtol=2e-15, atol=0, equal_nan=True)
    assert np.isnan(trace[0, 4]) and np.isnan(determinant[0, 4]) and np.isnan(norm[0, 4])


def test_double_matrix_to_diag_inserts_double_zeros_and_keeps_array_mask(ee, local):
    source = ee.ImageCollection("sentinel-2-l2a").first().set("owner", "column")
    column_bands = ["zero_seed", "m00", "m10", "m11"]
    column = source_array(ee, source, column_bands, (4, 1), "column")
    labels = [[f"r{row}" for row in range(4)], [f"c{column}" for column in range(4)]]
    expression = column.matrixToDiag().arrayFlatten(labels, separator="_")
    result, actual, names = compile_raster(ee, expression, local)

    matrix_ir = Translator(local["catalog"], local["items"], {}).evaluate(
        encode(ee, column.matrixToDiag()),
    )
    off_diagonal_pixels = [
        matrix_ir.cells[row * 4 + col]
        for row in range(4) for col in range(4) if row != col
    ]
    assert all(pixel is off_diagonal_pixels[0] for pixel in off_diagonal_pixels)

    assert names == result["bands"] == [f"r{row}_c{col}" for row in range(4) for col in range(4)]
    assert result["properties"]["owner"] == "column"
    assert result["source_item_ids"] == ["double-array-scene"]
    raw = np.stack([
        local["arrays"]["double-array-scene"][band] for band in column_bands
    ], axis=1)
    expected = np.zeros((5, 16), dtype=np.float64)
    for index in range(4):
        expected[:, index * 4 + index] = raw[:, index]
    off_diagonal_indexes = [
        row * 4 + col for row in range(4) for col in range(4) if row != col
    ]
    expected[3, :] = np.nan  # Missing in one input cell applies the full-array mask.
    for row in np.flatnonzero(~np.isfinite(raw[:, 0])):
        expected[row, off_diagonal_indexes] = np.nan
    np.testing.assert_array_equal(actual, expected.T)
    assert np.signbit(raw[:3, 0]).all()  # negative finite, subnormal, and zero inputs
    actual_bits = actual.view(np.uint64)
    assert np.all(actual_bits[off_diagonal_indexes, :3] == np.uint64(0))
    assert np.all(actual_bits[off_diagonal_indexes, 4] == np.uint64(0))
    assert actual_bits[0, 2] == np.uint64(0x8000000000000000)


@pytest.mark.parametrize("infinity", [np.inf, -np.inf], ids=["positive", "negative"])
def test_double_matrix_to_diag_oracle_rejects_source_infinity(ee, local, infinity):
    source = ee.ImageCollection("sentinel-2-l2a").first()
    column_bands = ["zero_seed", "m00", "m10", "m11"]
    column = source_array(ee, source, column_bands, (4, 1), "column")
    result = compile_value(ee, column.matrixToDiag().arrayFlatten(
        [["r0", "r1", "r2", "r3"], ["c0", "c1", "c2", "c3"]],
        separator="_",
    ), local)

    scene = "double-array-scene"
    source_arrays = local["arrays"][scene]
    arrays = {scene: dict(source_arrays)}
    zero_seed = np.array(source_arrays["zero_seed"], copy=True)
    zero_seed[4] = infinity
    arrays[scene]["zero_seed"] = zero_seed
    with pytest.raises(ValueError, match="valid infinity"):
        evaluate_float64_graph(
            result, arrays, grid=local["grid"],
            source_geometries={scene: local["geometry"]},
        )


@pytest.mark.parametrize("reducer", ["sum", "min", "max"])
def test_double_array_accum_stages_each_prefix_and_keeps_mask_metadata(
        ee, local, reducer):
    source = ee.ImageCollection("sentinel-2-l2a").first().set("accum_owner", "kept")
    array = source_array(ee, source, ACCUM_BANDS, (3,), "prefix")
    method = array.arrayAccum(0) if reducer == "sum" else array.arrayAccum(
        0, getattr(ee.Reducer, reducer)(),
    )
    expression = method.arrayFlatten([["first", "second", "third"]])
    result, actual, names = compile_raster(ee, expression, local)

    assert names == result["bands"] == ["first", "second", "third"]
    assert result["properties"]["accum_owner"] == "kept"
    assert result["source_item_ids"] == ["double-array-scene"]
    assert sum(node["process_id"] == "local_ee_integer_values"
               for node in result["process_graph"].values()) >= 2

    raw = np.stack([
        local["arrays"]["double-array-scene"][band] for band in ACCUM_BANDS
    ])
    with np.errstate(over="ignore", invalid="ignore"):
        if reducer == "sum":
            expected = np.add.accumulate(raw, axis=0, dtype=np.float64)
        elif reducer == "min":
            expected = np.minimum.accumulate(raw, axis=0)
        else:
            expected = np.maximum.accumulate(raw, axis=0)
    expected[~np.isfinite(expected)] = np.nan
    expected[:, 4] = np.nan
    np.testing.assert_allclose(actual, expected, rtol=0, atol=0, equal_nan=True)
    assert actual[0, 0] == 16777217.
    if reducer == "sum":
        assert actual[1, 0] == 16777218.
        assert actual[2, 0] == 2.
        assert actual[1, 2] == 1e-323


def test_double_array_operations_preserve_nested_float32_boundary(ee, local):
    source = ee.ImageCollection("sentinel-2-l2a").first()
    scene = "double-array-scene"
    finite_arrays = {scene: dict(local["arrays"][scene])}
    for band, value in zip(MATRIX_BANDS, (1e20, 2e20, 3e20, -1e20)):
        values = np.array(finite_arrays[scene][band], copy=True)
        values[1] = value
        finite_arrays[scene][band] = values
    finite_local = dict(local)
    finite_local["arrays"] = finite_arrays
    matrix = source_array(
        ee, source, MATRIX_BANDS, (2, 2), "narrowed", precision="float_then_double",
    )
    result, actual, names = compile_raster(ee, matrix.matrixTrace(), finite_local)

    expected_first = float(np.float32(16777217.)) + 1.
    assert names == result["bands"] == ["narrowed"]
    assert actual[0, 0] == expected_first == 16777217.
    processes = {node["process_id"] for node in result["process_graph"].values()}
    assert "local_ee_to_float" in processes
    assert "local_ee_to_double" in processes
    assert "local_ee_integer_values" in processes
    assert np.isnan(actual[0, 4])
