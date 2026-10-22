"""Pinned EE hypot syntax and independent static/raster magnitude references."""
from decimal import Decimal, localcontext
from fractions import Fraction
import math
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
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
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [7, 0], [7, 1], [0, 1], [0, 0]]]}
    arrays = {"vector-scene": {
        "x": np.array([3e30, 3e-30, -3, 0, np.nan, 3, 16777217., 10]),
        "y": np.array([4e30, 4e-30, -4, 0, 5, np.nan, 0., 20]),
        "right1": np.array([12, 0, 12, 0, 12, 12, 0., 30]),
        "right2": np.array([5, 4, 5, 0, 5, 5, 0., 40]),
    }}
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {
        "bands": {"values": ["x", "y", "right1", "right2"]}}}]
    items = {"sentinel-2-l2a": [{
        # The bbox includes one sample center that the finer scene geometry excludes.
        "id": "vector-scene", "bbox": [0, 0, 8, 1], "geometry": geometry,
        "properties": {"system:index": "vector-scene", "system:time_start": 1000,
                       "fixture": "synthetic-vector-math"},
    }]}
    grid = np.array([[index + 0.5, 0.5] for index in range(8)])
    return {"catalog": catalog, "items": items, "arrays": arrays,
            "geometry": geometry, "grid": grid}


def encode(ee, expression):
    return ee.serializer.encode(expression, for_cloud_api=False)


def decimal_hypot(left, right):
    """High precision independent reference for the Float64 hypot result."""
    with localcontext() as context:
        context.prec = 120
        x, y = Decimal.from_float(float(left)), Decimal.from_float(float(right))
        return float((x * x + y * y).sqrt())


def atan_fraction(value):
    """Alternating rational series, transformed to a ratio no larger than 1."""
    value = Fraction(value)
    sign = -1 if value < 0 else 1
    value = abs(value)
    if value > 1:
        return sign * (Fraction.from_float(math.pi / 2) - atan_fraction(1 / value))
    return sign * sum(((-1) ** index * value ** (2 * index + 1) / (2 * index + 1)
                       for index in range(100)), Fraction())


def atan2_reference(y, x):
    """Independent quadrant reduction using exact ratios and a Taylor series."""
    if y == 0:
        if x < 0:
            return math.copysign(math.pi, float(y))
        return math.copysign(0.0, float(y))
    if x == 0:
        return math.copysign(math.pi / 2, float(y))
    acute = float(atan_fraction(Fraction(abs(y), abs(x))))
    if x > 0:
        return math.copysign(acute, float(y))
    return math.copysign(math.pi - acute, float(y))


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


def test_pinned_number_hypot_serializes_and_matches_high_precision_magnitudes(ee):
    pairs = [(3, 4), (-3, -4), (0, 0), (3e30, 4e30), (3e-30, 4e-30),
             (1e308, 1e308), (2**53, 0)]
    expressions = [ee.Number(left).hypot(right) for left, right in pairs]
    expression = encode(ee, expressions)
    call = find_invocation(expression, "Number.hypot")
    assert call is not None and set(call["arguments"]) == {"left", "right"}
    actual = compile_expression(expression, [], {})["value"]
    expected = [decimal_hypot(left, right) for left, right in pairs]
    assert actual[:3] == [5.0, 5.0, 0.0]
    np.testing.assert_allclose(actual, expected, rtol=2e-15, atol=0)


def test_pinned_array_hypot_preserves_typed_shape_and_matches_independent_values(ee):
    left = [[3e30, 3e-30, -3], [0, 1e308, 2**53]]
    right = [[4e30, 4e-30, -4], [0, 1e308, 0]]
    expression = encode(ee, ee.Array(left).hypot(ee.Array(right)))
    call = find_invocation(expression, "Array.hypot")
    assert call is not None and set(call["arguments"]) == {"left", "right"}
    actual = np.asarray(compile_expression(expression, [], {})["value"])
    expected = np.array([[decimal_hypot(x, y) for x, y in zip(a, b)]
                         for a, b in zip(left, right)])
    assert actual.shape == (2, 3)
    np.testing.assert_allclose(actual, expected, rtol=2e-15, atol=0)
    np.testing.assert_allclose(actual[0], [5e30, 5e-30, 5], rtol=2e-15, atol=0)


