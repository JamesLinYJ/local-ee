"""Per-band collection array packing through the pinned SDK and local compiler."""
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_core import MAX_ARRAY_WORK
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, ImageSequence, const
from gee.compat.earthengine import raster_collection_arrays
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
SCENE_IDS = ["same-b", "same-a", "later"]
ARRAY_BANDS = ["blue", "red"]
OUTPUT_LABELS = ["scene_0", "scene_1", "scene_2"]


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
    bands = ["blue", "red", "b2", "b3", "b4", "b5", "b6", "b7"]
    full = {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 1], [0, 1], [0, 0]]]}
    left = {"type": "Polygon", "coordinates": [[[0, 0], [3, 0], [3, 1], [0, 1], [0, 0]]]}
    right = {"type": "Polygon", "coordinates": [[[1, 0], [4, 0], [4, 1], [1, 1], [1, 0]]]}
    geometries = {"same-b": left, "same-a": right, "later": full}
    times = {"same-b": 86_400_000, "same-a": 86_400_000, "later": 172_800_000}
    items = {"sentinel-2-l2a": [
        {"id": scene_id, "bbox": [0, 0, 4, 1], "geometry": geometries[scene_id],
         "properties": {"system:index": scene_id, "system:time_start": times[scene_id]}}
        for scene_id in SCENE_IDS
    ]}
    arrays = {
        "same-b": {
            "blue": np.array([1., 2., np.nan, 4.]),
            "red": np.array([10., 20., 30., 40.]),
        },
        "same-a": {
            "blue": np.array([100., 200., 300., 400.]),
            "red": np.array([1000., np.nan, 3000., 4000.]),
        },
        "later": {
            "blue": np.array([10000., 20000., 30000., 40000.]),
            "red": np.array([100000., 200000., 300000., 400000.]),
        },
    }
    for scene_index, scene_id in enumerate(SCENE_IDS):
        for band_index, band in enumerate(bands[2:], start=2):
            arrays[scene_id][band] = np.full(4, scene_index * 100 + band_index, dtype=float)
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": bands}}}]
    grid = np.array([[x + 0.5, 0.5] for x in range(4)])
    return {"catalog": catalog, "items": items, "arrays": arrays, "grid": grid,
            "geometries": geometries}


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_value(ee, value, local):
    return compile_expression(encode(ee, value), local["catalog"], local["items"])


def find_invocation(value, function_name):
    if isinstance(value, dict):
        if value.get("type") == "Invocation" and value.get("functionName") == function_name:
            return value
        for child in value.values():
            found = find_invocation(child, function_name)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for child in value:
            found = find_invocation(child, function_name)
            if found is not None:
                return found
    return None


def sequence(ee, ids=SCENE_IDS, bands=ARRAY_BANDS):
    images = [ee.Image(scene_id).select(list(bands)) for scene_id in ids]
    return ee.ImageCollection.fromImages(images)


def flatten_selected(image, band_name, labels=OUTPUT_LABELS):
    return image.select([band_name]).arrayFlatten([labels], separator="_")


def evaluate(ee, value, local):
    result = compile_value(ee, value, local)
    data, names, timed = evaluate_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries=local["geometries"],
    )
    assert timed is False
    return result, dict(zip(names, data))


