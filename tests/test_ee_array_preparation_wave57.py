"""Fixed raster-array dimensions, dot products and padding through the EE SDK."""
from copy import deepcopy
from fractions import Fraction
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_core import MAX_ARRAY_WORK
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, Source, const
from gee.compat.earthengine.raster_array_bands import (
    RasterArrayBands,
    wrap_array_bands,
)
from gee.compat.earthengine.pixel_graph import PixelCompiler
from gee.compat.earthengine.raster_array_core import wrap_array_image
from gee.compat.earthengine.raster_array_dot import invoke_raster_array_dot
from gee.compat.earthengine.raster_array_preparation import (
    invoke_raster_array_preparation,
)
from gee.compat.earthengine.raster_array_preparation_precision import (
    raster_array_precision_flags,
)
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from ee_float64_graph_reference import evaluate_float64_graph
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
COLLECTION = "sentinel-2-l2a"
BANDS = ["red", "nir", "blue", "green"]
PROJECTION = {
    "proj:code": "EPSG:32649",
    "proj:transform": [10, 0, 0, 0, -10, 10],
}
GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [4, 0], [4, 1], [0, 1], [0, 0]]],
}


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
    assets = {
        name: {"proj:code": PROJECTION["proj:code"],
               "proj:transform": list(PROJECTION["proj:transform"])}
        for name in BANDS
    }
    item = {
        "id": "scene", "bbox": [0, 0, 4, 1], "geometry": GEOMETRY,
        "assets": assets,
        "properties": {
            "system:index": "scene", "system:time_start": 1000,
            "array_tag": "kept", **PROJECTION,
        },
    }
    arrays = {"scene": {
        "red": np.array([16777217., 2., 3., 4.]),
        "nir": np.array([10., 20., np.nan, 40.]),
        "blue": np.array([.3, .5, .75, 1.]),
        "green": np.array([.2, .25, .125, .5]),
    }}
    return {
        "catalog": [{"id": COLLECTION,
                     "cube:dimensions": {"bands": {"values": BANDS}}}],
        "items": {COLLECTION: [item]},
        "arrays": arrays,
        "grid": np.array([[index + .5, .5] for index in range(4)]),
        "geometry": GEOMETRY,
    }


def compile_value(ee, value, local):
    encoded = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(encoded, local["catalog"], local["items"])


def find_invocation(value, function_name):
    if isinstance(value, dict):
        if value.get("functionName") == function_name:
            return value
        for child in value.values():
            found = find_invocation(child, function_name)
            if found is not None:
                return found
    elif isinstance(value, (tuple, list)):
        for child in value:
            found = find_invocation(child, function_name)
            if found is not None:
                return found
    return None


def resolve_references(value, scope):
    if isinstance(value, dict) and value.get("type") == "ValueRef":
        return resolve_references(scope[value["value"]], scope)
    if isinstance(value, dict):
        return {key: resolve_references(child, scope)
                for key, child in value.items() if key != "type"}
    if isinstance(value, tuple):
        return [resolve_references(child, scope) for child in value]
    if isinstance(value, list):
        return [resolve_references(child, scope) for child in value]
    return value


def evaluate(result, local, *, double=False, process_handlers=None):
    evaluator = evaluate_graph if process_handlers is not None else (
        evaluate_float64_graph if double else evaluate_graph
    )
    values, names, timed = evaluator(
        result, local["arrays"], grid=local["grid"],
        source_geometries={"scene": local["geometry"]},
        **({"process_handlers": process_handlers}
           if process_handlers is not None else {}),
    )
    assert timed is False
    return dict(zip(names, values))


def identity_unmix_handler(arguments, values):
    """Trusted sample-graph precision oracle for one identity fixture only.

    This test handler does not execute the engine or stand in for native unmix
    evidence; it isolates the array-pad precision stage around that producer.
    """
    assert set(arguments) == {"data", "spec"}
    spec = json.loads(arguments["spec"])
    coefficient = struct.unpack(
        ">d", bytes.fromhex(spec["endmembers"][0][0]),
    )[0]
    assert spec["endmembers"] == [["3ff0000000000000"]]
    assert spec["sumToOne"] is False and spec["nonNegative"] is False

    data_reference = arguments["data"]
    assert set(data_reference) == {"from_node"}
    data, names, timed = values[data_reference["from_node"]]
    assert names == ["band0"] and coefficient == 1.0
    band_axis = 1 if timed else 0
    identity_output = np.take(data, 0, axis=band_axis)
    return np.expand_dims(identity_output, axis=band_axis), ["unmix0"], timed


