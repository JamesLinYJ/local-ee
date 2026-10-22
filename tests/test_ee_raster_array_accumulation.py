"""Pinned raster-array prefix scans and stable matrix Frobenius norms."""
from decimal import Decimal, localcontext
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
ARRAY_BANDS = [f"v{index:02d}" for index in range(64)]
CANCEL_BANDS = [f"cancel_{index}" for index in range(3)]
OVERFLOW_BANDS = ["overflow_0", "overflow_1"]
NORM_BANDS = ["norm_00", "norm_01", "norm_10", "norm_11"]


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
    geometry = {"type": "Polygon", "coordinates": [
        [[0, 0], [4, 0], [4, 1], [0, 1], [0, 0]],
    ]}
    arrays = {}
    for index, band in enumerate(ARRAY_BANDS):
        sign = -1.0 if index % 2 else 1.0
        arrays[band] = np.asarray([
            sign * (index + 1 + pixel * 0.5) for pixel in range(5)
        ], dtype=np.float64)
    # A single missing off-diagonal source cell masks every cumulative result
    # for that input array at sample 2.
    arrays["v05"][2] = np.nan
    arrays.update({
        "cancel_0": np.full(5, 1e8),
        "cancel_1": np.full(5, 1.0),
        "cancel_2": np.full(5, -1e8),
        "overflow_0": np.full(5, 2e38),
        "overflow_1": np.full(5, 2e38),
        # Four cells in one rank-2 array yield well-scaled large, tiny, zero,
        # and near-Float32-limit norm cases at the first four sample centers.
        "norm_00": np.asarray([3e30, 3e-30, 0.0, 2e38, 0.0]),
        "norm_01": np.asarray([4e30, 4e-30, 0.0, 2e38, 0.0]),
        "norm_10": np.zeros(5),
        "norm_11": np.zeros(5),
    })
    bands = ARRAY_BANDS + CANCEL_BANDS + OVERFLOW_BANDS + NORM_BANDS
    return {
        "catalog": [{"id": "sentinel-2-l2a", "cube:dimensions": {
            "bands": {"values": bands},
        }}],
        "items": {"sentinel-2-l2a": [{
            "id": "accum-scene", "bbox": [0, 0, 5, 1], "geometry": geometry,
            "properties": {"system:index": "accum-scene", "system:time_start": 1000,
                           "synthetic": True},
        }]},
        "arrays": {"accum-scene": arrays},
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
        source_geometries={"accum-scene": local["geometry"]},
    )
    assert timed is False
    return result, values, names


def first_image(ee):
    return ee.ImageCollection("sentinel-2-l2a").first()


def source_array(ee, image, bands, shape, name="array"):
    value = image.select(list(bands)).toArray()
    dimensions = ee.Image.constant(ee.Array(list(shape)))
    return value.arrayReshape(dimensions, len(shape)).toFloat().rename([name])


def matrix_labels(shape, separator="_"):
    return [[f"d{axis}_{index}" for index in range(length)]
            for axis, length in enumerate(shape)]


def source_values(local, bands, shape):
    arrays = local["arrays"]["accum-scene"]
    cells = np.stack([arrays[band] for band in bands], axis=1)
    return cells.astype(np.float32).astype(np.float64).reshape((len(local["grid"]), *shape))


def valid_samples(local, bands):
    arrays = local["arrays"]["accum-scene"]
    valid = np.ones(len(local["grid"]), dtype=bool)
    for band in bands:
        valid &= np.isfinite(arrays[band])
    valid[-1] = False
    return valid


def flattened_expected(values, valid):
    expected = values.reshape((len(valid), -1)).T.astype(np.float64)
    expected[:, ~valid] = np.nan
    return expected


def numpy_prefix(values, axis, reducer):
    if reducer == "sum":
        return np.add.accumulate(values.astype(np.float32), axis=axis, dtype=np.float32)
    operation = np.minimum if reducer == "min" else np.maximum
    return operation.accumulate(values.astype(np.float32), axis=axis)


def decimal_frobenius(matrix):
    with localcontext() as context:
        context.prec = 100
        total = sum(
            (Decimal.from_float(float(value)) ** 2 for value in matrix.flat),
            Decimal(0),
        )
        return float(total.sqrt())


@pytest.mark.parametrize("axis", [0, 1])
@pytest.mark.parametrize("reducer", ["sum", "min", "max"])
def test_sdk_array_accum_prefixes_rank_two_cells_and_preserves_whole_mask(
        ee, local, axis, reducer):
    bands = ARRAY_BANDS[:6]
    before = {name: values.copy() for name, values in local["arrays"]["accum-scene"].items()}
    source = first_image(ee).set("array_owner", "prefix-test")
    value = source_array(ee, source, bands, (2, 3), "matrix")
    reducer_value = None if reducer == "sum" else getattr(ee.Reducer, reducer)()
    accumulated = value.arrayAccum(axis) if reducer_value is None else value.arrayAccum(
        axis, reducer_value,
    )
    flattened = accumulated.arrayFlatten(matrix_labels((2, 3)), separator="_")

    result, actual, names = compile_raster(ee, flattened, local)
    expected_names = [f"d0_{row}_d1_{column}" for row in range(2) for column in range(3)]
    assert names == result["bands"] == expected_names
    assert result["properties"]["array_owner"] == "prefix-test"
    assert result["source_item_ids"] == ["accum-scene"]

    expected = source_values(local, bands, (2, 3))
    expected = numpy_prefix(expected, axis + 1, reducer)
    np.testing.assert_array_equal(
        actual, flattened_expected(expected, valid_samples(local, bands)),
    )
    assert np.isnan(actual[:, 2]).all()
    for name, previous in before.items():
        np.testing.assert_array_equal(local["arrays"]["accum-scene"][name], previous)


