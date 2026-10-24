"""Official SDK serialization and finite-graph tests for Image band preparation."""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.image_band_preparation import (
    BAND_PREPARATION_ARGUMENTS,
    invoke_image_band_preparation,
)
from gee.compat.earthengine.image_metadata_raster import IMAGE_METADATA_RASTER_ARGUMENTS
from gee.compat.earthengine.ir import Image, Source, UnsupportedEEError
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import Function, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_raster_array_values import evaluated_bands
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]


def rect(w=0, s=0, e=2, n=2):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


@pytest.fixture
def ee():
    with OfflineGuard() as guard:
        client = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        assert client.__version__ == "1.7.49"
        yield client
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def local():
    bands = ["blue", "green", "red", "nir"]
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": bands}}}]
    items = {"sentinel-2-l2a": [
        {"id": item_id, "bbox": [0, 0, 2, 2], "geometry": rect(), "properties": {
            "system:index": item_id, "system:time_start": 1000,
            "CLOUDY_PIXEL_PERCENTAGE": cloudy,
        }}
        for item_id, cloudy in (("a", 20), ("b", 5), ("c", 90))
    ]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_sdk(ee, value, local):
    return compile_expression(encode(ee, value), *local)


def walk(value):
    if isinstance(value, dict):
        if value.get("type") == "Invocation":
            yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from walk(child)


def graph_nodes(result, process_id):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == process_id]


def resolve(value, scope):
    seen = set()
    while isinstance(value, dict) and value.get("type") == "ValueRef":
        key = value.get("value")
        if key in seen or key not in scope:
            raise AssertionError(f"unresolved or cyclic SDK scope ref: {key}")
        seen.add(key)
        value = scope[key]
    return value


def mapped_callback(ee, collection):
    encoded = encode(ee, collection)
    scope = dict(encoded.get("scope", []))
    maps = [node for entry in scope.values() for node in walk(entry)
            if node.get("functionName") == "Collection.map"]
    assert len(maps) == 1
    callback = resolve(maps[0]["arguments"]["baseAlgorithm"], scope)
    return Function(callback["argumentNames"], callback["body"], {}), scope


def mutate_invocation(value, name, key, replacement):
    for node in walk(value):
        if node.get("functionName") == name:
            node["arguments"][key] = replacement
            return
    raise AssertionError(f"missing serialized invocation {name}")


def test_regexp_rename_uses_re2_captures_global_default_and_preserves_unmatched(ee, local):
    image = ee.ImageCollection("sentinel-2-l2a").first().select(["blue", "green", "nir"])
    expression = image.regexpRename("e", "x")
    serialized = encode(ee, expression)
    invocation = next(node for node in walk(serialized)
                      if node.get("functionName") == "Image.regexpRename")
    assert invocation["arguments"]["regex"] == "e"
    result = compile_expression(serialized, *local)
    assert result["bands"] == ["blux", "grxxn", "nir"]
    assert result["source_item_ids"] == ["a"]

    first_only = compile_sdk(ee, image.regexpRename("e", "x", all=False), local)
    assert first_only["bands"] == ["blux", "grxen", "nir"]
    null_all = compile_sdk(ee, image.regexpRename("e", "x", all=None), local)
    assert null_all["bands"] == ["blux", "grxxn", "nir"]
    captured = compile_sdk(
        ee, image.select("blue").regexpRename(r"([a-z])([a-z]+)", "$2-$1"), local,
    )
    assert captured["bands"] == ["lue-b"]


def test_regexp_rename_rejects_collisions_unsupported_re2_and_unknown_kwargs(ee, local):
    image = ee.ImageCollection("sentinel-2-l2a").first().select(["blue", "green"])
    with pytest.raises(UnsupportedEEError, match="duplicate band names"):
        compile_sdk(ee, image.regexpRename(".*", "same"), local)
    with pytest.raises(UnsupportedEEError, match="RE2"):
        compile_sdk(ee, image.regexpRename(r"(b)\1", "$1"), local)

    encoded = copy.deepcopy(encode(ee, image.regexpRename("e", "x")))
    mutate_invocation(encoded, "Image.regexpRename", "unexpected", True)
    with pytest.raises(UnsupportedEEError, match="unexpected"):
        compile_expression(encoded, *local)


def test_slice_keeps_input_order_and_normalizes_negative_and_null_bounds(ee, local):
    image = ee.ImageCollection("sentinel-2-l2a").first().select(["blue", "green", "red", "nir"])
    result = compile_sdk(ee, image.slice(-3, None), local)
    assert result["bands"] == ["green", "red", "nir"]
    assert result["source_item_ids"] == ["a"]
    # Out-of-range clamping follows Python's bounded slice convention locally;
    # Google documents negative-from-end positions, but not out-of-range bounds.
    assert compile_sdk(ee, image.slice(-99, 99), local)["bands"] == ["blue", "green", "red", "nir"]
    reversed_slice = Translator(*local, options=None).evaluate(
        encode(ee, image.slice(3, 1)),
    )
    assert isinstance(reversed_slice, Image) and reversed_slice.bands == []


