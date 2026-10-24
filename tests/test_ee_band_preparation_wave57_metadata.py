"""Per-item identity and metadata-to-raster coverage for Image methods."""
from __future__ import annotations

import copy
from dataclasses import replace

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.image_metadata_raster import invoke_image_metadata_raster
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.ee_metadata import requires_item_metadata
from test_ee_band_preparation_wave57 import (
    compile_sdk,
    ee,
    graph_nodes,
    local,
    mapped_callback,
)
from test_ee_translate import evaluate_graph


def test_metadata_and_id_map_expansion_preserve_same_day_scene_ids(ee, local):
    collection = ee.ImageCollection("sentinel-2-l2a")
    ids = collection.map(lambda image: image.set("seen:id", image.id())).aggregate_array("seen:id")
    assert compile_sdk(ee, ids, local)["value"] == ["a", "b", "c"]
    assert len({item["properties"]["system:time_start"] for item in local[1]["sentinel-2-l2a"]}) == 1

    mapped = collection.map(lambda image: image.metadata("CLOUDY_PIXEL_PERCENTAGE", "cloud"))
    result = compile_sdk(ee, mapped.toBands(), local)
    assert result["kind"] == "image"
    assert result["bands"] == ["a_cloud", "b_cloud", "c_cloud"]
    assert [node["arguments"]["value"] for node in graph_nodes(
        result, "local_ee_constant_on_grid")] == [20, 5, 90]
    loads = [node["arguments"] for node in graph_nodes(result, "load_collection")]
    assert [node["_gee_item_ids"] for node in loads] == [["a"], ["b"], ["c"]]


def test_metadata_constant_is_double_on_grid_and_does_not_inherit_input_mask(ee, local):
    image = ee.ImageCollection("sentinel-2-l2a").first().updateMask(0)
    expression = image.metadata("CLOUDY_PIXEL_PERCENTAGE", None)
    result = compile_sdk(ee, expression, local)
    assert result["bands"] == ["CLOUDY_PIXEL_PERCENTAGE"]
    assert result["source_item_ids"] == ["a"]
    assert not graph_nodes(result, "local_ee_to_float")
    constants = graph_nodes(result, "local_ee_constant_on_grid")
    assert [node["arguments"]["value"] for node in constants] == [1.0, 20]

    arrays = {"a": {"blue": np.array([1.0, 2.0]), "green": np.array([2.0, 3.0]),
                     "red": np.array([3.0, 4.0]), "nir": np.array([4.0, 5.0])}}
    data, names, _ = evaluate_graph(
        result, arrays, grid=np.array([[0.5, 0.5], [1.5, 1.5]]),
    )
    assert names == ["CLOUDY_PIXEL_PERCENTAGE"]
    np.testing.assert_array_equal(data.reshape(-1), [20.0, 20.0])


def test_metadata_requires_present_numeric_property_real_id_and_real_grid(ee, local):
    image = ee.ImageCollection("sentinel-2-l2a").first()
    with pytest.raises(UnsupportedEEError, match="unavailable"):
        compile_sdk(ee, image.metadata("not-present"), local)
    with pytest.raises(UnsupportedEEError, match="numeric"):
        compile_sdk(ee, image.metadata("system:index"), local)
    with pytest.raises(UnsupportedEEError, match="source item identity"):
        compile_sdk(ee, ee.Image.constant(1).id(), local)
    constant_metadata = ee.Image.constant(1).set("number", 4).metadata("number")
    with pytest.raises(UnsupportedEEError, match="real local raster source"):
        compile_sdk(ee, constant_metadata, local)

    translator = Translator(*local, options=None)
    source_image = translator.load("sentinel-2-l2a").image
    with pytest.raises(UnsupportedEEError, match="property must be a string"):
        invoke_image_metadata_raster(
            translator, "Image.metadata", {"image": source_image, "property": None},
        )
    with pytest.raises(UnsupportedEEError, match="unknown"):
        invoke_image_metadata_raster(
            translator, "Image.metadata", {
                "image": source_image,
                "property": "CLOUDY_PIXEL_PERCENTAGE",
                "unknown": 1,
            },
        )
    with pytest.raises(UnsupportedEEError, match="source item identity"):
        invoke_image_metadata_raster(
            translator, "Image.id", {
                "element": replace(source_image, source=replace(source_image.source, ids=())),
            },
        )


def test_id_uses_the_loaded_source_identity_not_system_index(ee, local):
    catalog, items = local
    changed_items = copy.deepcopy(items)
    changed_items["sentinel-2-l2a"][0]["properties"]["system:index"] = "different-property"
    result = compile_sdk(
        ee, ee.ImageCollection("sentinel-2-l2a").first().id(),
        (catalog, changed_items),
    )
    assert result["value"] == "a"


def test_static_captured_metadata_reads_do_not_expand_collection_maps(ee):
    collection = ee.ImageCollection("sentinel-2-l2a")
    dynamic_id, scope = mapped_callback(
        ee, collection.map(lambda image: image.set("seen:id", image.id())),
    )
    assert requires_item_metadata(dynamic_id, scope)
    dynamic_metadata, scope = mapped_callback(
        ee, collection.map(lambda image: image.metadata("CLOUDY_PIXEL_PERCENTAGE")),
    )
    assert requires_item_metadata(dynamic_metadata, scope)

    captured = collection.first().set("captured:number", 7)
    static_read, scope = mapped_callback(
        ee, collection.map(lambda image: image.set(
            "captured:number", captured.metadata("captured:number"),
        )),
    )
    assert not requires_item_metadata(static_read, scope)
