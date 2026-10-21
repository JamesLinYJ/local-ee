"""Typed Image properties survive official Feature serialization and mapping."""
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.feature_values import validate_json_value
from gee.compat.earthengine.ir import Image, Pixel
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.probe_cases import synthetic_inputs
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                              signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")


def compile_sdk(ee, expression):
    metadata, items, _ = synthetic_inputs()
    return compile_expression(ee.serializer.encode(expression, for_cloud_api=False), [metadata], items)


def test_feature_image_properties_keep_pixel_ir_until_the_public_boundary(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    feature = ee.Feature(None, {"image": image})
    assert compile_sdk(ee, ee.Image(feature.get("image")).bandNames())["value"] == ["nir"]
    output = compile_sdk(ee, feature)["value"]["properties"]["image"]
    assert output["type"] == "Image" and output["id"] == "scene-a"
    assert output["bands"] == [{"id": "nir"}]
    assert set(output) == {"type", "id", "properties", "bands"}


def test_feature_map_can_produce_a_homogeneous_image_collection(ee):
    images = ee.ImageCollection("sentinel-2-l2a").toList(2)
    features = ee.FeatureCollection([
        ee.Feature(None, {"image": images.get(index)}) for index in range(2)
    ])
    result = ee.ImageCollection(features.map(lambda feature: ee.Image(feature.get("image")).select("nir")))
    assert compile_sdk(ee, result.size())["value"] == 2
    assert compile_sdk(ee, result.aggregate_array("system:index"))["value"] == ["scene-a", "scene-b"]
    assert compile_sdk(ee, result.first())["source_item_ids"] == ["scene-a"]


def test_inner_join_map_keeps_each_sensor_source_and_band_mask(ee):
    source = ee.ImageCollection("sentinel-2-l2a")
    paired = ee.Join.inner().apply(
        source.filter(ee.Filter.eq("system:index", "scene-a")),
        source.filter(ee.Filter.eq("system:index", "scene-b")),
        ee.Filter.equals(leftValue=1, rightValue=1))
    combined = ee.ImageCollection(paired.map(lambda feature:
        ee.Image(feature.get("primary")).select("red").addBands(
            ee.Image(feature.get("secondary")).select("nir")))).first()
    compiled = compile_sdk(ee, combined)
    assert compiled["source_item_ids"] == ["scene-a", "scene-b"]
    values, bands, timed = evaluate_graph(compiled, {
        "scene-a": {"red": np.array([1, 3, np.nan]), "nir": np.array([999, 999, 999])},
        "scene-b": {"red": np.array([999, 999, 999]), "nir": np.array([7, np.nan, 11])},
    })
    assert bands == ["red", "nir"] and timed is False
    np.testing.assert_equal(values, [[1, 3, np.nan], [7, np.nan, 11]])


def test_feature_map_rejects_mixed_element_types_and_drops_nulls_only_when_requested(ee):
    source = ee.ImageCollection("sentinel-2-l2a").first()
    features = ee.FeatureCollection([ee.Feature(None, {"image": source, "use": use})
                                    for use in (True, False)])
    mixed = features.map(lambda feature: ee.Algorithms.If(
        feature.get("use"), ee.Image(feature.get("image")), feature))
    with pytest.raises(UnsupportedEEError, match="cannot mix Feature and Image"):
        compile_sdk(ee, mixed)
    nullable = features.map(lambda feature: ee.Algorithms.If(
        feature.get("use"), ee.Image(feature.get("image")), None), dropNulls=True)
    assert compile_sdk(ee, ee.ImageCollection(nullable).size())["value"] == 1
    with pytest.raises(UnsupportedEEError, match="dropNulls=true"):
        compile_sdk(ee, features.map(lambda feature: ee.Algorithms.If(
            feature.get("use"), ee.Image(feature.get("image")), None)))


def test_feature_image_properties_reject_symbolic_or_malformed_internal_images():
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="concrete local Images"):
        validate_json_value(translator, Image([("nir", Pixel("constant", (1,)))], {}, mapped=True))
    with pytest.raises(UnsupportedEEError, match="valid named pixel bands"):
        validate_json_value(translator, Image([("nir", object())], {}))
    cyclic = Image([], {})
    cyclic.props["self"] = cyclic
    with pytest.raises(UnsupportedEEError, match="depth limit"):
        validate_json_value(translator, cyclic)