def _fraction_dot(left, right, *, float32_left=False, float32_right=False):
    total = 0.0
    for first, second in zip(left, right):
        if float32_left:
            first = float(np.float32(first))
        if float32_right:
            second = float(np.float32(second))
        exact_product = (Fraction.from_float(float(first))
                         * Fraction.from_float(float(second)))
        product = float(exact_product)
        total = float(Fraction.from_float(total) + Fraction.from_float(product))
    return total


def test_array_dimensions_reports_rank_zero_for_scalar_bands_and_masks(ee, local):
    source = ee.Image("scene").set("array_tag", "dimensions")
    scalar_dimensions = compile_value(
        ee, source.select(["red", "nir"]).arrayDimensions(), local,
    )
    assert scalar_dimensions["bands"] == ["red", "nir"]
    assert scalar_dimensions["properties"]["array_tag"] == "dimensions"
    scalar = evaluate(scalar_dimensions, local)
    np.testing.assert_array_equal(scalar["red"], [0, 0, 0, 0])
    np.testing.assert_array_equal(scalar["nir"], [0, 0, np.nan, 0])

    vector = source.select(["red", "nir"]).toFloat().toArray()
    dimensions = compile_value(ee, vector.arrayDimensions(), local)
    assert dimensions["bands"] == ["array"]
    np.testing.assert_array_equal(evaluate(dimensions, local)["array"],
                                  [1, 1, np.nan, 1])

    matrix = compile_value(
        ee, vector.toArray(axis=1).arrayDimensions(), local,
    )
    np.testing.assert_array_equal(evaluate(matrix, local)["array"],
                                  [2, 2, np.nan, 2])


def test_array_pad_appends_real_cells_and_keeps_mask_name_properties_and_source(ee, local):
    source = ee.Image("scene").set("array_tag", "pad")
    vector = source.select(["red", "nir"]).toFloat().toArray()
    padded = vector.arrayPad([4], pad=0.5)
    encoded = ee.serializer.encode(padded, for_cloud_api=False)
    invocation = find_invocation(encoded, "Image.arrayPad")
    assert invocation is not None
    scope = dict(encoded["scope"])
    arguments = resolve_references(invocation["arguments"], scope)
    assert arguments["lengths"] == [4]
    assert arguments["pad"] == 0.5

    flattened = padded.arrayFlatten([[
        "red", "nir", "tail0", "tail1",
    ]])
    result = compile_value(ee, flattened, local)
    assert result["bands"] == ["red", "nir", "tail0", "tail1"]
    assert result["properties"]["array_tag"] == "pad"
    assert result["source_item_ids"] == ["scene"]
    actual = evaluate(result, local)
    np.testing.assert_allclose(actual["red"], [16777216., 2., np.nan, 4.],
                               equal_nan=True)
    np.testing.assert_allclose(actual["nir"], [10., 20., np.nan, 40.],
                               equal_nan=True)
    np.testing.assert_allclose(actual["tail0"], [.5, .5, np.nan, .5],
                               equal_nan=True)
    np.testing.assert_allclose(actual["tail1"], [.5, .5, np.nan, .5],
                               equal_nan=True)

    unchanged = vector.arrayPad([0]).arrayFlatten([["red", "nir"]])
    unchanged_result = compile_value(ee, unchanged, local)
    unchanged_values = evaluate(unchanged_result, local)
    np.testing.assert_allclose(unchanged_values["red"], actual["red"],
                               equal_nan=True)
    np.testing.assert_allclose(unchanged_values["nir"], actual["nir"],
                               equal_nan=True)


