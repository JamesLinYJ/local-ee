"""Strict SDK contracts and resource boundaries for raster array cat/repeat."""
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine import raster_array_concatenation as concatenation
from gee.compat.earthengine.array_core import MAX_ARRAY_WORK
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, Source, const
from gee.compat.earthengine.raster_array_core import wrap_array_image
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
BANDS = list("abcdefghijkl")
HIGH_BANDS = [f"band_{index:02d}" for index in range(65)]


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
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [3, 0], [3, 1], [0, 1], [0, 0]]]}
    bands = {
        name: np.asarray([index + 1., index + 2., index + 3.], dtype=np.float64)
        for index, name in enumerate(BANDS)
    }
    return {
        "catalog": [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": BANDS}}}],
        "items": {"sentinel-2-l2a": [{
            "id": "concat-parameters", "bbox": [0, 0, 3, 1], "geometry": geometry,
            "properties": {"system:index": "concat-parameters", "system:time_start": 1000},
        }]},
        "arrays": {"concat-parameters": bands},
        "grid": np.array([[x + .5, .5] for x in range(3)]),
        "geometry": geometry,
    }


@pytest.fixture
def high_local():
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    arrays = {"concat-large": {
        name: np.asarray([index + 1.], dtype=np.float64)
        for index, name in enumerate(HIGH_BANDS)
    }}
    return {
        "catalog": [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": HIGH_BANDS}}}],
        "items": {"sentinel-2-l2a": [{
            "id": "concat-large", "bbox": [0, 0, 1, 1], "geometry": geometry,
            "properties": {"system:index": "concat-large", "system:time_start": 1000},
        }]},
        "arrays": arrays,
        "grid": np.array([[.5, .5]]),
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
    elif isinstance(value, (tuple, list)):
        for child in value:
            found = find_invocation(child, name)
            if found is not None:
                return found
    return None


def compile_value(ee, value, local):
    return compile_expression(encode(ee, value), local["catalog"], local["items"])


def source_array(ee, image, bands, shape):
    value = image.select(bands).toFloat().toArray()
    return value.arrayReshape(ee.Image.constant(ee.Array(list(shape))), len(shape))


def compile_flat(ee, expression, local):
    result = compile_value(ee, expression, local)
    values, names, timed = evaluate_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries={"concat-large": local["geometry"],
                           "concat-parameters": local["geometry"]},
    )
    assert timed is False
    return result, values, names


@pytest.mark.parametrize("algorithm,missing,unknown", [
    ("Image.arrayCat", "axis", "extra"),
    ("Image.arrayRepeat", "copies", "extra"),
])
def test_sdk_serialized_invocations_reject_missing_and_unknown_arguments(
        ee, local, algorithm, missing, unknown):
    image = ee.ImageCollection("sentinel-2-l2a").first()
    array = source_array(ee, image, ["a", "b"], (2,))
    if algorithm == "Image.arrayCat":
        expression = array.arrayCat(array, 0).arrayFlatten([["a", "b", "c", "d"]])
    else:
        expression = array.arrayRepeat(0, ee.Image.constant(2)).arrayFlatten([["a", "b", "c", "d"]])
    encoded = encode(ee, expression)
    invocation = find_invocation(encoded, algorithm)
    assert invocation is not None
    assert set(invocation["arguments"]) == (
        {"image1", "image2", "axis"} if algorithm == "Image.arrayCat"
        else {"input", "axis", "copies"}
    )

    bad_missing = deepcopy(encoded)
    del find_invocation(bad_missing, algorithm)["arguments"][missing]
    with pytest.raises(UnsupportedEEError, match="requires"):
        compile_expression(bad_missing, local["catalog"], local["items"])

    bad_unknown = deepcopy(encoded)
    find_invocation(bad_unknown, algorithm)["arguments"][unknown] = 7
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(bad_unknown, local["catalog"], local["items"])


@pytest.mark.parametrize("axis", [True, 1.5, 2])
def test_array_cat_rejects_boolean_fractional_and_out_of_rank_axes(ee, local, axis):
    image = ee.ImageCollection("sentinel-2-l2a").first()
    array = source_array(ee, image, ["a", "b"], (2,))
    value = array.arrayCat(array, axis).arrayFlatten([["a", "b", "c", "d"]])
    with pytest.raises(UnsupportedEEError, match="axis"):
        compile_value(ee, value, local)


def test_array_cat_requires_typed_arrays_with_same_rank_and_matching_other_axes(ee, local):
    image = ee.ImageCollection("sentinel-2-l2a").first()
    vector = source_array(ee, image, ["a", "b"], (2,))
    ordinary = image.select("a")
    value = vector.arrayCat(ordinary, 0).arrayFlatten([["a", "b", "c"]])
    with pytest.raises(UnsupportedEEError, match="RasterArrayImage"):
        compile_value(ee, value, local)

    left = source_array(ee, image, ["a", "b", "c", "d"], (2, 2))
    right = source_array(ee, image, ["e", "f", "g", "h", "i", "j"], (3, 2))
    mismatched = left.arrayCat(right, 1).arrayFlatten([
        ["r0", "r1"], ["c0", "c1", "c2", "c3"],
    ])
    with pytest.raises(UnsupportedEEError, match="matching non-concatenated dimensions"):
        compile_value(ee, mismatched, local)

    wrong_rank = vector.arrayCat(left, 0).arrayFlatten([["cell"]])
    with pytest.raises(UnsupportedEEError, match="same rank"):
        compile_value(ee, wrong_rank, local)


@pytest.mark.parametrize("axis", [True, 1.5, 1])
def test_array_repeat_rejects_boolean_fractional_and_out_of_rank_axes(ee, local, axis):
    image = ee.ImageCollection("sentinel-2-l2a").first()
    array = source_array(ee, image, ["a"], (1,))
    value = array.arrayRepeat(axis, ee.Image.constant(2)).arrayFlatten([["copy"]])
    with pytest.raises(UnsupportedEEError, match="axis"):
        compile_value(ee, value, local)


@pytest.mark.parametrize("copies", [
    pytest.param(lambda ee, image: ee.Image.constant(0), id="zero"),
    pytest.param(lambda ee, image: ee.Image.constant(-2), id="negative"),
    pytest.param(lambda ee, image: ee.Image.constant(2.5), id="fractional"),
    pytest.param(lambda ee, image: ee.Image.constant(True), id="boolean"),
    pytest.param(lambda ee, image: ee.Image.constant(2).updateMask(ee.Image.constant(0)), id="masked"),
    pytest.param(lambda ee, image: ee.Image.constant([2, 2]), id="multiband"),
    pytest.param(lambda ee, image: image.select("a"), id="source-backed"),
    pytest.param(lambda ee, image: ee.Image.constant(2).clip(ee.Geometry.Rectangle([0, 0, 1, 1])), id="footprint"),
])
def test_array_repeat_rejects_unproven_copies_images(ee, local, copies):
    image = ee.ImageCollection("sentinel-2-l2a").first()
    array = source_array(ee, image, ["a", "b"], (2,))
    count_image = copies(ee, image)
    value = array.arrayRepeat(0, count_image).arrayFlatten([["copy0", "copy1"]])
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, value, local)


def test_array_repeat_rejects_mapped_and_nodata_count_ir_without_pixel_proof():
    source = Source("sentinel-2-l2a", ("concat-parameters",), ("a",))
    cell = Pixel("band", (source, "a"))
    array = wrap_array_image(Image([("a", cell)], {}, source), (1,), (cell,), const(True))
    for count_image in (
        Image([("count", const(2))], {}, mapped=True),
        Image([("count", const(2))], {}, footprint={"type": "Polygon"}),
        Image([("count", const(None))], {}),
        Image([("count", const(2))], {}, source=source),
    ):
        with pytest.raises(UnsupportedEEError):
            concatenation.invoke_raster_concatenation(
                Translator([], {}, {}), "Image.arrayRepeat",
                {"input": array, "axis": 0, "copies": count_image},
            )


def test_array_cat_keeps_left_metadata_uses_source_fallback_and_preserves_masks_and_inputs():
    source = Source("sentinel-2-l2a", ("concat-parameters",), ("a", "b"))
    first = Pixel("band", (source, "a"))
    second = Pixel("band", (source, "b"))
    left_image = Image([("left", first)], {"owner": "left"})
    right_image = Image([("right", second)], {"owner": "right"}, source)
    left = wrap_array_image(left_image, (1,), (first,), const(False), "left-array")
    right = wrap_array_image(right_image, (1,), (second,), const(True), "right-array")
    left_before, right_before = left.cells, right.cells

    result = concatenation.invoke_raster_concatenation(
        Translator([], {}, {}), "Image.arrayCat",
        {"image1": left, "image2": right, "axis": 0.0},
    )
    assert result.shape == (2,)
    assert result.cells == (first, second)
    assert result.mask.op == "constant" and result.mask.args == (False,)
    assert result.name == "left-array"
    assert result.image.source == source
    assert result.image.props == {"owner": "left"}
    assert left.cells == left_before and right.cells == right_before

    nodata = wrap_array_image(left_image, (1,), (first,), const(None))
    nodata_result = concatenation.invoke_raster_concatenation(
        Translator([], {}, {}), "Image.arrayCat",
        {"image1": nodata, "image2": right, "axis": 0},
    )
    assert nodata_result.mask.op == "constant" and nodata_result.mask.args == (None,)


def test_array_repeat_preserves_input_pixels_metadata_mask_and_source():
    source = Source("sentinel-2-l2a", ("concat-parameters",), ("a", "b"))
    first, second = Pixel("band", (source, "a")), Pixel("band", (source, "b"))
    image = Image([("a", first), ("b", second)], {"owner": "repeat"}, source)
    original = wrap_array_image(image, (2,), (first, second), const(False), "feature")
    cells_before, mask_before, props_before = original.cells, original.mask, dict(image.props)
    result = concatenation.invoke_raster_concatenation(
        Translator([], {}, {}), "Image.arrayRepeat",
        {"input": original, "axis": 0, "copies": Image([("count", const(3))], {})},
    )

    assert result.shape == (6,)
    assert result.cells == (first, second, first, second, first, second)
    assert result.mask is mask_before and result.image.source == source
    assert result.image.props == props_before
    assert original.cells == cells_before and image.props == props_before


def test_rank_eight_and_64_cell_concatenation_boundaries_are_real_sdk_compilations(ee, high_local):
    image = ee.ImageCollection("sentinel-2-l2a").first()
    left = source_array(ee, image, [HIGH_BANDS[0]], (1,)).arrayReshape(
        ee.Image.constant(ee.Array([1] * 8)), 8)
    right = source_array(ee, image, [HIGH_BANDS[1]], (1,)).arrayReshape(
        ee.Image.constant(ee.Array([1] * 8)), 8)
    cube = left.arrayCat(right, 7)
    labels = [[f"axis{axis}_{index}" for index in range(2 if axis == 7 else 1)]
              for axis in range(8)]
    result, actual, names = compile_flat(
        ee, cube.arrayFlatten(labels, separator="_"), high_local)
    assert result["bands"] == names == [
        "axis0_0_axis1_0_axis2_0_axis3_0_axis4_0_axis5_0_axis6_0_axis7_0",
        "axis0_0_axis1_0_axis2_0_axis3_0_axis4_0_axis5_0_axis6_0_axis7_1",
    ]
    np.testing.assert_array_equal(actual, [[1.], [2.]])

    source = ee.ImageCollection("sentinel-2-l2a").first()
    one_cell = source.select(HIGH_BANDS[0]).toArray().toArray(axis=1)
    first = one_cell.matrixMultiply(ee.Image.constant(ee.Array([[1] * 32])))
    second = one_cell.matrixMultiply(ee.Image.constant(ee.Array([[2] * 32])))
    sixty_four = first.arrayCat(second, 1)
    # Read the supported 64-cell result through a dynamic pixel so the output
    # graph measures the new array path rather than 64 redundant output bands.
    length = sixty_four.arrayLength(1).add(source.select(HIGH_BANDS[0])).rename("length_plus_sample")
    result, actual, names = compile_flat(ee, length, high_local)
    assert names == result["bands"] == ["length_plus_sample"]
    np.testing.assert_array_equal(actual, [[65.]])

    over = one_cell.matrixMultiply(ee.Image.constant(ee.Array([[1] * 32]))).arrayCat(
        one_cell.matrixMultiply(ee.Image.constant(ee.Array([[2] * 33]))), 1)
    with pytest.raises(UnsupportedEEError, match="64"):
        compile_value(ee, over.arrayFlatten([
            ["row"], [f"v{index}" for index in range(65)],
        ]), high_local)

    pair = source.select(HIGH_BANDS[:2]).toArray()
    repeated = pair.arrayRepeat(0, ee.Image.constant(32))
    flat = repeated.arrayFlatten([[f"copy{index}" for index in range(64)]])
    result, actual, names = compile_flat(ee, flat, high_local)
    assert len(names) == len(result["bands"]) == 64
    np.testing.assert_array_equal(actual[:, 0], np.tile([1., 2.], 32))
    with pytest.raises(UnsupportedEEError, match="64"):
        compile_value(
            ee, pair.arrayRepeat(0, ee.Image.constant(33)).arrayFlatten(
                [[f"copy{index}" for index in range(66)]]), high_local,
        )


def test_deep_array_expression_hits_the_real_500_process_graph_cap(ee, high_local):
    image = ee.ImageCollection("sentinel-2-l2a").first()
    base = image.select(HIGH_BANDS[:32]).toArray().arrayCat(
        image.select(HIGH_BANDS[32:64]).toArray(), 0)
    chained = base
    for _ in range(10):
        chained = chained.add(base)
    expression = chained.arrayFlatten([[f"v{index}" for index in range(64)]])
    with pytest.raises(UnsupportedEEError, match="500 nodes"):
        compile_value(ee, expression, high_local)


def _raw_arrays():
    source = Source("sentinel-2-l2a", ("concat-parameters",), ("a", "b"))
    first, second = Pixel("band", (source, "a")), Pixel("band", (source, "b"))
    image = Image([("a", first), ("b", second)], {}, source)
    array = wrap_array_image(image, (2,), (first, second), const(True))
    return array, Image([("copies", const(2))], {})


@pytest.mark.parametrize("operation,phase", [
    ("Image.arrayCat", "result"),
    ("Image.arrayRepeat", "result"),
    ("Image.arrayRepeat", "count"),
])
def test_shared_work_preflight_runs_before_result_array_construction(monkeypatch, operation, phase):
    array, copies = _raw_arrays()
    translator = Translator([], {}, {})

    def output_forbidden(*args, **kwargs):
        raise AssertionError("output wrapper ran before shared work was precharged")

    monkeypatch.setattr(concatenation, "wrap_array_image", output_forbidden)
    if operation == "Image.arrayCat":
        args = {"image1": array, "image2": array, "axis": 0}
        translator.steps = MAX_ARRAY_WORK - 1
        expected_steps = MAX_ARRAY_WORK - 1
    elif phase == "count":
        args = {"input": array, "axis": 0, "copies": copies}
        translator.steps = MAX_ARRAY_WORK
        expected_steps = MAX_ARRAY_WORK
    else:
        args = {"input": array, "axis": 0, "copies": copies}
        translator.steps = MAX_ARRAY_WORK - 5
        expected_steps = MAX_ARRAY_WORK - 4  # The one-node constant proof is charged first.

    with pytest.raises(UnsupportedEEError, match="work budget"):
        concatenation.invoke_raster_concatenation(translator, operation, args)
    assert translator.steps == expected_steps


def test_rank_zero_array_values_are_rejected_by_sdk_operations():
    from gee.compat.earthengine.raster_array_core import RasterArrayImage

    pixel = const(3)
    scalar = RasterArrayImage(Image([], {}), (), (pixel,), const(True), "scalar")
    with pytest.raises(UnsupportedEEError, match="rank-1..8"):
        concatenation.invoke_raster_concatenation(
            Translator([], {}, {}), "Image.arrayRepeat",
            {"input": scalar, "axis": 0, "copies": Image([("count", const(2))], {})},
        )
