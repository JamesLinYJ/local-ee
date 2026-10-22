"""Pinned SDK matrix properties through the local raster compiler."""
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
SCALES = np.asarray([1., 2., 3., 4., 5.])
MATRIX4 = np.asarray([
    [2, 1, 3, 1],
    [0, 4, 5, 2],
    [1, 2, 1, 3],
    [4, -1, 0, 2],
], dtype=np.float64)
MATRIX3 = MATRIX4[:3, :3]
MATRIX_BANDS = [f"m{row}{column}" for row in range(4) for column in range(4)]
COLUMN_BANDS = [f"column_{index}" for index in range(8)]
CANCEL_BANDS = [f"cancel_{index}" for index in range(3)]
OVERFLOW_BANDS = ["overflow_00", "overflow_01", "overflow_10", "overflow_11"]


def matrix_bands(rows, columns):
    return [f"m{row}{column}" for row in range(rows) for column in range(columns)]


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
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 1], [0, 1], [0, 0]]]}
    arrays = {}
    for row in range(4):
        for column in range(4):
            arrays[f"m{row}{column}"] = MATRIX4[row, column] * SCALES
    # The missing sample is off the selected diagonal. Matrix properties must
    # still apply the source matrix's whole-array validity mask to every result.
    arrays["m01"][2] = np.nan
    column_values = [
        np.asarray([16777217., 2., 3., 4., 5.]),
        np.asarray([10., 20., 30., 40., 50.]),
        np.asarray([-1., -2., -3., -4., -5.]),
        np.asarray([4., 5., 6., 7., 8.]),
        np.asarray([8., 7., 6., 5., 4.]),
        np.asarray([3., 3., 3., 3., 3.]),
        np.asarray([-7., -6., -5., -4., -3.]),
        np.asarray([1., 0., 1., 0., 1.]),
    ]
    column_values[1][2] = np.nan
    arrays.update(dict(zip(COLUMN_BANDS, column_values)))
    arrays.update({name: np.zeros(5) for name in CANCEL_BANDS + OVERFLOW_BANDS})
    bands = MATRIX_BANDS + COLUMN_BANDS + CANCEL_BANDS + OVERFLOW_BANDS
    return {
        "catalog": [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": bands}}}],
        "items": {"sentinel-2-l2a": [{
            "id": "matrix-properties-scene", "bbox": [0, 0, 5, 1], "geometry": geometry,
            "properties": {"system:index": "matrix-properties-scene",
                           "system:time_start": 1000, "matrix_tag": "preserved"},
        }]},
        "arrays": {"matrix-properties-scene": arrays},
        "grid": np.asarray([[index + .5, .5] for index in range(5)]),
        "geometry": geometry,
    }


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def find_invocation(value, name):
    if isinstance(value, dict):
        if value.get("type") == "Invocation" and value.get("functionName") == name:
            return value
        for child in value.values():
            found = find_invocation(child, name)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for child in value:
            found = find_invocation(child, name)
            if found is not None:
                return found
    return None


def compile_value(ee, value, local):
    return compile_expression(encode(ee, value), local["catalog"], local["items"])


def compile_raster(ee, value, local):
    result = compile_value(ee, value, local)
    assert result["kind"] == "image"
    values, names, timed = evaluate_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries={"matrix-properties-scene": local["geometry"]},
    )
    assert timed is False
    return result, values, names


def first_image(ee):
    return ee.ImageCollection("sentinel-2-l2a").first()


def raster_matrix(ee, image, bands, shape, name="matrix", cast=True):
    value = image.select(list(bands)).toArray()
    value = value.arrayReshape(ee.Image.constant(ee.Array(list(shape))), 2)
    if cast:
        value = value.toFloat()
    return value.rename([name])


def fraction_determinant(values):
    """Exact Gaussian-elimination reference, independent of permutation expansion."""
    matrix = [[Fraction(value) for value in row] for row in values]
    size = len(matrix)
    sign = 1
    determinant = Fraction(1)
    for column in range(size):
        pivot_row = next((row for row in range(column, size)
                          if matrix[row][column] != 0), None)
        if pivot_row is None:
            return Fraction(0)
        if pivot_row != column:
            matrix[column], matrix[pivot_row] = matrix[pivot_row], matrix[column]
            sign = -sign
        pivot = matrix[column][column]
        determinant *= pivot
        for row in range(column + 1, size):
            factor = matrix[row][column] / pivot
            for index in range(column + 1, size):
                matrix[row][index] -= factor * matrix[column][index]
    return sign * determinant