def test_array_dot_product_has_float64_and_mixed_cast_fraction_references(ee, local):
    source = ee.Image("scene").set("array_tag", "dot")
    left = source.select(["red", "nir"]).toDouble().toArray()
    right = source.select(["blue", "green"]).toDouble().toArray()
    result = compile_value(ee, left.arrayDotProduct(right), local)
    assert result["bands"] == ["array"]
    assert result["properties"]["array_tag"] == "dot"
    assert result["source_item_ids"] == ["scene"]
    actual = evaluate(result, local, double=True)["array"]
    red, nir = local["arrays"]["scene"]["red"], local["arrays"]["scene"]["nir"]
    blue, green = local["arrays"]["scene"]["blue"], local["arrays"]["scene"]["green"]
    expected = np.array([
        _fraction_dot((red[index], nir[index]), (blue[index], green[index]))
        if np.isfinite(nir[index]) else np.nan
        for index in range(len(red))
    ])
    np.testing.assert_array_equal(actual, expected)

    mixed_left = source.select(["red", "nir"]).toFloat().toArray()
    mixed_right = source.select(["blue", "green"]).toDouble().toArray()
    mixed_result = compile_value(
        ee, mixed_left.arrayDotProduct(mixed_right), local,
    )
    mixed_actual = evaluate(mixed_result, local, double=True)["array"]
    mixed_expected = np.array([
        _fraction_dot((red[index], nir[index]), (blue[index], green[index]),
                      float32_left=True)
        if np.isfinite(nir[index]) else np.nan
        for index in range(len(red))
    ])
    np.testing.assert_array_equal(mixed_actual, mixed_expected)
    assert mixed_actual[0] != actual[0]

    float32_local = deepcopy(local)
    float32_local["arrays"]["scene"]["blue"] = np.array([.25, .5, .75, 1.])
    float32_local["arrays"]["scene"]["green"] = np.array([.5, .25, .125, .5])
    float_result = compile_value(
        ee,
        ee.Image("scene").select(["red", "nir"]).toFloat().toArray()
        .arrayDotProduct(
            ee.Image("scene").select(["blue", "green"]).toFloat().toArray()
        ),
        float32_local,
    )
    float_actual = evaluate(float_result, float32_local)["array"]
    float_blue = float32_local["arrays"]["scene"]["blue"]
    float_green = float32_local["arrays"]["scene"]["green"]
    float_expected = np.array([
        _fraction_dot((red[index], nir[index]),
                      (float_blue[index], float_green[index]),
                      float32_left=True, float32_right=True)
        if np.isfinite(nir[index]) else np.nan
        for index in range(len(red))
    ])
    np.testing.assert_array_equal(float_actual, float_expected)


@pytest.mark.parametrize("lengths", [[], [1, 2], [-1], [1.5], [True], [65]])
def test_array_pad_rejects_invalid_lengths(ee, local, lengths):
    vector = ee.Image("scene").select(["red", "nir"]).toArray()
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, vector.arrayPad(lengths), local)


@pytest.mark.parametrize("pad", [float("nan"), float("inf"), True, 3.5e38])
def test_array_pad_rejects_nonfinite_boolean_and_float32_overflow(ee, local, pad):
    vector = ee.Image("scene").select(["red", "nir"]).toFloat().toArray()
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, vector.arrayPad([3], pad=pad), local)


@pytest.mark.parametrize("cast,pad", [("toFloat", 1e20), ("toDouble", 3.5e38)])
def test_array_pad_rejects_values_beyond_finite_grid_constant_range(ee, local,
                                                                   cast, pad):
    vector = getattr(
        ee.Image("scene").select(["red", "nir"]), cast,
    )().toArray()
    with pytest.raises(UnsupportedEEError, match="local finite raster constant range"):
        compile_value(ee, vector.arrayPad([3], pad=pad), local)


def test_array_pad_float32_rounds_pad_at_the_explicit_cast_stage(ee, local):
    vector = ee.Image("scene").select(["red", "nir"]).toFloat().toArray()
    flat = vector.arrayPad([3], pad=16777217).arrayFlatten(
        [["red", "nir", "tail"]],
    )
    result = compile_value(ee, flat, local)
    actual = evaluate(result, local)
    np.testing.assert_array_equal(actual["tail"], [16777216., 16777216.,
                                                    np.nan, 16777216.])


