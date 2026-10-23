"""Fixed-shape raster-array value semantics through the pinned Python SDK."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from ee_float64_graph_reference import evaluate_float64_graph
from test_ee_translate import arrays as sample_arrays
from test_ee_translate import evaluate_graph, local as local_fixture


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def compile_value(ee, value, local):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, *local)


def evaluated_bands(result, rasters, *, float64_spi=False):
    evaluator = evaluate_float64_graph if float64_spi else evaluate_graph
    values, names, timed = evaluator(result, rasters)
    if timed:
        assert values.shape[0] == 1, "these fixtures contain one output observation"
        values = values[0]
    return dict(zip(names, values))


def find_invocation_arguments(value, function_name):
    if isinstance(value, dict):
        if value.get("functionName") == function_name:
            return value["arguments"]
        for child in value.values():
            found = find_invocation_arguments(child, function_name)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for child in value:
            found = find_invocation_arguments(child, function_name)
            if found is not None:
                return found
    return None


def test_to_array_axes_lengths_and_multiscene_multiband_values(ee, local_fixture, sample_arrays):
    # Both a and b contribute to each mean band before the two bands become one
    # fixed-shape array pixel.
    source = ee.ImageCollection("sentinel-2-l2a").limit(2).mean().select(["red", "nir"])
    vector = source.toArray()
    flat = compile_value(ee, vector.arrayFlatten([["red", "nir"]]), local_fixture)
    actual = evaluated_bands(flat, sample_arrays)
    np.testing.assert_allclose(actual["red"], [1, 3])
    np.testing.assert_allclose(actual["nir"], [5, 3])
    assert flat["source_item_ids"] == ["a", "b"]

    # For a rank-1 array image, axis 1 appends a singleton dimension and axis
    # 0 leaves the shape unchanged. Flattening gives the same scalar values.
    extended = vector.toArray(axis=1).arrayFlatten([["red", "nir"], ["column"]])
    extended_result = compile_value(ee, extended, local_fixture)
    extended_bands = evaluated_bands(extended_result, sample_arrays)
    np.testing.assert_allclose(extended_bands["red_column"], [1, 3])
    np.testing.assert_allclose(extended_bands["nir_column"], [5, 3])

    unchanged = compile_value(
        ee, vector.toArray(axis=0).arrayFlatten([["red", "nir"]]), local_fixture
    )
    unchanged_bands = evaluated_bands(unchanged, sample_arrays)
    np.testing.assert_allclose(unchanged_bands["red"], [1, 3])
    np.testing.assert_allclose(unchanged_bands["nir"], [5, 3])

    scalar_length = compile_value(ee, vector.arrayLength(0), local_fixture)
    np.testing.assert_allclose(next(iter(evaluated_bands(scalar_length, sample_arrays).values())), [2, 2])
    vector_lengths = compile_value(
        ee, vector.arrayLengths().arrayFlatten([["axis_0"]]), local_fixture
    )
    np.testing.assert_allclose(evaluated_bands(vector_lengths, sample_arrays)["axis_0"], [2, 2])

    matrix_lengths = compile_value(
        ee,
        vector.toArray(axis=1).arrayLengths().arrayFlatten([["rows", "columns"]]),
        local_fixture,
    )
    matrix_length_bands = evaluated_bands(matrix_lengths, sample_arrays)
    np.testing.assert_allclose(matrix_length_bands["rows"], [2, 2])
    np.testing.assert_allclose(matrix_length_bands["columns"], [1, 1])


def test_to_array_mask_is_shared_and_length_operations_keep_it(ee, local_fixture, sample_arrays):
    source = ee.Image("b").select(["red", "nir"])
    vector = source.toArray()
    flat = compile_value(ee, vector.arrayFlatten([["red", "nir"]]), local_fixture)
    actual = evaluated_bands(flat, sample_arrays)
    np.testing.assert_allclose(actual["red"], [1, np.nan], equal_nan=True)
    np.testing.assert_allclose(actual["nir"], [9, np.nan], equal_nan=True)

    length = compile_value(ee, vector.arrayLength(0), local_fixture)
    length_values = next(iter(evaluated_bands(length, sample_arrays).values()))
    np.testing.assert_allclose(length_values, [2, np.nan], equal_nan=True)

    lengths = compile_value(
        ee, vector.arrayLengths().arrayFlatten([["axis_0"]]), local_fixture
    )
    np.testing.assert_allclose(
        evaluated_bands(lengths, sample_arrays)["axis_0"], [2, np.nan], equal_nan=True
    )


def test_array_metadata_and_constant_matrix_bind_to_the_real_source_grid(
    ee, local_fixture, sample_arrays
):
    source = ee.Image("a").set("array_source", "scene-a").select(["red", "nir"])
    flattened = compile_value(
        ee, source.toArray().arrayFlatten([["red", "nir"]]), local_fixture
    )
    assert flattened["properties"]["array_source"] == "scene-a"
    assert flattened["source_item_ids"] == ["a"]

    # The left operand is a constant matrix. Its product takes the finite grid
    # and whole-array mask from the right operand, while properties follow image1.
    matrix = ee.Image.constant(ee.Array([[1, 2], [3, 4]])).set("operand", "left")
    column = ee.Image("b").set("operand", "right").select(["red", "nir"])
    product = matrix.matrixMultiply(column.toArray().toArray(axis=1))
    result = compile_value(
        ee, product.arrayProject([0]).arrayFlatten([["weighted_red", "weighted_nir"]]),
        local_fixture,
    )
    assert result["properties"]["operand"] == "left"
    assert result["source_item_ids"] == ["b"]
    actual = evaluated_bands(result, sample_arrays)
    np.testing.assert_allclose(actual["weighted_red"], [19, np.nan], equal_nan=True)
    np.testing.assert_allclose(actual["weighted_nir"], [39, np.nan], equal_nan=True)


def test_same_shape_array_image_arithmetic_matches_hand_values(ee, local_fixture, sample_arrays):
    image = ee.Image("a")
    red_nir = image.select(["red", "nir"]).toArray()
    blue_green = image.select(["blue", "green"]).toArray()
    result = compile_value(
        ee,
        red_nir.add(blue_green).arrayFlatten([["red_plus_blue", "nir_plus_green"]]),
        local_fixture,
    )
    actual = evaluated_bands(result, sample_arrays)
    np.testing.assert_allclose(actual["red_plus_blue"], [1.1, 3.2])
    np.testing.assert_allclose(actual["nir_plus_green"], [1.2, 3.4])


def test_array_image_arithmetic_rejects_scalar_broadcast_and_unequal_shapes(
    ee, local_fixture
):
    image = ee.Image("a")
    vector = image.select(["red", "nir"]).toArray()
    with pytest.raises(UnsupportedEEError, match="single-band fixed-shape RasterArrayImage"):
        compile_value(ee, vector.add(1), local_fixture)

    other_shape = image.select(["red", "nir", "blue"]).toArray()
    with pytest.raises(UnsupportedEEError, match="identical shapes"):
        compile_value(ee, vector.add(other_shape), local_fixture)


def test_dynamic_collection_arrays_remain_explicitly_unsupported(ee, local_fixture):
    expression = ee.ImageCollection("sentinel-2-l2a").limit(2).toArray()
    with pytest.raises(
        UnsupportedEEError,
        match=r"Unsupported Earth Engine algorithm: ImageCollection\.toArray",
    ):
        compile_value(ee, expression, local_fixture)


def test_array_shape_unknown_argument_work_and_nonfinite_bounds(ee, local_fixture):
    oversized_axis = ee.Image.constant(ee.Array([1] * 65))
    with pytest.raises(UnsupportedEEError, match="64"):
        compile_value(ee, oversized_axis, local_fixture)

    vector = ee.Image("a").select(["red", "nir"]).toArray()
    encoded = deepcopy(ee.serializer.encode(vector, for_cloud_api=False))
    arguments = find_invocation_arguments(encoded, "Image.toArray")
    assert arguments is not None
    arguments["ignored"] = 1
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(encoded, *local_fixture)

    wide = ee.Image.constant(ee.Array([1] * 64))
    layer = [wide] * 512
    while len(layer) > 1:
        layer = [layer[index].add(layer[index + 1]) for index in range(0, len(layer), 2)]
    with pytest.raises(UnsupportedEEError, match="work budget"):
        compile_value(ee, layer[0], local_fixture)

    nonfinite = ee.Image.constant(ee.Array([float("nan")]))
    with pytest.raises(UnsupportedEEError, match="finite real numbers"):
        compile_value(ee, nonfinite, local_fixture)

    with pytest.raises(UnsupportedEEError, match="inner dimensions must match"):
        compile_value(
            ee,
            ee.Image.constant(ee.Array([[1, 2], [3, 4]])).matrixMultiply(
                ee.Image.constant(ee.Array([[1, 2, 3]]))
            ),
            local_fixture,
        )

    with pytest.raises(UnsupportedEEError, match="arrayFlatten or arrayGet"):
        compile_value(ee, ee.Image("a").select(["red", "nir"]).toArray(), local_fixture)


@pytest.mark.parametrize("operation", ["add", "subtract", "multiply", "divide"])
def test_generic_float64_array_binary_arithmetic_uses_native_scalarization(
    ee, local_fixture, sample_arrays, operation,
):
    arrays = deepcopy(sample_arrays)
    arrays["a"]["red"] = np.array([2**24 + 1., 4., 6., 3.], dtype=np.float64)
    arrays["a"]["nir"] = np.array([2**24 + 3., 8., np.nan, 5.], dtype=np.float64)
    arrays["a"]["blue"] = np.array([2., 2., 3., 0.], dtype=np.float64)
    arrays["a"]["green"] = np.array([3., np.nan, 4., 0.], dtype=np.float64)

    source = ee.Image("a").set("array_source", "double-fixture")
    left = source.select(["red", "nir"]).toDouble().toArray()
    right = source.select(["blue", "green"]).toDouble().toArray()
    value = getattr(left, operation)(right).arrayFlatten([["red_out", "nir_out"]])
    result = compile_value(ee, value, local_fixture)

    assert result["bands"] == ["red_out", "nir_out"]
    assert result["properties"]["array_source"] == "double-fixture"
    assert result["source_item_ids"] == ["a"]
    specs = [
        json.loads(node["arguments"]["spec"])
        for node in result["process_graph"].values()
        if node["process_id"] == "local_ee_integer_values"
    ]
    assert [spec["op"] for spec in specs] == [operation, operation]
    assert all(spec["operands"] == [{"band": 0}, {"band": 1}] for spec in specs)
    assert not any(node["process_id"] == "local_ee_to_float"
                   for node in result["process_graph"].values())

    left_values = np.array([
        arrays["a"]["red"], arrays["a"]["nir"],
    ], dtype=np.float64)
    right_values = np.array([
        arrays["a"]["blue"], arrays["a"]["green"],
    ], dtype=np.float64)
    functions = {
        "add": np.add,
        "subtract": np.subtract,
        "multiply": np.multiply,
        "divide": np.divide,
    }
    with np.errstate(all="ignore"):
        if operation == "divide":
            expected = np.divide(
                left_values, right_values,
                out=np.zeros_like(left_values), where=right_values != 0,
            )
        else:
            expected = functions[operation](left_values, right_values)
    # ArrayImage has one shared mask: a missing cell in either vector masks
    # every flattened output component at that pixel.
    expected[:, 1:3] = np.nan
    actual = evaluated_bands(result, arrays, float64_spi=True)
    np.testing.assert_allclose(actual["red_out"], expected[0], rtol=0, atol=0,
                               equal_nan=True)
    np.testing.assert_allclose(actual["nir_out"], expected[1], rtol=0, atol=0,
                               equal_nan=True)