def test_sdk_array_accum_uses_actual_value_axis_and_nullable_reducer_wire_contract(ee, local):
    source = source_array(ee, first_image(ee), ARRAY_BANDS[:6], (2, 3), "wire")
    default = encode(ee, source.arrayAccum(0).arrayFlatten(matrix_labels((2, 3))))
    explicit_null = encode(ee, source.arrayAccum(0, None).arrayFlatten(matrix_labels((2, 3))))
    for encoded in (default, explicit_null):
        invocation = find_invocation(encoded, "Image.arrayAccum")
        assert invocation is not None
        assert set(invocation["arguments"]) == {"input", "axis"}
        assert invocation["arguments"]["axis"] == 0

    explicit_sum = encode(ee, source.arrayAccum(0, ee.Reducer.sum())
                          .arrayFlatten(matrix_labels((2, 3))))
    invocation = find_invocation(explicit_sum, "Image.arrayAccum")
    assert set(invocation["arguments"]) == {"input", "axis", "reducer"}
    assert invocation["arguments"]["axis"] == 0
    result_default, default_values, _ = compile_raster(
        ee, source.arrayAccum(0).arrayFlatten(matrix_labels((2, 3))), local,
    )
    result_explicit, explicit_values, _ = compile_raster(
        ee, source.arrayAccum(0, ee.Reducer.sum()).arrayFlatten(matrix_labels((2, 3))), local,
    )
    assert result_default["bands"] == result_explicit["bands"]
    np.testing.assert_array_equal(default_values, explicit_values)


def test_sdk_array_accum_rank_three_uses_row_major_axis_one_prefixes(ee, local):
    bands = ARRAY_BANDS[:8]
    shape = (2, 2, 2)
    source = source_array(ee, first_image(ee).set("array_rank", 3), bands, shape, "tensor")
    labels = [[f"z{index}" for index in range(2)],
              [f"y{index}" for index in range(2)],
              [f"x{index}" for index in range(2)]]
    result, actual, names = compile_raster(
        ee, source.arrayAccum(1, ee.Reducer.sum()).arrayFlatten(labels, separator="/"), local,
    )
    expected_names = [f"z{z}/y{y}/x{x}" for z in range(2) for y in range(2) for x in range(2)]
    assert names == result["bands"] == expected_names
    assert result["properties"]["array_rank"] == 3
    values = source_values(local, bands, shape)
    expected = numpy_prefix(values, 2, "sum")
    np.testing.assert_array_equal(
        actual, flattened_expected(expected, valid_samples(local, bands)),
    )


def test_float32_prefix_sum_matches_staged_cancellation_for_dynamic_and_literal_arrays(ee, local):
    bands = CANCEL_BANDS
    source = source_array(ee, first_image(ee), bands, (3,), "cancellation")
    labels = ["first", "second", "third"]
    dynamic = source.arrayAccum(0).arrayFlatten([labels])
    _, actual, names = compile_raster(ee, dynamic, local)
    assert names == ["first", "second", "third"]
    np.testing.assert_array_equal(actual[:, :4], np.asarray([
        [1e8, 1e8, 0], [1e8, 1e8, 0], [1e8, 1e8, 0], [1e8, 1e8, 0],
    ], dtype=np.float32).T.astype(np.float64))

    literal = ee.Image.constant(ee.Array([1e8, 1.0, -1e8])).toFloat()
    flattened = literal.arrayAccum(0).arrayFlatten([labels])
    materialized = flattened.add(first_image(ee).select([ARRAY_BANDS[0]]).multiply(0))
    _, static_actual, static_names = compile_raster(ee, materialized, local)
    assert static_names == names
    np.testing.assert_array_equal(static_actual[:, :4], actual[:, :4])


def test_finite_float32_prefix_values_can_overflow_during_accumulation(ee, local):
    source = source_array(ee, first_image(ee), OVERFLOW_BANDS, (2,), "overflow")
    value = source.arrayAccum(0).arrayFlatten([["first", "second"]])
    with np.errstate(over="ignore", invalid="ignore"):
        result, actual, names = compile_raster(ee, value, local)
    assert names == result["bands"] == ["first", "second"]
    assert np.isfinite(np.float32(2e38))
    assert np.all(actual[0, :4] == float(np.float32(2e38)))
    assert np.isposinf(actual[1, :4]).all()
    assert np.isnan(actual[:, 4]).all()

    literal = ee.Image.constant(ee.Array([2e38, 2e38])).toFloat()
    flattened = literal.arrayAccum(0).arrayFlatten([["first", "second"]])
    materialized = flattened.add(first_image(ee).select([ARRAY_BANDS[0]]).multiply(0))
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, materialized, local)