def test_rank_two_padding_keeps_row_major_values_and_appends_each_axis(ee, local):
    source = ee.Image("scene").select(["red", "nir"]).toFloat().toArray()
    column = source.toArray(axis=1)
    row = ee.Image.constant(ee.Array([[1, 2]]))
    matrix = column.matrixMultiply(row)
    labels = [["r0", "r1", "r2"], ["c0", "c1", "c2"]]
    flattened = matrix.arrayPad([3, 3], pad=0.5).arrayFlatten(labels)
    result = compile_value(ee, flattened, local)
    values = evaluate(result, local)
    np.testing.assert_allclose(values["r0_c0"], [16777216., 2., np.nan, 4.],
                               equal_nan=True)
    np.testing.assert_allclose(values["r0_c1"], [33554432., 4., np.nan, 8.],
                               equal_nan=True)
    np.testing.assert_allclose(values["r0_c2"], [.5, .5, np.nan, .5],
                               equal_nan=True)
    np.testing.assert_allclose(values["r1_c0"], [10., 20., np.nan, 40.],
                               equal_nan=True)
    np.testing.assert_allclose(values["r1_c1"], [20., 40., np.nan, 80.],
                               equal_nan=True)
    np.testing.assert_allclose(values["r1_c2"], [.5, .5, np.nan, .5],
                               equal_nan=True)
    for name in ("r2_c0", "r2_c1", "r2_c2"):
        np.testing.assert_allclose(values[name], [.5, .5, np.nan, .5],
                                   equal_nan=True)


def test_array_pad_double_preserves_value_beyond_float32_exact_integer_range(ee, local):
    vector = ee.Image("scene").select(["red", "nir"]).toDouble().toArray()
    padded = vector.arrayPad([3], pad=16777217.0)
    flat = padded.arrayFlatten([["red", "nir", "tail"]])
    result = compile_value(ee, flat, local)
    actual = evaluate(result, local, double=True)
    np.testing.assert_array_equal(actual["tail"], [16777217., 16777217.,
                                                    np.nan, 16777217.])


def test_array_pad_preserves_unmix_double_until_explicit_float_cast(ee, local):
    source = ee.Image("scene").select(["red"]).set("array_tag", "unmix-pad")
    unmix = source.unmix([[1.0]])
    handlers = {"local_ee_unmix": identity_unmix_handler}

    double_flat = unmix.toArray().arrayPad([2], pad=0.1).arrayFlatten(
        [["fraction", "tail"]],
    )
    double_result = compile_value(ee, double_flat, local)
    double_processes = {
        node["process_id"] for node in double_result["process_graph"].values()
    }
    assert "local_ee_to_double" in double_processes
    assert double_result["properties"]["array_tag"] == "unmix-pad"
    double_values = evaluate(
        double_result, local, process_handlers=handlers,
    )
    np.testing.assert_array_equal(
        double_values["fraction"], [16777217., 2., 3., 4.],
    )
    assert double_values["tail"][0] == float(Fraction(1, 10))

    float_flat = unmix.toFloat().toArray().arrayPad(
        [2], pad=0.1,
    ).arrayFlatten([["fraction", "tail"]])
    float_result = compile_value(ee, float_flat, local)
    float_processes = {
        node["process_id"] for node in float_result["process_graph"].values()
    }
    assert "local_ee_to_float" in float_processes
    float_values = evaluate(
        float_result, local, process_handlers=handlers,
    )
    np.testing.assert_array_equal(
        float_values["fraction"], [16777216., 2., 3., 4.],
    )
    assert float_values["tail"][0] == float(np.float32(Fraction(1, 10)))
    assert double_values["tail"][0] != float_values["tail"][0]


