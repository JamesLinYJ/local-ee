"""New typed metadata reads preserve real item identity inside image maps."""
from pathlib import Path

import pytest

from gee.ee_metadata import requires_item_metadata
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import Function, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_metadata import _local_data, resolve, walk


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    with OfflineGuard() as guard:
        client = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        yield client
    assert guard.evidence()["attempt_count"] == 0


def value(ee, expression):
    encoded = ee.serializer.encode(expression, for_cloud_api=False)
    return compile_expression(encoded, *_local_data())["value"]


def callback_reads_items(ee, collection):
    encoded = ee.serializer.encode(collection, for_cloud_api=False)
    scope = dict(encoded["scope"])
    maps = [node for entry in scope.values() for node in walk(entry)
            if node.get("functionName") == "Collection.map"]
    assert len(maps) == 1
    callback = resolve(maps[0]["arguments"]["baseAlgorithm"], scope)
    return requires_item_metadata(
        Function(callback["argumentNames"], callback["body"], {}), scope,
    )


def test_typed_getters_in_maps_keep_same_day_distinct_observations(ee):
    collection = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").map(
        lambda image: image.set({
            "typed_time": image.getNumber("system:time_start"),
            "label": image.getString("system:index").cat("-tag"),
        })
    )
    assert callback_reads_items(ee, collection)
    assert value(ee, collection.aggregate_array("typed_time")) == [1000, 1001, 86402000]
    assert value(ee, collection.aggregate_array("label")) == ["a-tag", "b-tag", "c-tag"]


def test_dictionary_and_array_metadata_stays_typed_inside_per_item_callbacks(ee):
    def prepare(image):
        result = image.set("vector", ee.Array([
            image.getNumber("CLOUDY_PIXEL_PERCENTAGE"),
            image.getNumber("system:time_start"),
        ]))
        return result.set({
            "vector_sum": result.getArray("vector").reduce(ee.Reducer.sum(), [0]).get([0]),
            "saved": image.toDictionary(["system:index", "CLOUDY_PIXEL_PERCENTAGE"]),
        })

    collection = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").map(prepare)
    assert callback_reads_items(ee, collection)
    assert value(ee, collection.aggregate_array("vector_sum")) == [1020, 1006, 86402090]
    assert value(ee, collection.aggregate_array("saved")) == [
        {"system:index": name, "CLOUDY_PIXEL_PERCENTAGE": cloud}
        for name, cloud in zip(("a", "b", "c"), (20, 5, 90))
    ]


def test_replace_properties_metadata_follows_its_actual_mapped_source(ee):
    def prepare(image):
        copied = ee.Image(ee.ApiFunction.call_(
            "Element.replaceProperties", destination=ee.Image.constant(0), source=image,
        ))
        return copied.set("copied_time", copied.getNumber("system:time_start"))

    collection = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").map(prepare)
    assert callback_reads_items(ee, collection)
    assert value(ee, collection.aggregate_array("copied_time")) == [1000, 1001, 86402000]


def test_captured_static_typed_read_does_not_force_per_item_expansion(ee):
    captured = ee.Image.constant(0).set("fixed", 42)
    collection = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").map(
        lambda image: image.set("captured", captured.getNumber("fixed")),
    )
    assert not callback_reads_items(ee, collection)
    assert value(ee, collection.aggregate_array("captured")) == [42, 42, 42]
