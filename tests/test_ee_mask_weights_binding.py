"""Keep reviewed per-observation and masked-constant binding fixes in CI."""
from __future__ import annotations

import json

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


@pytest.fixture
def context():
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path="vendor/earthengine-js/algorithms.json",
        )
        metadata, items, _ = synthetic_inputs()
        yield ee, [metadata], items
    assert guard.evidence()["attempt_count"] == 0


def compiled(context, value):
    ee, catalog, items = context
    return compile_expression(ee.serializer.encode(value, for_cloud_api=False), catalog, items)


def test_nested_masked_constant_keeps_nodata_on_its_actual_raster_grid(context):
    ee, _catalog, _items = context
    scene = ee.Image(ee.ImageCollection("sentinel-2-l2a").first())
    mask = ee.Image.constant(0.5).updateMask(0).updateMask(scene.select("red"))
    result = compiled(context, scene.select("nir").updateMask(mask).mask())
    validate(result["process_graph"])
    assert result["source_item_ids"] == ["scene-a"]
    assert result["bands"] == ["nir"]
    nodes = result["process_graph"]
    operations = [json.loads(node["arguments"]["spec"])["op"]
                  for node in nodes.values() if node["process_id"] == "local_ee_mask_weights"]
    assert "apply" in operations and "update" in operations
    masked = [node for node in nodes.values() if node["process_id"] == "mask"]
    assert masked
    for node in masked:
        data = nodes[node["arguments"]["data"]["from_node"]]
        invalid = nodes[node["arguments"]["mask"]["from_node"]]
        assert data["process_id"] == invalid["process_id"] == "local_ee_constant_on_grid"
        assert data["arguments"]["value"] == 0 and invalid["arguments"]["value"] == 1
        assert data["arguments"]["data"] == invalid["arguments"]["data"]


@pytest.mark.parametrize("fractional", [False, True])
def test_mapped_mask_getters_keep_distinct_same_day_scene_identities(context, fractional):
    ee, _catalog, items = context
    # These actual observations differ by one millisecond on the same UTC day.
    items["sentinel-2-l2a"][0]["properties"]["system:time_start"] = 1000
    items["sentinel-2-l2a"][1]["properties"]["system:time_start"] = 1001
    collection = ee.ImageCollection("sentinel-2-l2a").limit(2)
    if fractional:
        collection = collection.map(lambda image: image.select("nir").updateMask(0.25).mask())
    else:
        collection = collection.map(lambda image: image.select("nir").mask())
    info = compiled(context, collection)
    assert info["source_item_ids"] == ["scene-a", "scene-b"]
    assert "process_graph" not in info  # collection metadata does not invent pixels
    image = compiled(context, collection.toBands())
    validate(image["process_graph"])
    loads = [node["arguments"]["_gee_item_ids"] for node in image["process_graph"].values()
             if node["process_id"] == "load_collection"]
    assert loads == [["scene-a"], ["scene-b"]]
    assert image["bands"] == ["scene-a_nir", "scene-b_nir"]