def test_pad_precision_matches_producer_overrides_and_matrix_casts(local):
    translator = Translator(local["catalog"], local["items"], {})
    compiler = PixelCompiler()
    compiler.double_precision = {}
    source = Source(COLLECTION, ("scene",), ("red",))
    band = Pixel("band", (source, "red"))

    def flag(pixel, name):
        image = Image([], {})
        array = wrap_array_image(image, (1,), (pixel,), const(True), name)
        return raster_array_precision_flags(
            translator, (array,), "Image.arrayPad",
        )[0]

    unmix = Pixel("unmix_component", ((band,), "spec", 0))
    assert compiler.has_double_precision(unmix) is True
    assert flag(unmix, "unmix") is True

    for operation in (
        "classify", "trained_classify", "smile_rf_classify", "fast_distance",
    ):
        producer = Pixel(operation, (Pixel("to_double", (band,)),))
        assert compiler.has_double_precision(producer) is False
        assert flag(producer, operation) is False

    reduction = Pixel(
        "reduce_bands", ((Pixel("to_double", (band,)),), "mean"),
    )
    assert compiler.has_double_precision(reduction) is True
    assert flag(reduction, "reduce_bands") is True

    matrix_producer = Pixel("matrix_values", ((Pixel("to_double", (band,)),), "spec"))
    matrix_element = Pixel("matrix_element", (matrix_producer, 0))
    # Native matrix output cells are explicitly cast around this producer at
    # construction sites; the compiler's direct-operand scan does not infer
    # precision by recursively walking producer descriptor tuples.
    assert compiler.has_double_precision(matrix_element) is False
    assert flag(matrix_element, "matrix") is False
    explicit_float = Pixel("to_float", (matrix_element,))
    assert compiler.has_double_precision(explicit_float) is False
    assert flag(explicit_float, "matrix_float") is False


def test_array_pad_checks_total_shape_before_binding_or_allocating_cells(ee, local,
                                                                        monkeypatch):
    matrix = ee.Image.constant(ee.Array([[1, 2], [3, 4]]))
    with pytest.raises(UnsupportedEEError, match="64 cells"):
        compile_value(ee, matrix.arrayPad([9, 9]), local)

    from gee.compat.earthengine import raster_array_preparation as preparation

    source = Source(COLLECTION, ("scene",), ("red",))
    image = Image([], {}, source=source)
    vector = wrap_array_image(
        image, (2,), (Pixel("band", (source, "red")),
                      Pixel("band", (source, "red"))),
        const(True), "vector",
    )
    translator = Translator(local["catalog"], local["items"], {})
    translator.steps = MAX_ARRAY_WORK - 1
    allocated = []
    monkeypatch.setattr(preparation, "_pad_cells",
                        lambda *args: allocated.append(True))
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_raster_array_preparation(
            translator, "Image.arrayPad",
            {"image": vector, "lengths": [3]},
        )
    assert allocated == []


def test_scalar_rank_zero_and_empty_fixed_shapes_have_explicit_boundaries(local):
    translator = Translator(local["catalog"], local["items"], {})
    scalar = wrap_array_image(
        Image([], {}), (), (const(7),), const(True), "scalar_array",
    )
    dimensions = invoke_raster_array_preparation(
        translator, "Image.arrayDimensions", {"input": scalar},
    )
    assert dimensions.bands == [("scalar_array", const(0))]
    with pytest.raises(UnsupportedEEError, match="rank-1..8"):
        invoke_raster_array_preparation(
            translator, "Image.arrayPad", {"image": scalar, "lengths": []},
        )
    with pytest.raises(UnsupportedEEError, match="positive integers"):
        wrap_array_image(Image([], {}), (0,), (), const(True), "empty")


def test_array_pad_rank_eight_and_64_cell_boundaries_are_real_fixed_shapes(local):
    translator = Translator(local["catalog"], local["items"], {})
    source = Source(COLLECTION, ("scene",), ("red",))
    image = Image([], {}, source=source)
    cell = Pixel("band", (source, "red"))
    rank_eight = wrap_array_image(
        image, (1,) * 8, (cell,), const(True), "rank_eight",
    )
    expanded = invoke_raster_array_preparation(
        translator, "Image.arrayPad",
        {"image": rank_eight, "lengths": [2, 1, 1, 1, 1, 1, 1, 1], "pad": 9},
    )
    assert expanded.shape == (2, 1, 1, 1, 1, 1, 1, 1)
    assert expanded.cells[0] is cell
    assert expanded.cells[1].op == "to_float"

    maximum = wrap_array_image(image, (1,), (cell,), const(True), "maximum")
    expanded = invoke_raster_array_preparation(
        translator, "Image.arrayPad",
        {"image": maximum, "lengths": [64]},
    )
    assert expanded.shape == (64,)
    assert len(expanded.cells) == 64


