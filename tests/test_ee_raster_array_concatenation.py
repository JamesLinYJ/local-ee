"""SDK raster-array concatenation and repetition with independent NumPy maps."""
from pathlib import Path
import itertools

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
BANDS = list("abcdefghijkl")


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
    values = {
        "a": [16777217, 2, 3, 4, 5], "b": [10, 20, 30, 40, 50],
        "c": [100, 200, 300, 400, 500], "d": [1000, 2000, 3000, 4000, 5000],
        "e": [7, 8, 9, 10, 11], "f": [70, 80, 90, 100, 110],
        "g": [700, 800, 900, 1000, 1100], "h": [7000, 8000, 9000, 10000, 11000],
        "i": [17, 18, 19, 20, 21], "j": [170, 180, 190, 200, 210],
        "k": [1700, 1800, 1900, 2000, 2100], "l": [17000, 18000, 19000, 20000, 21000],
    }
    # Different input arrays fail validity at different pixels. Concatenation
    # must combine both whole-array masks, while the last center is outside
    # the scene geometry but inside its bbox.
    values["b"][1] = np.nan
    values["f"][3] = np.nan
    arrays = {"concat-scene": {name: np.asarray(data, dtype=np.float64)
                               for name, data in values.items()}}
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": BANDS}}}]
    items = {"sentinel-2-l2a": [{
        "id": "concat-scene", "bbox": [0, 0, 5, 1], "geometry": geometry,
        "properties": {"system:index": "concat-scene", "system:time_start": 1000,
                       "synthetic": True},
    }]}
    return {"catalog": catalog, "items": items, "arrays": arrays,
            "geometry": geometry, "grid": np.array([[x + 0.5, 0.5] for x in range(5)])}


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


def compile_flat(ee, expression, local):
    result = compile_expression(encode(ee, expression), local["catalog"], local["items"])
    assert result["kind"] == "image"
    values, names, timed = evaluate_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries={"concat-scene": local["geometry"]},
    )
    assert timed is False
    return result, values, names


def source_array(ee, image, bands, shape):
    array = image.select(bands).toFloat().toArray()
    lengths = ee.Image.constant(ee.Array(list(shape)))
    return array.arrayReshape(lengths, len(shape))


def independent_cells(local, bands, shape):
    source = local["arrays"]["concat-scene"]
    values = np.stack([source[band].astype(np.float32).astype(np.float64)
                       for band in bands], axis=-1)
    return values.reshape((len(local["grid"]), *shape))


def assert_expected(result_values, expected, local, input_bands):
    expected = expected.reshape((len(local["grid"]), -1)).T
    valid = np.ones(len(local["grid"]), dtype=bool)
    for band in input_bands:
        valid &= np.isfinite(local["arrays"]["concat-scene"][band])
    valid[-1] = False  # source geometry excludes the last bbox-covered center
    expected[:, ~valid] = np.nan
    np.testing.assert_allclose(result_values, expected, rtol=0, atol=0, equal_nan=True)


@pytest.mark.parametrize("axis,left_bands,left_shape,right_bands,right_shape,labels", [
    (0, ["a", "b"], (1, 2), ["c", "d", "e", "f"], (2, 2),
     [["r0", "r1", "r2"], ["c0", "c1"]]),
    (1, ["a", "b", "c", "d"], (2, 2), ["e", "f"], (2, 1),
     [["r0", "r1"], ["c0", "c1", "c2"]]),
])
def test_sdk_array_cat_concatenates_along_rank_two_axes_with_masks_and_metadata(
        ee, local, axis, left_bands, left_shape, right_bands, right_shape, labels):
    left = source_array(ee, ee.Image("concat-scene").set("owner", "left"), left_bands, left_shape)
    right = source_array(ee, ee.Image("concat-scene").set("owner", "right"), right_bands, right_shape)
    expression = encode(ee, left.arrayCat(right, float(axis)))
    invocation = find_invocation(expression, "Image.arrayCat")
    assert invocation is not None
    assert set(invocation["arguments"]) == {"image1", "image2", "axis"}
    assert invocation["arguments"]["axis"] == float(axis)

    value = left.arrayCat(right, float(axis)).arrayFlatten(labels, separator="_")
    result, actual, names = compile_flat(ee, value, local)
    expected_names = ["_".join((row, column)) for row in labels[0] for column in labels[1]]
    assert result["bands"] == names == expected_names
    assert result["properties"]["owner"] == "left"
    assert result["source_item_ids"] == ["concat-scene"]

    left_values = independent_cells(local, left_bands, left_shape)
    right_values = independent_cells(local, right_bands, right_shape)
    expected = np.concatenate((left_values, right_values), axis=axis + 1)
    assert_expected(actual, expected, local, left_bands + right_bands)
    assert np.isnan(actual[:, [1, 3, 4]]).all()