def test_number_atan2_uses_sdk_left_x_right_y_order_in_all_quadrants(ee):
    vectors = [(3, 4), (4, 3), (-3, 4), (-3, -4), (3, -4),
               (0, 1), (1, 0), (0, -1), (-1, 0)]
    expression = encode(ee, [ee.Number(x).atan2(y) for x, y in vectors])
    call = find_invocation(expression, "Number.atan2")
    assert call is not None and set(call["arguments"]) == {"left", "right"}
    actual = compile_expression(expression, [], {})["value"]
    expected = [atan2_reference(y, x) for x, y in vectors]
    np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-15)
    assert actual[0] != actual[1]


def test_array_atan2_uses_right_as_y_and_preserves_shape(ee):
    left = [[3, 4, -3, -3, 3], [0, 1, 0, 0, -1]]
    right = [[4, 3, 4, -4, -4], [1, 0, -1, 0, 0]]
    expression = encode(ee, ee.Array(left).atan2(ee.Array(right)))
    call = find_invocation(expression, "Array.atan2")
    assert call is not None and set(call["arguments"]) == {"left", "right"}
    actual = np.asarray(compile_expression(expression, [], {})["value"])
    expected = np.asarray([[atan2_reference(y, x) for x, y in zip(a, b)]
                           for a, b in zip(left, right)])
    assert actual.shape == (2, 5)
    np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-15)


def test_image_hypot_pairs_bands_keeps_left_metadata_and_masks_per_band(ee, local):
    source = ee.Image("vector-scene").set("owner", "left")
    value = source.select(["y", "x"]).hypot(source.select(["right1", "right2"]))
    expression = encode(ee, value)
    call = find_invocation(expression, "Image.hypot")
    assert call is not None and set(call["arguments"]) == {"image1", "image2"}
    result = compile_expression(expression, local["catalog"], local["items"])
    assert result["kind"] == "image"
    assert result["bands"] == ["y", "x"]
    assert result["source_item_ids"] == ["vector-scene"]
    assert result["properties"]["owner"] == "left"
    assert "local_ee_to_float" in [node["process_id"] for node in result["process_graph"].values()]
    data, names, timed = evaluate_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries={"vector-scene": local["geometry"]},
    )
    assert names == ["y", "x"] and timed is False
    expected_y = np.asarray(
        [4e30, 4e-30, math.sqrt(160), 0, 13, np.nan, 0, np.nan], dtype=np.float32)
    expected_x = np.asarray(
        [3e30, 4, math.sqrt(34), 0, np.nan, math.sqrt(34), 16777217, np.nan], dtype=np.float32)
    np.testing.assert_allclose(data[0], expected_y, rtol=2e-7, atol=0, equal_nan=True)
    np.testing.assert_allclose(data[1], expected_x, rtol=2e-7, atol=0, equal_nan=True)
    # Float32 materialization rounds the source's nonrepresentable integer.
    assert data[1, 6] == np.float32(16777217) == 16777216

    large_and_small = source.select("x").hypot(source.select("y"))
    magnitude = compile_expression(encode(ee, large_and_small), local["catalog"], local["items"])
    large_values, _, _ = evaluate_graph(
        magnitude, local["arrays"], grid=local["grid"],
        source_geometries={"vector-scene": local["geometry"]},
    )
    np.testing.assert_array_equal(large_values[0, :2],
                                  np.asarray([5e30, 5e-30], dtype=np.float32))