def test_array_dot_product_rejects_scene_mismatch_and_asset_grid_mismatch(ee, local):
    source = ee.Image("scene")
    left = source.select(["red", "nir"]).toDouble().toArray()
    right = source.select(["blue", "green"]).toDouble().toArray()
    # A repeated source identity is admitted after asset projections are checked.
    assert compile_value(ee, left.arrayDotProduct(right), local)["source_item_ids"] == ["scene"]

    other_item = deepcopy(local["items"][COLLECTION][0])
    other_item["id"] = "other-scene"
    other_item["properties"]["system:index"] = "other-scene"
    local["items"][COLLECTION].append(other_item)
    other_arrays = deepcopy(local["arrays"]["scene"])
    local["arrays"]["other-scene"] = other_arrays
    other = ee.Image("other-scene").select(["blue", "green"]).toDouble().toArray()
    with pytest.raises(UnsupportedEEError, match="scene identities"):
        compile_value(ee, left.arrayDotProduct(other), local)

    local["items"][COLLECTION][0]["assets"]["green"]["proj:transform"][2] += 5
    with pytest.raises(UnsupportedEEError, match="grid"):
        compile_value(ee, left.arrayDotProduct(right), local)


def test_array_pad_requires_concrete_single_scene_grid(ee, local):
    source_free = ee.Image.constant(1).toArray().arrayPad([2])
    with pytest.raises(UnsupportedEEError, match="one concrete raster source"):
        compile_value(ee, source_free, local)

    other_item = deepcopy(local["items"][COLLECTION][0])
    other_item["id"] = "other-scene"
    other_item["properties"]["system:index"] = "other-scene"
    local["items"][COLLECTION].append(other_item)
    local["arrays"]["other-scene"] = deepcopy(local["arrays"]["scene"])
    first = ee.Image("scene").select(["red"])
    second = ee.Image("other-scene").select(["red"])
    mixed_sources = first.add(second).toArray().arrayPad([2])
    with pytest.raises(UnsupportedEEError, match="one concrete raster source"):
        compile_value(ee, mixed_sources, local)


def test_array_dot_product_requires_paired_rank_one_equal_length_vectors(ee, local):
    scalar = ee.Image("scene").select(["red"]).toArray()
    vector = ee.Image("scene").select(["red", "nir"]).toArray()
    matrix = vector.toArray(axis=1)
    with pytest.raises(UnsupportedEEError, match="rank-1"):
        compile_value(ee, matrix.arrayDotProduct(matrix), local)
    with pytest.raises(UnsupportedEEError, match="equal lengths"):
        compile_value(ee, scalar.arrayDotProduct(vector), local)


def test_array_dot_product_uses_existing_positional_single_band_broadcast_policy(local):
    translator = Translator(local["catalog"], local["items"], {})
    source = Source(COLLECTION, ("scene",), tuple(BANDS))
    image = Image([], {"bundle_tag": "left"}, source=source)

    def array(name, source_band):
        return wrap_array_image(
            image, (1,), (Pixel("band", (source, source_band)),),
            const(True), name,
        )

    left = wrap_array_bands(
        translator, image,
        (array("left0", "red"), array("left1", "nir")),
    )
    right = wrap_array_bands(
        translator, image,
        (array("right0", "blue"), array("right1", "green")),
    )
    single = array("single", "blue")
    assert isinstance(left, RasterArrayBands)

    def output_names(first, second):
        result = invoke_raster_array_dot(
            translator, "Image.arrayDotProduct",
            {"image1": first, "image2": second},
        )
        return [name for name, _pixel in result.bands]

    assert output_names(left, right) == ["left0", "left1"]
    assert output_names(left, single) == ["left0", "left1"]
    assert output_names(single, right) == ["right0", "right1"]
