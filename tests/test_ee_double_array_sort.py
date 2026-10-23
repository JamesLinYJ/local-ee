"""Independent sample-graph checks for explicit Float64 raster sorting."""
import json

import numpy as np
import pytest
from shapely.geometry import Point, shape

from ee_float64_graph_reference import evaluate_float64_graph
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_double_array_properties import ee, local, source_array


SCENE = "double-array-scene"


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


def _compile_raster(ee, expression, local):
    encoded = ee.serializer.encode(expression, for_cloud_api=False)
    result = compile_expression(encoded, local["catalog"], local["items"])
    values, names, timed = evaluate_float64_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries={SCENE: local["geometry"]},
    )
    assert timed is False
    return result, values, names


def _source_values(local, bands, array_shape, precision):
    arrays = local["arrays"][SCENE]
    sample_count = len(local["grid"])
    values = np.stack([np.asarray(arrays[band], dtype=np.float64) for band in bands], axis=1)
    values = values.reshape((sample_count, *array_shape))
    if precision in {"float", "float_then_double", "double_then_float"}:
        values = values.astype(np.float32).astype(np.float64)
    return values


def _numpy_sample_reference(local, value_bands, value_shape, value_precision,
                            key_bands, key_shape, key_precision, axis):
    """Sort each finite, covered sample with NumPy's independent stable argsort."""
    values = _source_values(local, value_bands, value_shape, value_precision)
    keys = _source_values(local, key_bands, key_shape, key_precision)
    geometry = shape(local["geometry"])
    samples = np.full((len(local["grid"]), values[0].size), np.nan, dtype=np.float64)

    for sample, center in enumerate(local["grid"]):
        if not geometry.covers(Point(float(center[0]), float(center[1]))):
            continue
        if not np.isfinite(values[sample]).all() or not np.isfinite(keys[sample]).all():
            continue
        permutation = np.argsort(keys[sample].reshape(-1), kind="stable")
        samples[sample] = np.take(values[sample], permutation, axis=axis).reshape(-1)

    return samples.T


def _source(ee):
    return ee.ImageCollection("sentinel-2-l2a").first().set("sort_owner", "payload")


def test_double_keys_preserve_fine_order_extremes_subnormals_and_both_input_masks(
        ee, local):
    arrays = local["arrays"][SCENE]
    payload_bands = ["a0", "a1", "a2"]
    key_bands = ["m00", "m01", "m10"]

    arrays["a0"][:] = [101.25, 11.5, 21.25, 31.5, 41.25]
    arrays["a1"][:] = [202.5, 12.5, 22.5, 32.5, 42.5]
    arrays["a2"][:] = [303.75, 13.75, 23.75, np.nan, 43.75]
    arrays["m00"][:] = [16777217.0, 1e308, -5e-324, 3.0, 5.0]
    arrays["m01"][:] = [16777216.0, -1e308, 0.0, 1.0, np.nan]
    arrays["m10"][:] = [16777215.0, 1e308, -0.0, 2.0, 0.0]

    payload = source_array(ee, _source(ee), payload_bands, (3,), "payload", "float")
    keys = source_array(ee, _source(ee), key_bands, (3,), "keys", "double")
    result, actual, names = _compile_raster(
        ee, payload.arraySort(keys).arrayFlatten([["out0", "out1", "out2"]]), local,
    )
    expected = _numpy_sample_reference(
        local, payload_bands, (3,), "float", key_bands, (3,), "double", 0,
    )

    np.testing.assert_array_equal(actual, expected)
    assert actual[:, 0].tolist() == [303.75, 202.5, 101.25]
    assert np.isnan(actual[:, 3]).all()  # invalid payload masks its entire array
    assert np.isnan(actual[:, 4]).all()  # invalid key masks the payload array
    assert result["bands"] == names == ["out0", "out1", "out2"]
    assert result["properties"]["sort_owner"] == "payload"
    assert result["source_item_ids"] == [SCENE]
    assert len(result["process_graph"]) <= 500
    assert any(node["process_id"] == "local_ee_integer_values"
               for node in result["process_graph"].values())


def test_double_payload_keeps_its_precision_with_float_keys(ee, local):
    arrays = local["arrays"][SCENE]
    payload_bands = ["a0", "a1", "a2"]
    key_bands = ["m00", "m01", "m10"]
    arrays["a0"][0], arrays["a1"][0], arrays["a2"][0] = 16777217.0, 16777216.0, 7.0
    arrays["m00"][:] = [16777217.0, 11.0, 21.0, 31.0, 41.0]
    arrays["m01"][:] = [16777216.0, 12.0, 22.0, 32.0, 42.0]
    arrays["m10"][:] = [16777215.0, 13.0, 23.0, 33.0, 43.0]

    payload = source_array(ee, _source(ee), payload_bands, (3,), "payload", "double")
    keys = source_array(ee, _source(ee), key_bands, (3,), "keys", "float")
    result, actual, _names = _compile_raster(
        ee, payload.arraySort(keys).arrayFlatten([["first", "second", "third"]]), local,
    )
    expected = _numpy_sample_reference(
        local, payload_bands, (3,), "double", key_bands, (3,), "float", 0,
    )

    np.testing.assert_array_equal(actual, expected)
    assert actual[1, 0] == 16777217.0
    assert actual[2, 0] == 16777216.0
    assert result["properties"]["sort_owner"] == "payload"
    assert any(
        node["process_id"] == "local_ee_integer_values"
        and json.loads(node["arguments"]["spec"])["op"] == "select"
        for node in result["process_graph"].values()
    )