def test_cat_binds_leading_constant_to_later_real_source_and_keeps_first_metadata(ee, local):
    first_constant = ee.Image.constant(7).rename("blue").set("cat:first", "constant")
    raster = ee.ImageCollection("sentinel-2-l2a").first().select("blue").set("cat:first", "raster")
    # The pinned public helper folds left-to-right through Image.addBands. This
    # is the leading-constant regression whose later raster supplies the only
    # real grid while the first input supplies the retained properties.
    public_result = compile_sdk(ee, ee.Image.cat(first_constant, raster), local)
    assert public_result["bands"] == ["blue", "blue_1"]
    assert public_result["properties"]["cat:first"] == "constant"
    assert public_result["source_item_ids"] == ["a"]
    assert [node["arguments"]["value"] for node in graph_nodes(
        public_result, "local_ee_constant_on_grid")] == [7]
    loads = graph_nodes(public_result, "load_collection")
    assert len(loads) == 1
    assert loads[0]["arguments"]["_gee_item_ids"] == ["a"]
    assert loads[0]["arguments"]["spatial_extent"] == {
        "west": 0.0, "south": 0.0, "east": 2.0, "north": 2.0,
    }

    arrays = {"a": {"blue": np.array([np.nan, 4.0])}}
    data, names, _ = evaluate_graph(
        public_result, arrays, grid=np.array([[0.5, 0.5], [1.5, 1.5]]),
    )
    assert names == ["blue", "blue_1"]
    # The constant is independently valid on the real source grid. Source
    # NoData stays masked in the raster band.
    np.testing.assert_array_equal(data[0], [7.0, 7.0])
    assert np.isnan(data[1, 0]) and data[1, 1] == 4.0

    public_raster_first = compile_sdk(ee, ee.Image.cat(raster, first_constant), local)
    assert public_raster_first["properties"]["cat:first"] == "raster"
    repeated = compile_sdk(ee, ee.Image.cat(first_constant, raster, raster), local)
    assert repeated["bands"] == ["blue", "blue_1", "blue_2"]
    with pytest.raises(UnsupportedEEError, match="grid|constant"):
        compile_sdk(ee, ee.Image.cat(first_constant), local)
    expression = ee.Image(ee.ApiFunction.lookup("Image.cat").apply(
        {"images": [first_constant, raster]},
    ))
    serialized = encode(ee, expression)
    cat_call = next(node for node in walk(serialized) if node.get("functionName") == "Image.cat")
    assert len(cat_call["arguments"]["images"]) == 2

    result = compile_expression(serialized, *local)
    assert result["bands"] == ["blue", "blue_1"]
    assert result["properties"]["cat:first"] == "constant"
    assert result["source_item_ids"] == ["a"]
    assert [node["arguments"]["value"] for node in graph_nodes(
        result, "local_ee_constant_on_grid")] == [7]


def test_float_and_double_aliases_use_existing_real_cast_boundaries(ee, local):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("blue").set("cast:tag", "kept")
    float_expression, double_expression = image.float(), image.double()
    serialized_float, serialized_double = encode(ee, float_expression), encode(ee, double_expression)
    assert any(node.get("functionName") == "Image.float" for node in walk(serialized_float))
    assert any(node.get("functionName") == "Image.double" for node in walk(serialized_double))
    float_result = compile_expression(serialized_float, *local)
    double_result = compile_expression(serialized_double, *local)
    assert graph_nodes(float_result, "local_ee_to_float")
    assert graph_nodes(double_result, "local_ee_to_double")
    assert float_result["properties"]["cast:tag"] == double_result["properties"]["cast:tag"] == "kept"
    assert float_result["source_item_ids"] == double_result["source_item_ids"] == ["a"]

    arrays = {"a": {"blue": np.array([16_777_217.0, 1.25])}}
    float_data, float_names, _ = evaluate_graph(float_result, arrays)
    double_data, double_names, _ = evaluate_graph(double_result, arrays)
    assert float_names == double_names == ["blue"]
    np.testing.assert_array_equal(float_data.reshape(-1), [16_777_216.0, 1.25])
    np.testing.assert_array_equal(double_data.reshape(-1), [16_777_217.0, 1.25])

    # Casting a scalar constant before binding keeps the float32 rounding
    # boundary, while double retains the exact integer value on the same grid.
    constants = ee.ImageCollection("sentinel-2-l2a").first().select("blue").addBands(
        ee.Image.constant(16_777_217).float().rename("as_float"),
    ).addBands(ee.Image.constant(16_777_217).double().rename("as_double"))
    constant_result = compile_sdk(ee, constants, local)
    constant_arrays = {"a": {"blue": np.array([1.0, 2.0])}}
    constant_data, constant_names, _ = evaluate_graph(
        constant_result, constant_arrays,
        grid=np.array([[0.5, 0.5], [1.5, 1.5]]),
    )
    assert constant_names == ["blue", "as_float", "as_double"]
    np.testing.assert_array_equal(constant_data[1], [16_777_216.0, 16_777_216.0])
    np.testing.assert_array_equal(constant_data[2], [16_777_217.0, 16_777_217.0])