def test_sdk_array_cat_preserves_row_major_rank_three_cells(ee, local):
    image = ee.Image("concat-scene").set("owner", "rank-three")
    left_bands, right_bands = BANDS[:4], BANDS[4:]
    left = source_array(ee, image, left_bands, (2, 1, 2))
    right = source_array(ee, image, right_bands, (2, 2, 2))
    result_array = left.arrayCat(right, 1)
    labels = [["z0", "z1"], ["y0", "y1", "y2"], ["x0", "x1"]]
    result, actual, names = compile_flat(
        ee, result_array.arrayFlatten(labels, separator="/"), local)

    expected_names = [f"{z}/{y}/{x}" for z in labels[0] for y in labels[1] for x in labels[2]]
    assert names == result["bands"] == expected_names
    assert result["properties"]["owner"] == "rank-three"
    left_values = independent_cells(local, left_bands, (2, 1, 2))
    right_values = independent_cells(local, right_bands, (2, 2, 2))
    expected = np.concatenate((left_values, right_values), axis=2)
    assert expected.shape[1:] == (2, 3, 2)
    assert_expected(actual, expected, local, left_bands + right_bands)


def test_sdk_array_repeat_tiles_whole_blocks_on_each_axis_and_keeps_masks(ee, local):
    source = ee.Image("concat-scene").set("repeat_tag", "preserved")
    base = source_array(ee, source, ["a", "b", "c", "d"], (2, 2))
    inputs = independent_cells(local, ["a", "b", "c", "d"], (2, 2))
    for axis, copies, count_image in (
        (0, 2, ee.Image.constant(2).toFloat()),
        (1, 3, ee.Image.constant(3).toDouble()),
    ):
        repeated = base.arrayRepeat(axis, count_image)
        expression = encode(ee, repeated)
        invocation = find_invocation(expression, "Image.arrayRepeat")
        assert invocation is not None
        assert set(invocation["arguments"]) == {"input", "axis", "copies"}
        assert isinstance(invocation["arguments"]["copies"], dict)
        assert invocation["arguments"]["copies"].get("type") == "ValueRef"
        scope = dict(expression["scope"])
        count_expression = scope[invocation["arguments"]["copies"]["value"]]
        expected_cast = "Image.toFloat" if axis == 0 else "Image.toDouble"
        assert count_expression["functionName"] == expected_cast

        labels = [[f"r{i}" for i in range(2 * copies)] if axis == 0 else ["r0", "r1"],
                  [f"c{i}" for i in range(2)] if axis == 0 else [f"c{i}" for i in range(2 * copies)]]
        result, actual, names = compile_flat(
            ee, repeated.arrayFlatten(labels, separator="_"), local)
        expected_names = ["_".join(parts) for parts in itertools.product(*labels)]
        assert names == expected_names == result["bands"]
        assert result["properties"]["repeat_tag"] == "preserved"
        expected = np.tile(inputs, (1, copies, 1) if axis == 0 else (1, 1, copies))
        assert_expected(actual, expected, local, ["a", "b", "c", "d"])
        assert not np.array_equal(expected[0], np.repeat(inputs[0], copies, axis=axis))
        assert np.isnan(actual[:, [1, 4]]).all()


def test_float32_casted_count_uses_its_rounded_pixel_value(ee, local):
    source = ee.ImageCollection("sentinel-2-l2a").first()
    base = source_array(ee, source, ["a"], (1,))
    rounded_count = ee.Image.constant(2.0000000000000004).toFloat()
    value = base.arrayRepeat(0, rounded_count).arrayFlatten([["first", "second"]])
    result, actual, names = compile_flat(ee, value, local)

    assert names == result["bands"] == ["first", "second"]
    np.testing.assert_array_equal(actual[:, :4], np.stack([
        local["arrays"]["concat-scene"]["a"][:4].astype(np.float32).astype(np.float64),
    ] * 2))

    unrounded = ee.Image.constant(2.0000000000000004)
    invalid = base.arrayRepeat(0, unrounded).arrayFlatten([["first", "second"]])
    with pytest.raises(UnsupportedEEError, match="copies.*integer|integer.*copies"):
        compile_flat(ee, invalid, local)