def test_image_hypot_single_band_broadcast_uses_the_other_band_order(ee, local):
    source = ee.Image("vector-scene")
    right_order = source.select(["right2", "right1"])
    result = compile_expression(
        encode(ee, source.select("x").hypot(right_order)), local["catalog"], local["items"])
    data, names, _ = evaluate_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries={"vector-scene": local["geometry"]},
    )
    assert names == ["right2", "right1"]
    np.testing.assert_allclose(data[0, [0, 1, 2, 3, 5, 6]],
                               np.asarray([decimal_hypot(3e30, 5), 4, math.sqrt(34), 0,
                                           math.sqrt(34), 16777216], dtype=np.float32),
                               rtol=2e-7, atol=0)
    assert np.isnan(data[0, 4])
    np.testing.assert_allclose(data[1, [0, 1, 2, 3, 4, 5, 6]],
                               np.asarray([decimal_hypot(3e30, 12), 3e-30,
                                           math.sqrt(153), 0, np.nan,
                                           math.sqrt(153), 16777216], dtype=np.float32),
                               rtol=2e-7, atol=0, equal_nan=True)
    assert np.isnan(data[:, 7]).all()

    left_order = compile_expression(
        encode(ee, source.select(["x", "y"]).hypot(4)), local["catalog"], local["items"])
    left_values, left_names, _ = evaluate_graph(
        left_order, local["arrays"], grid=local["grid"],
        source_geometries={"vector-scene": local["geometry"]},
    )
    assert left_names == ["x", "y"]
    np.testing.assert_allclose(left_values[:, 2],
                               np.asarray([5, math.sqrt(32)], dtype=np.float32),
                               rtol=2e-7, atol=0)

    # The official Image signature promotes a bool scalar to Image.constant;
    # it participates numerically while NoData from the source remains masked.
    boolean_scalar = compile_expression(
        encode(ee, source.select("x").hypot(True)), local["catalog"], local["items"])
    bool_values, bool_names, _ = evaluate_graph(
        boolean_scalar, local["arrays"], grid=local["grid"],
        source_geometries={"vector-scene": local["geometry"]},
    )
    assert bool_names == ["x"]
    np.testing.assert_allclose(bool_values[0, [1, 2, 3, 5]],
                               np.asarray([decimal_hypot(3e-30, 1),
                                           decimal_hypot(-3, 1), 1,
                                           decimal_hypot(3, 1)], dtype=np.float32),
                               rtol=2e-7, atol=0)
    assert np.isnan(bool_values[0, 4])
    assert np.isnan(bool_values[0, 7])


def test_image_hypot_documents_dynamic_float32_output_overflow_policy(ee, local):
    source_values = np.full(8, 3.3e38)
    arrays = {"vector-scene": {
        "x": source_values.copy(), "y": source_values.copy(),
        "right1": source_values.copy(), "right2": source_values.copy(),
    }}
    casted = compile_expression(
        encode(ee, ee.Image("vector-scene").select(["x", "y"]).toFloat()),
        local["catalog"], local["items"],
    )
    cast_values, _, _ = evaluate_graph(
        casted, arrays, grid=local["grid"],
        source_geometries={"vector-scene": local["geometry"]},
    )
    float32_inputs = np.asarray(np.float32(3.3e38), dtype=np.float64)
    assert np.isfinite(float32_inputs) and np.isfinite(cast_values[:, :7]).all()
    assert np.all(cast_values[:, :7] == float32_inputs)

    reference = decimal_hypot(float32_inputs, float32_inputs)
    assert reference > float(np.finfo(np.float32).max)
    dynamic = ee.Image("vector-scene").select("x").toFloat().hypot(
        ee.Image("vector-scene").select("y").toFloat())
    result = compile_expression(encode(ee, dynamic), local["catalog"], local["items"])
    with np.errstate(over="ignore", invalid="ignore"):
        values, _, _ = evaluate_graph(
            result, arrays, grid=local["grid"],
            source_geometries={"vector-scene": local["geometry"]},
        )
    assert np.isposinf(values[0, :7]).all()
    assert np.isnan(values[0, 7])

    # Constant pairs are checked while compiling; dynamic pixel values only
    # encounter the Float32 overflow after the pixel callback is evaluated.
    overrange_constant = ee.Image.constant(3.3e38).hypot(ee.Image.constant(3.3e38))
    with pytest.raises(UnsupportedEEError, match="Float32 range"):
        compile_expression(encode(ee, overrange_constant), [], {})