def test_float_double_aliases_cast_single_arrays_on_raw_and_public_paths(ee, local):
    source = ee.ImageCollection("sentinel-2-l2a").first().select(["red", "green"])
    array = source.toArray()
    public_float = compile_sdk(
        ee, array.float().arrayFlatten([["red", "green"]]), local,
    )
    assert public_float["bands"] == ["red", "green"]
    assert graph_nodes(public_float, "local_ee_to_float")
    values = {"a": {
        "red": np.array([16_777_217.0, 1.25]),
        "green": np.array([2_147_483_649.0, 2.5]),
    }}
    float_values = evaluated_bands(public_float, values)
    np.testing.assert_array_equal(float_values["red"], [16_777_216.0, 1.25])
    np.testing.assert_array_equal(float_values["green"], [2_147_483_648.0, 2.5])

    raw_double_image = ee.Image(ee.ApiFunction.lookup("Image.double").apply({
        "value": array,
    }))
    raw_double = compile_sdk(ee, raw_double_image.arrayGet([0]), local)
    assert graph_nodes(raw_double, "local_ee_to_double")
    double_values = evaluated_bands(raw_double, values)
    np.testing.assert_array_equal(double_values["array"], [16_777_217.0, 1.25])


def test_float_double_aliases_cast_every_array_in_a_bundle(ee, local):
    fit = ee.ImageCollection("sentinel-2-l2a").select(
        ["blue", "red", "green"],
    ).reduce(ee.Reducer.linearRegression(numX=1, numY=2))
    public_float = compile_sdk(
        ee,
        fit.float().select("coefficients").arrayFlatten([["x"], ["red", "green"]]),
        local,
    )
    assert public_float["kind"] == "image"
    assert public_float["bands"] == ["x_red", "x_green"]
    assert graph_nodes(public_float, "local_ee_to_float")

    raw_double_bundle = ee.Image(ee.ApiFunction.lookup("Image.double").apply({
        "value": fit,
    }))
    raw_double = compile_sdk(
        ee,
        raw_double_bundle.select("residuals").arrayFlatten([["red", "green"]]),
        local,
    )
    assert raw_double["kind"] == "image"
    assert raw_double["bands"] == ["red", "green"]
    assert graph_nodes(raw_double, "local_ee_to_double")


def test_exact_argument_maps_and_near_budget_fail_before_band_scan(local):
    assert BAND_PREPARATION_ARGUMENTS["Image.regexpRename"] == (
        frozenset({"input", "regex", "replacement"}), frozenset({"all"}),
    )
    assert BAND_PREPARATION_ARGUMENTS["Image.slice"] == (
        frozenset({"image", "start"}), frozenset({"end"}),
    )
    assert BAND_PREPARATION_ARGUMENTS["Image.cat"] == (
        frozenset({"images"}), frozenset(),
    )
    assert BAND_PREPARATION_ARGUMENTS["Image.float"] == (
        frozenset({"value"}), frozenset(),
    )
    assert BAND_PREPARATION_ARGUMENTS["Image.double"] == (
        frozenset({"value"}), frozenset(),
    )
    assert IMAGE_METADATA_RASTER_ARGUMENTS["Image.id"] == (
        frozenset({"element"}), frozenset(),
    )
    assert IMAGE_METADATA_RASTER_ARGUMENTS["Image.metadata"] == (
        frozenset({"image", "property"}), frozenset({"name"}),
    )

    class ScanTrap(list):
        def __len__(self):
            return 1

        def __iter__(self):
            raise AssertionError("band scan happened before budget rejection")

    image = Image([], {}, Source("sentinel-2-l2a", ("a",), ("blue",)))
    image.bands = ScanTrap()
    translator = Translator(*local, options=None)
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_image_band_preparation(
            translator, "Image.regexpRename",
            {"input": image, "regex": "x", "replacement": "y", "all": None},
        )

    translator.steps = 49_998
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_image_band_preparation(translator, "Image.cat", {"images": [image]})


def test_every_new_algorithm_rejects_unknown_arguments(ee, local):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("blue")
    raw_cat = ee.Image(ee.ApiFunction.lookup("Image.cat").apply({"images": [image]}))
    expressions = [
        (image.regexpRename("b", "B"), "Image.regexpRename"),
        (image.slice(0, None), "Image.slice"),
        (image.float(), "Image.float"),
        (image.double(), "Image.double"),
        (raw_cat, "Image.cat"),
        (image.id(), "Image.id"),
        (image.metadata("CLOUDY_PIXEL_PERCENTAGE"), "Image.metadata"),
    ]
    for expression, algorithm in expressions:
        encoded = copy.deepcopy(encode(ee, expression))
        mutate_invocation(encoded, algorithm, "unexpected", True)
        with pytest.raises(UnsupportedEEError, match="unexpected"):
            compile_expression(encoded, *local)