def test_matrix_fnorm_uses_decimal_reference_masks_metadata_and_scale_range(ee, local):
    bands = ["norm_00", "norm_01", "norm_10", "norm_11"]
    before = {name: values.copy() for name, values in local["arrays"]["accum-scene"].items()}
    matrix = source_array(ee, first_image(ee).set("norm_tag", "preserved"),
                          bands, (2, 2), "frobenius")
    invocation = find_invocation(encode(ee, matrix.matrixFnorm()), "Image.matrixFnorm")
    assert invocation is not None
    assert set(invocation["arguments"]) == {"value"}

    result, actual, names = compile_raster(ee, matrix.matrixFnorm(), local)
    assert names == result["bands"] == ["frobenius"]
    assert result["properties"]["norm_tag"] == "preserved"
    assert result["source_item_ids"] == ["accum-scene"]
    input_values = source_values(local, bands, (2, 2))
    expected = np.asarray([
        decimal_frobenius(input_values[pixel]) for pixel in range(4)
    ], dtype=np.float64)
    expected = np.concatenate((expected, [np.nan]))
    assert expected[0] == pytest.approx(5e30, rel=2e-7)
    assert expected[1] == pytest.approx(5e-30, rel=2e-7)
    assert expected[2] == 0
    assert np.isfinite(expected[3]) and expected[3] > 2.8e38
    np.testing.assert_allclose(actual[0], expected, rtol=3e-6, atol=0, equal_nan=True)
    assert actual[0, 2] == 0  # Scale=0 is handled without 0/0 NaN.
    for name, previous in before.items():
        np.testing.assert_array_equal(local["arrays"]["accum-scene"][name], previous)


def test_matrix_fnorm_preserves_whole_array_mask_from_an_off_diagonal_cell(ee, local):
    bands = [ARRAY_BANDS[0], ARRAY_BANDS[5], ARRAY_BANDS[8], ARRAY_BANDS[9]]
    matrix = source_array(ee, first_image(ee), bands, (2, 2), "masked_norm")
    result, actual, names = compile_raster(ee, matrix.matrixFnorm(), local)
    assert names == result["bands"] == ["masked_norm"]
    assert np.isnan(actual[0, 2])
    assert np.isnan(actual[0, 4])
    assert np.isfinite(actual[0, [0, 1, 3]]).all()


def test_matrix_fnorm_accepts_rectangular_rank_two_arrays(ee, local):
    bands = ARRAY_BANDS[:6]
    matrix = source_array(ee, first_image(ee), bands, (2, 3), "rectangular_norm")
    result, actual, names = compile_raster(ee, matrix.matrixFnorm(), local)
    assert names == result["bands"] == ["rectangular_norm"]
    values = source_values(local, bands, (2, 3))
    expected = np.asarray([decimal_frobenius(values[pixel]) for pixel in range(4)])
    expected = np.concatenate((expected, [np.nan]))
    np.testing.assert_allclose(actual[0], expected, rtol=2e-6, atol=0, equal_nan=True)


def test_finite_float32_matrix_norm_can_overflow_only_at_the_final_scale(ee, local):
    arrays = local["arrays"]["accum-scene"]
    arrays["norm_00"] = np.asarray([0.0, 0.0, 0.0, 3e38, 0.0])
    arrays["norm_01"] = np.asarray([0.0, 0.0, 0.0, 3e38, 0.0])
    arrays["norm_10"] = np.zeros(5)
    arrays["norm_11"] = np.zeros(5)
    matrix = source_array(ee, first_image(ee), NORM_BANDS, (2, 2), "finite_input_overflow")

    with np.errstate(over="ignore", invalid="ignore"):
        _, actual, _ = compile_raster(ee, matrix.matrixFnorm(), local)
    input_value = np.float32(3e38)
    assert np.isfinite(input_value)
    # sqrt(3e38**2 + 3e38**2) exceeds Float32 even though both cells fit.
    assert decimal_frobenius(np.asarray([[input_value, input_value], [0, 0]])) > float(
        np.finfo(np.float32).max,
    )
    assert np.isposinf(actual[0, 3])
    assert np.isnan(actual[0, 4])

    literal = ee.Image.constant(ee.Array([[3e38, 3e38], [0, 0]])).toFloat()
    materialized = literal.matrixFnorm().add(first_image(ee).select([ARRAY_BANDS[0]]).multiply(0))
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, materialized, local)


def test_literal_zero_matrix_fnorm_is_zero_when_materialized_on_source_grid(ee, local):
    literal = ee.Image.constant(ee.Array([[0, 0], [0, 0]])).toFloat()
    scalar = literal.matrixFnorm().add(first_image(ee).select([ARRAY_BANDS[0]]).multiply(0))
    _, values, _ = compile_raster(ee, scalar, local)
    np.testing.assert_array_equal(values[0, :4], np.zeros(4))
    assert np.isnan(values[0, 4])