def test_sdk_to_array_per_band_preserves_order_identity_band_masks_and_scene_geometry(ee, local):
    packed = sequence(ee).toArrayPerBand(axis=0, dropMasked=False)
    # The client returns a generic ee.Image; its typed multi-array value must
    # survive a Dictionary lookup and ordinary Image re-wrapping.
    carried = ee.Image(ee.Dictionary({"packed": packed}).get("packed"))
    assert compile_value(ee, carried.bandNames(), local)["value"] == ARRAY_BANDS
    encoded = encode(ee, carried)
    encoded_arguments = find_invocation(encoded, "ImageCollection.toArrayPerBand")["arguments"]
    assert set(encoded_arguments) == {"collection", "axis", "dropMasked"}
    assert encoded_arguments["axis"] == 0
    assert encoded_arguments["dropMasked"] is False

    blue_result, blue = evaluate(ee, flatten_selected(carried, "blue"), local)
    red_result, red = evaluate(ee, flatten_selected(carried, "red"), local)
    assert blue_result["source_item_ids"] == SCENE_IDS
    assert red_result["source_item_ids"] == SCENE_IDS
    assert blue_result["has_time_dimension"] is False
    assert blue_result["process_graph"]
    # arrayFlatten names replace the logical array band name with the supplied
    # coordinate labels, matching the SDK's array-valued band contract.
    assert blue_result["bands"] == OUTPUT_LABELS
    # Hand-picked grid centers: x=.5 is outside same-a, x=3.5 outside
    # same-b, and the middle missing samples affect only their own band.
    np.testing.assert_allclose(blue["scene_0"], [np.nan, 2, np.nan, np.nan], equal_nan=True)
    np.testing.assert_allclose(blue["scene_1"], [np.nan, 200, np.nan, np.nan], equal_nan=True)
    np.testing.assert_allclose(blue["scene_2"], [np.nan, 20000, np.nan, np.nan], equal_nan=True)
    np.testing.assert_allclose(red["scene_0"], [np.nan, np.nan, 30, np.nan], equal_nan=True)
    np.testing.assert_allclose(red["scene_1"], [np.nan, np.nan, 3000, np.nan], equal_nan=True)
    np.testing.assert_allclose(red["scene_2"], [np.nan, np.nan, 300000, np.nan], equal_nan=True)
    assert blue_result["properties"] == {}


def test_collection_array_names_can_be_reordered_and_renamed_as_typed_bands(ee, local):
    packed = sequence(ee).toArrayPerBand()
    renamed = packed.select(["red", "blue"], ["signal", "visible"])
    assert compile_value(ee, renamed.bandNames(), local)["value"] == ["signal", "visible"]
    result, values = evaluate(ee, flatten_selected(renamed, "visible"), local)
    assert result["bands"] == OUTPUT_LABELS
    np.testing.assert_allclose(values["scene_1"], [np.nan, 200, np.nan, np.nan], equal_nan=True)


def test_to_array_per_band_default_signature_and_exact_supported_parameters(ee, local):
    default = encode(ee, sequence(ee).toArrayPerBand())
    call = find_invocation(default, "ImageCollection.toArrayPerBand")
    assert call is not None
    # The pinned SDK omits server defaults from the wire expression.
    assert set(call["arguments"]) == {"collection"}
    explicit = encode(ee, sequence(ee).toArrayPerBand(axis=0, dropMasked=False))
    call = find_invocation(explicit, "ImageCollection.toArrayPerBand")
    assert call["arguments"]["axis"] == 0
    assert call["arguments"]["dropMasked"] is False
    with pytest.raises(UnsupportedEEError, match="Multiple array bands require select"):
        compile_value(ee, sequence(ee).toArrayPerBand(), local)
    # The pinned serializer keeps an integer-valued float as a JSON float;
    # the local Integer policy accepts it while rejecting bool separately.
    float_axis = sequence(ee).toArrayPerBand(axis=0.0)
    float_call = find_invocation(encode(ee, float_axis), "ImageCollection.toArrayPerBand")
    assert float_call["arguments"]["axis"] == 0.0
    assert compile_value(ee, flatten_selected(float_axis, "blue"), local)["bands"] == OUTPUT_LABELS
    negative_zero = sequence(ee).toArrayPerBand(axis=-0.0)
    assert compile_value(ee, flatten_selected(negative_zero, "blue"), local)["bands"] == OUTPUT_LABELS


def test_to_array_per_band_rejects_axis_drop_masked_and_unknown_wire_arguments(ee, local):
    for value in (
        sequence(ee).toArrayPerBand(axis=1),
        sequence(ee).toArrayPerBand(axis=-1),
        sequence(ee).toArrayPerBand(axis=0.5),
        sequence(ee).toArrayPerBand(axis=True),
        sequence(ee).toArrayPerBand(axis=float("nan")),
        sequence(ee).toArrayPerBand(axis=float("inf")),
        sequence(ee).toArrayPerBand(dropMasked=True),
        sequence(ee).toArrayPerBand(dropMasked=0),
        sequence(ee).toArrayPerBand(dropMasked=1),
    ):
        with pytest.raises(UnsupportedEEError):
            compile_value(ee, value, local)

    expression = deepcopy(encode(ee, sequence(ee).toArrayPerBand()))
    call = find_invocation(expression, "ImageCollection.toArrayPerBand")
    call["arguments"]["ignored"] = True
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(expression, local["catalog"], local["items"])
    with pytest.raises(UnsupportedEEError):
        compile_expression({"type": "Invocation", "functionName": "ImageCollection.toArrayPerBand",
                           "arguments": {}}, local["catalog"], local["items"])