def valid_pixels(local, bands):
    valid = np.ones(len(local["grid"]), dtype=bool)
    values = local["arrays"]["matrix-properties-scene"]
    for band in bands:
        valid &= np.isfinite(values[band])
    valid[-1] = False
    return valid


def test_sdk_matrix_diagonal_rectangular_uses_row_major_diagonal_and_whole_input_mask(ee, local):
    before = {name: values.copy()
              for name, values in local["arrays"]["matrix-properties-scene"].items()}
    matrix = raster_matrix(ee, first_image(ee).set("operation", "rectangular"),
                           matrix_bands(3, 4), (3, 4), "rectangular")
    diagonal = matrix.matrixDiagonal()
    encoded = encode(ee, diagonal.arrayFlatten([["d0", "d1", "d2"], ["value"]]))
    invocation = find_invocation(encoded, "Image.matrixDiagonal")
    assert invocation is not None
    assert set(invocation["arguments"]) == {"value"}
    assert compile_value(ee, diagonal.bandNames(), local)["value"] == ["rectangular"]

    result, actual, names = compile_raster(
        ee, diagonal.arrayFlatten([["d0", "d1", "d2"], ["value"]], separator="_"), local)
    assert names == result["bands"] == ["d0_value", "d1_value", "d2_value"]
    assert result["source_item_ids"] == ["matrix-properties-scene"]
    assert result["properties"]["matrix_tag"] == "preserved"
    assert result["properties"]["operation"] == "rectangular"

    expected = np.stack([
        MATRIX4[index, index] * SCALES for index in range(3)
    ]).astype(np.float32).astype(np.float64)
    expected[:, ~valid_pixels(local, matrix_bands(3, 4))] = np.nan
    np.testing.assert_array_equal(actual, expected)
    for name, values in before.items():
        np.testing.assert_array_equal(local["arrays"]["matrix-properties-scene"][name], values)


def test_sdk_matrix_to_diag_writes_float32_zero_off_diagonal_and_keeps_masks(ee, local):
    before = {name: values.copy()
              for name, values in local["arrays"]["matrix-properties-scene"].items()}
    column = raster_matrix(ee, first_image(ee).set("operation", "to-diag"),
                           COLUMN_BANDS[:3], (3, 1), "column")
    diagonal = column.matrixToDiag()
    assert compile_value(ee, diagonal.bandNames(), local)["value"] == ["column"]
    labels = [[f"r{row}" for row in range(3)], [f"c{column}" for column in range(3)]]
    result, actual, names = compile_raster(
        ee, diagonal.arrayFlatten(labels, separator="_"), local)

    expected_names = [f"r{row}_c{column}" for row in range(3) for column in range(3)]
    assert names == result["bands"] == expected_names
    assert result["properties"]["operation"] == "to-diag"
    assert result["source_item_ids"] == ["matrix-properties-scene"]
    raw = np.stack([local["arrays"]["matrix-properties-scene"][name]
                    for name in COLUMN_BANDS[:3]]).astype(np.float32).astype(np.float64)
    raw[:, ~valid_pixels(local, COLUMN_BANDS[:3])] = np.nan
    expected = np.stack([
        np.diag(raw[:, pixel]).reshape(-1) for pixel in range(raw.shape[1])
    ], axis=1)
    expected[:, ~valid_pixels(local, COLUMN_BANDS[:3])] = np.nan
    np.testing.assert_array_equal(actual, expected)
    assert np.all(actual[[1, 2, 3, 5, 6, 7], :2] == 0)
    assert np.isnan(actual[:, 2]).all() and np.isnan(actual[:, 4]).all()
    for name, values in before.items():
        np.testing.assert_array_equal(local["arrays"]["matrix-properties-scene"][name], values)