@pytest.mark.parametrize(
    "axis,key_bands,key_shape",
    [(0, ["m00", "m01"], (2, 1)), (1, ["m00", "m10"], (1, 2))],
)
def test_rank_two_double_payload_uses_the_key_array_axis(
        ee, local, axis, key_bands, key_shape):
    arrays = local["arrays"][SCENE]
    if axis == 0:
        arrays["m00"][:] = [2.0, 11.0, 21.0, 31.0, 41.0]
        arrays["m01"][:] = [1.0, 12.0, 22.0, 32.0, 42.0]
    else:
        arrays["m00"][:] = [2.0, 11.0, 21.0, 31.0, 41.0]
        arrays["m10"][:] = [1.0, 13.0, 23.0, 33.0, 43.0]

    payload_bands = ["a0", "a1", "a2", "zero_seed"]
    payload = source_array(ee, _source(ee), payload_bands, (2, 2), "matrix", "double")
    keys = source_array(ee, _source(ee), key_bands, key_shape, "axis_keys", "float")
    result, actual, names = _compile_raster(
        ee,
        payload.arraySort(keys).arrayFlatten(
            [["r0", "r1"], ["c0", "c1"]], separator="_",
        ),
        local,
    )
    expected = _numpy_sample_reference(
        local, payload_bands, (2, 2), "double", key_bands, key_shape, "float", axis,
    )

    np.testing.assert_array_equal(actual, expected)
    assert result["bands"] == names == ["r0_c0", "r0_c1", "r1_c0", "r1_c1"]
    assert result["properties"]["sort_owner"] == "payload"
    assert result["source_item_ids"] == [SCENE]
    assert len(result["process_graph"]) <= 500


@pytest.mark.parametrize("explicit_null", [False, True])
def test_default_and_null_keys_sort_double_values_with_the_full_array_mask(
        ee, local, explicit_null):
    value_bands = ["a0", "a1", "a2"]
    value = source_array(ee, _source(ee), value_bands, (3,), "default_keys", "double")
    expression = value.arraySort(None) if explicit_null else value.arraySort()
    result, actual, _names = _compile_raster(
        ee, expression.arrayFlatten([["v0", "v1", "v2"]]), local,
    )
    expected = _numpy_sample_reference(
        local, value_bands, (3,), "double", value_bands, (3,), "double", 0,
    )

    np.testing.assert_array_equal(actual, expected)
    assert np.isnan(actual[:, 4]).all()
    assert result["source_item_ids"] == [SCENE]
    assert len(result["process_graph"]) <= 500


def test_nested_float32_to_double_cast_keeps_payload_rounding_and_key_ties(ee, local):
    arrays = local["arrays"][SCENE]
    arrays["a0"][:] = [16777217.0, 11.5, 21.25, 31.5, 41.25]
    arrays["a1"][:] = [16777219.0, 12.5, 22.25, 32.5, 42.25]
    arrays["m00"][:] = [2.0, 11.0, 21.0, 31.0, 41.0]
    arrays["m01"][:] = [1.0, 12.0, 22.0, 32.0, 42.0]

    rounded_payload = source_array(
        ee, _source(ee), ["a0", "a1"], (2,), "rounded_payload", "float_then_double",
    )
    precise_keys = source_array(
        ee, _source(ee), ["m00", "m01"], (2,), "precise_keys", "double",
    )
    payload_result, payload_actual, _ = _compile_raster(
        ee, rounded_payload.arraySort(precise_keys).arrayFlatten([["x", "y"]]), local,
    )
    expected_payload = _numpy_sample_reference(
        local, ["a0", "a1"], (2,), "float_then_double",
        ["m00", "m01"], (2,), "double", 0,
    )
    np.testing.assert_array_equal(payload_actual, expected_payload)
    assert payload_actual[:, 0].tolist() == [16777220.0, 16777216.0]
    assert any(node["process_id"] == "local_ee_to_float"
               for node in payload_result["process_graph"].values())

    arrays["m00"][0], arrays["m01"][0] = 16777217.0, 16777216.0
    rounded_keys = source_array(
        ee, _source(ee), ["m00", "m01"], (2,), "rounded_keys", "float_then_double",
    )
    precise_payload = source_array(
        ee, _source(ee), ["a0", "a1"], (2,), "precise_payload", "double",
    )
    key_result, key_actual, _ = _compile_raster(
        ee, precise_payload.arraySort(rounded_keys).arrayFlatten([["x", "y"]]), local,
    )
    expected_keys = _numpy_sample_reference(
        local, ["a0", "a1"], (2,), "double",
        ["m00", "m01"], (2,), "float_then_double", 0,
    )
    np.testing.assert_array_equal(key_actual, expected_keys)
    assert key_actual[:, 0].tolist() == [16777217.0, 16777219.0]
    assert any(node["process_id"] == "local_ee_to_float"
               for node in key_result["process_graph"].values())