def test_collection_array_requires_nonempty_bounded_matching_scalar_frames(ee, local):
    empty = ee.ImageCollection.fromImages([]).toArrayPerBand()
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, empty, local)

    nine = ee.ImageCollection.fromImages([ee.Image("same-b").select("blue")] * 9)
    with pytest.raises(UnsupportedEEError, match="8"):
        compile_value(ee, nine.toArrayPerBand(), local)

    reordered = ee.ImageCollection.fromImages([
        ee.Image("same-b").select(["blue", "red"]),
        ee.Image("same-a").select(["red", "blue"]),
    ]).toArrayPerBand()
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, reordered, local)

    distinct = ee.ImageCollection.fromImages([
        ee.Image("same-b").select("blue"), ee.Image("same-a").select("red"),
    ]).toArrayPerBand()
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, distinct, local)

    too_many_bands = [f"band_{index}" for index in range(9)]
    catalog = deepcopy(local["catalog"])
    catalog[0]["cube:dimensions"]["bands"]["values"] = too_many_bands
    nine_band = ee.ImageCollection.fromImages([
        ee.Image("same-b").select(too_many_bands),
    ]).toArrayPerBand()
    with pytest.raises(UnsupportedEEError, match="8"):
        compile_expression(encode(ee, nine_band), catalog, local["items"])


def test_eight_frames_and_eight_bands_reach_the_64_cell_boundary(ee, local):
    ids = [f"boundary-{index}" for index in range(8)]
    bands = [f"v{index}" for index in range(8)]
    catalog = deepcopy(local["catalog"])
    catalog[0]["cube:dimensions"]["bands"]["values"] = bands
    geometry = local["items"]["sentinel-2-l2a"][0]["geometry"]
    items = {"sentinel-2-l2a": [
        {"id": scene_id, "bbox": [0, 0, 4, 1], "geometry": geometry,
         "properties": {"system:index": scene_id, "system:time_start": index}}
        for index, scene_id in enumerate(ids)
    ]}
    arrays = {scene_id: {band: np.full(4, frame * 10 + index, dtype=float)
                         for index, band in enumerate(bands)}
              for frame, scene_id in enumerate(ids)}
    collection = ee.ImageCollection.fromImages([
        ee.Image(scene_id).select(bands) for scene_id in ids
    ])
    output = collection.toArrayPerBand().select(["v7"]).arrayFlatten([[
        f"frame_{index}" for index in range(8)
    ]])
    result = compile_expression(encode(ee, output), catalog, items)
    assert result["bands"] == [f"frame_{index}" for index in range(8)]
    assert result["source_item_ids"] == ids
    values, names, timed = evaluate_graph(result, arrays, grid=local["grid"])
    assert timed is False
    assert names == result["bands"]
    for frame in range(8):
        np.testing.assert_allclose(values[frame], np.full(4, frame * 10 + 7))


def test_collection_array_work_budget_preflights_before_frame_expansion(monkeypatch):
    translator = Translator([], {}, {})
    translator.steps = MAX_ARRAY_WORK - 1
    frames = ImageSequence([Image([("blue", const(3))], {})])
    monkeypatch.setattr(
        raster_collection_arrays, "collection_frames",
        lambda *args, **kwargs: pytest.fail("frames expanded before the work preflight"),
    )
    with pytest.raises(UnsupportedEEError, match="work budget"):
        raster_collection_arrays.invoke_collection_array(
            translator, "ImageCollection.toArrayPerBand", {"collection": frames}
        )
    assert translator.steps == MAX_ARRAY_WORK - 1