def test_sdk_matrix_trace_and_determinant_match_independent_references(ee, local):
    before = {name: values.copy()
              for name, values in local["arrays"]["matrix-properties-scene"].items()}
    matrix = raster_matrix(ee, first_image(ee).set("operation", "properties"),
                           matrix_bands(3, 3), (3, 3), "properties")
    for algorithm in ("Image.matrixTrace", "Image.matrixDeterminant"):
        expression = matrix.matrixTrace() if algorithm.endswith("Trace") else matrix.matrixDeterminant()
        invocation = find_invocation(encode(ee, expression), algorithm)
        assert invocation is not None
        assert set(invocation["arguments"]) == {"value"}

    trace_result, trace, trace_names = compile_raster(ee, matrix.matrixTrace(), local)
    assert trace_names == trace_result["bands"] == ["properties"]
    assert trace_result["properties"]["operation"] == "properties"
    expected_trace = (np.trace(MATRIX3) * SCALES).astype(np.float32).astype(np.float64)
    expected_trace[~valid_pixels(local, matrix_bands(3, 3))] = np.nan
    np.testing.assert_array_equal(trace[0], expected_trace)

    determinant_result, determinant, determinant_names = compile_raster(
        ee, matrix.matrixDeterminant(), local)
    assert determinant_names == determinant_result["bands"] == ["properties"]
    expected_det = []
    for pixel, scale in enumerate(SCALES):
        values = (MATRIX3 * scale).astype(np.float32).astype(np.float64)
        expected_det.append(float(fraction_determinant(values)))
    expected_det = np.asarray(expected_det, dtype=np.float64)
    expected_det[~valid_pixels(local, matrix_bands(3, 3))] = np.nan
    np.testing.assert_allclose(determinant[0], expected_det, rtol=0, atol=0, equal_nan=True)
    numpy_reference = np.asarray([
        np.linalg.det((MATRIX3 * scale).astype(np.float32).astype(np.float64))
        for scale in SCALES
    ])
    np.testing.assert_allclose(expected_det[[0, 1, 3]], numpy_reference[[0, 1, 3]],
                               rtol=1e-12, atol=1e-12)
    assert fraction_determinant(MATRIX3) == -19
    for name, values in before.items():
        np.testing.assert_array_equal(local["arrays"]["matrix-properties-scene"][name], values)


def test_float32_trace_accumulation_exposes_cancellation_policy(ee, local):
    names = ["cancel_0", "cancel_1", "cancel_2"]
    # Use raster-backed cells so this exercises per-pixel callback stages.
    source = first_image(ee)
    local["arrays"]["matrix-properties-scene"][names[0]] = np.full(5, 1e8)
    local["arrays"]["matrix-properties-scene"][names[1]] = np.full(5, 1.)
    local["arrays"]["matrix-properties-scene"][names[2]] = np.full(5, -1e8)
    # These are the diagonal of a 3x3 matrix; all other cells come from
    # existing source bands and the input remains square.
    square_names = ["cancel_0", "m01", "m02", "m10", "cancel_1", "m12",
                    "m20", "m21", "cancel_2"]
    cancellation = raster_matrix(ee, source.set("operation", "cancellation"),
                                 square_names, (3, 3), "cancelled")
    actual_result, actual, names = compile_raster(ee, cancellation.matrixTrace(), local)
    assert names == actual_result["bands"] == ["cancelled"]
    # Sequential Float32 accumulation rounds 1e8 + 1 back to 1e8, then
    # cancels to zero. The exact Fraction sum would be 1, so this documents
    # the local staged Float32 policy without claiming GEE parity.
    np.testing.assert_array_equal(actual[0, [0, 1, 3]], np.zeros(3, dtype=np.float64))
    assert np.isnan(actual[0, [2, 4]]).all()

    # Literal and source-backed pixels both retain the local staged Float32
    # policy when a scalar constant result is materialized on a source grid.
    literal = ee.Image.constant(ee.Array([
        [1e8, 0, 0], [0, 1, 0], [0, 0, -1e8],
    ])).toFloat()
    materialized = literal.matrixTrace().add(source.select(["m00"]).multiply(0))
    _, literal_actual, _ = compile_raster(ee, materialized, local)
    np.testing.assert_array_equal(literal_actual[0, [0, 1, 3]], np.zeros(3))


def test_finite_float32_cells_can_overflow_trace_and_determinant_locally(ee, local):
    arrays = local["arrays"]["matrix-properties-scene"]
    for band, value in zip(OVERFLOW_BANDS, [2e38, 0., 0., 2e38]):
        arrays[band] = np.full(5, value)
    matrix = raster_matrix(ee, first_image(ee), OVERFLOW_BANDS, (2, 2),
                           "large_finite_float32")

    with np.errstate(over="ignore", invalid="ignore"):
        _, trace, _ = compile_raster(ee, matrix.matrixTrace(), local)
        _, determinant, _ = compile_raster(ee, matrix.matrixDeterminant(), local)

    assert np.isfinite(np.float32(2e38))
    assert np.isposinf(trace[0, :4]).all()
    assert np.isposinf(determinant[0, :4]).all()
    assert np.isnan(trace[0, 4]) and np.isnan(determinant[0, 4])

