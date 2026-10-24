"""Bounded constant-band and date-band contracts from the pinned EE SDK."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import shape

from gee.compat.earthengine.ir import Image, ImageSequence, Pixel
from gee.ee_translate import Translator, UnsupportedEEError, compile_expression


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests/fixtures/ee-constant-1.7.49.json").read_text())
SDK = FIXTURE["expressions"]
BIG = 16_777_219


def rect(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def local_data():
    names = ["blue", "green", "red", "nir", "SCL"]
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": names}}}]
    # Equal timestamps must not collapse distinct item identities or extents.
    regions = {"a": rect(0, 0, 1, 1), "b": rect(2, 0, 3, 1), "c": rect(0, 2, 1, 3)}
    items = {"sentinel-2-l2a": [
        {"id": iid, "bbox": list(shape(geometry).bounds), "geometry": geometry,
         "properties": {"system:time_start": 1000, "system:index": iid,
                        "CLOUDY_PIXEL_PERCENTAGE": index * 10}}
        for index, (iid, geometry) in enumerate(regions.items())
    ]}
    return catalog, items


def walk(value):
    if isinstance(value, dict):
        if value.get("type") == "Invocation":
            yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def pixel_walk(value):
    if isinstance(value, Pixel):
        yield value
        for argument in value.args:
            yield from pixel_walk(argument)
    elif isinstance(value, (tuple, list)):
        for child in value:
            yield from pixel_walk(child)


def resolve(value, scope):
    seen = set()
    while isinstance(value, dict) and value.get("type") == "ValueRef":
        key = value["value"]
        if key in seen or key not in scope:
            raise AssertionError(f"unresolved/cyclic SDK fixture ref: {key}")
        seen.add(key)
        value = scope[key]
    return value


def invocation(expression, function):
    matches = [node for node in walk(expression) if node.get("functionName") == function]
    assert matches, f"missing serialized {function} call"
    return matches


def compile_fixture(name, local=None):
    return compile_expression(SDK[name], *(local or local_data()))


def nodes_for(result, process_id):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == process_id]


def loads_by_item(result):
    return {
        ids[0]: args["spatial_extent"]
        for node in result["process_graph"].values()
        if node["process_id"] == "load_collection"
        for args in [node["arguments"]]
        for ids in [args.get("_gee_item_ids", [])]
        if len(ids) == 1
    }


def test_fixture_is_generated_by_the_pinned_official_sdk_without_networking():
    assert FIXTURE["sdk"] == "1.7.49"
    assert FIXTURE["source_commit"] == "e189e4b89e785019ea5642ea8e80cb644749cd4a"
    assert set(SDK) == {
        "firstAddScalar", "firstAddMultiband", "firstAddDateMillis",
        "firstAddConstantArithmetic", "overwriteAndNames", "maskedRasterAddConstant",
        "rasterAddClippedConstant", "mapStaticConstantMean", "mapDateToBands",
        "standaloneConstant", "unboundClippedConstant", "unsupportedProjectionQuery",
    }
    source = (ROOT / "scripts/ee_constant_fixtures.cjs").read_text()
    assert "ee.data.computeValue = () => { throw Error" in source
    assert "http://localhost/disabled" in source and "vendor/earthengine-js" in source

    for name in list(SDK)[:9]:
        assert any(node["functionName"] == "ImageCollection.load"
                   and node["arguments"]["id"] == "sentinel-2-l2a"
                   for node in walk(SDK[name]))
    assert invocation(SDK["firstAddScalar"], "Image.addBands")
    constants = invocation(SDK["firstAddMultiband"], "Image.constant")
    scope = dict(SDK["firstAddMultiband"]["scope"])
    assert resolve(constants[0]["arguments"]["value"], scope) == [1, BIG]
    assert invocation(SDK["firstAddDateMillis"], "Date.millis")
    assert invocation(SDK["mapDateToBands"], "Collection.map")
    assert invocation(SDK["mapDateToBands"], "ImageCollection.toBands")
    bands = invocation(SDK["overwriteAndNames"], "Image.addBands")[0]["arguments"]
    assert bands["overwrite"] is True
    assert resolve(bands["names"], dict(SDK["overwriteAndNames"]["scope"])) == ["red", "nir"]


@pytest.mark.parametrize(("name", "expected_bands", "expected_values"), [
    ("firstAddScalar", ["one"], [1]),
    ("firstAddMultiband", ["one", "large"], [1, BIG]),
    ("firstAddDateMillis", ["millis"], [1000]),
    ("firstAddConstantArithmetic", ["calculated"], [7]),
    ("overwriteAndNames", ["red", "nir"], [101, 202]),
])
def test_raster_bound_constants_compile_with_exact_values_properties_and_source_ids(
        name, expected_bands, expected_values):
    result = compile_fixture(name)
    assert result["kind"] == "image"
    assert result["bands"] == expected_bands
    assert result["source_item_ids"] == ["a"]
    assert result["properties"]["system:index"] == "a"
    assert result["properties"]["system:time_start"] == 1000
    constants = nodes_for(result, "local_ee_constant_on_grid")
    assert [node["arguments"]["value"] for node in constants] == expected_values


def test_addbands_constant_ir_carries_template_source_and_destination_footprint():
    catalog, items = local_data()
    translator = Translator(catalog, items, None)
    image = translator.evaluate(SDK["firstAddScalar"])
    assert isinstance(image, Image)
    pixel = dict(image.bands)["one"]
    assert isinstance(pixel, Pixel) and pixel.op == "on_grid"
    constant, template, source, footprint, absolute = pixel.args
    assert constant.op == "constant" and constant.args == (1,)
    assert any(candidate.op == "band" and candidate.args[0] == source
               for candidate in pixel_walk(template))
    assert source.ids == ("a",)
    assert footprint is None and absolute is False
    assert shape(translator.footprint(image)).equals(shape(items["sentinel-2-l2a"][0]["geometry"]))


def test_masked_destination_uses_a_real_grid_without_inheriting_its_mask():
    result = compile_fixture("maskedRasterAddConstant")
    assert result["bands"] == ["valid_constant"]
    assert [node["arguments"]["value"] for node in nodes_for(
        result, "local_ee_constant_on_grid")] == [1.0, 7]
    assert result["source_item_ids"] == ["a"]
    catalog, items = local_data()
    image = Translator(catalog, items, None).evaluate(SDK["maskedRasterAddConstant"])
    pixel = dict(image.bands)["valid_constant"]
    assert pixel.op == "on_grid"
    constant, template, source, _, _ = pixel.args
    assert constant.op == "constant" and constant.args == (7,)
    assert any(candidate.op == "if" for candidate in pixel_walk(template))
    assert all(candidate.op != "if" for candidate in pixel_walk(constant))
    assert source.ids == ("a",)


def test_static_constant_mean_preserves_each_same_time_scene_and_extent():
    result = compile_fixture("mapStaticConstantMean")
    assert result["kind"] == "image"
    assert result["bands"] == ["static"]
    assert result["source_item_ids"] == ["a", "b", "c"]
    assert [node["arguments"]["value"] for node in nodes_for(
        result, "local_ee_constant_on_grid")] == [7, 7, 7]
    extents = loads_by_item(result)
    assert extents == {
        "a": {"west": 0.0, "south": 0.0, "east": 1.0, "north": 1.0},
        "b": {"west": 2.0, "south": 0.0, "east": 3.0, "north": 1.0},
        "c": {"west": 0.0, "south": 2.0, "east": 1.0, "north": 3.0},
    }


def test_date_to_bands_does_not_collapse_same_timestamp_ids_or_footprints():
    result = compile_fixture("mapDateToBands")
    assert result["kind"] == "image"
    assert result["bands"] == ["a_millis", "b_millis", "c_millis"]
    assert result["source_item_ids"] == ["a", "b", "c"]
    assert [node["arguments"]["value"] for node in nodes_for(
        result, "local_ee_constant_on_grid")] == [1000, 1000, 1000]
    assert loads_by_item(result) == {
        "a": {"west": 0.0, "south": 0.0, "east": 1.0, "north": 1.0},
        "b": {"west": 2.0, "south": 0.0, "east": 3.0, "north": 1.0},
        "c": {"west": 0.0, "south": 2.0, "east": 1.0, "north": 3.0},
    }


def call(name, **arguments):
    return {"type": "Invocation", "functionName": name, "arguments": arguments}


def raster():
    return call("Collection.first", collection=call("ImageCollection.load", id="sentinel-2-l2a"))


@pytest.mark.parametrize("value, message", [
    (2**53 + 1, "above 2\\^53"),
    (None, "finite|numeric"),
    (float("nan"), "finite|numeric"),
    (float("inf"), "finite|numeric"),
    (-float("inf"), "finite|numeric"),
])
def test_unsafe_raw_constant_literals_are_rejected_before_binding(value, message):
    expression = call("Image.addBands", dstImg=raster(), srcImg=call("Image.constant", value=value))
    with pytest.raises(UnsupportedEEError, match=message):
        compile_expression(expression, *local_data())


def test_folded_constant_above_exact_integer_range_is_rejected():
    folded = call("Image.add", image1=call("Image.constant", value=2**53), image2=1)
    expression = call("Image.addBands", dstImg=raster(), srcImg=folded)
    with pytest.raises(UnsupportedEEError, match="exact scalar range"):
        compile_expression(expression, *local_data())


@pytest.mark.parametrize("name", ["standaloneConstant", "unboundClippedConstant", "rasterAddClippedConstant"])
def test_unbound_or_clipped_constants_are_not_silently_materialized(name):
    with pytest.raises(UnsupportedEEError, match="constant|grid|clip|footprint"):
        compile_fixture(name)


def test_unsupported_projection_query_stays_explicitly_unsupported():
    with pytest.raises(UnsupportedEEError, match="Unsupported Earth Engine algorithm|projection"):
        compile_fixture("unsupportedProjectionQuery")
