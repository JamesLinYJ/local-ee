"""Official transparent Image construction and bounded mask replacement."""
from __future__ import annotations

import math
from copy import deepcopy

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.image_mask_setter import fold_set_value
from gee.compat.earthengine.ir import Image, Pixel, const
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
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


def compile_value(context, value):
    ee, catalog, items = context
    return compile_expression(ee.serializer.encode(value, for_cloud_api=False), catalog, items)


@pytest.mark.parametrize("constructor", [lambda ee: ee.Image(), lambda ee: ee.Image(None)])
def test_transparent_constructor_has_one_named_band(context, constructor):
    ee, _, _ = context
    empty = constructor(ee)
    assert compile_value(context, empty.bandNames())["value"] == ["constant"]
    assert compile_value(context, empty.mask().bandNames())["value"] == ["constant"]
    with pytest.raises(UnsupportedEEError, match="mask-aware consumer"):
        compile_value(context, empty)


@pytest.mark.parametrize("text", [
    "a.red * 2 + offset", "a[0] * 2 + offset", "renamed = a.red * 2 + offset",
    "sqrt(abs(a.red * 2 + offset))",
])
def test_named_expression_uses_real_arguments_and_keeps_empty_receiver(context, text):
    ee, _, _ = context
    source = ee.Image("scene-a").select("red").toDouble()
    value = ee.Image().expression(text, {"a": source, "offset": 2})
    result = compile_value(context, value)
    assert result["source_item_ids"] == ["scene-a"]
    assert result["bands"] == (["renamed"] if text.startswith("renamed") else ["red"])
    assert not any(node["process_id"] == "local_ee_unmask"
                   for node in result["process_graph"].values())


@pytest.mark.parametrize("weight", [0, 1, 0.25, 5e-324])
def test_replacement_recovers_zero_science_but_update_stays_masked(context, weight):
    ee, catalog, items = context
    source = ee.Image("scene-a").select("red").toDouble().updateMask(0)
    replaced = source.mask(weight)
    descriptor = compile_value(context, replaced.sample(dropNulls=False))
    assert descriptor["kind"] == "sample_table"
    assert descriptor["source_item_ids"] == ["scene-a"]
    assert any(node["process_id"] == "local_ee_unmask"
               for node in descriptor["process_graph"].values())

    translator = Translator(catalog, items, {})
    image = translator.evaluate(ee.serializer.encode(replaced, for_cloud_api=False))
    assert image.bands[0][1].op == "with_mask"
    assert image.bands[0][1].args[0].op == "mask_set_value"
    assert image.bands[0][1].args[1].args[0].op == "mask_validity"
    assert image.bands[0][1].args[1].args[0].args[0] is image.bands[0][1].args[0]


@pytest.mark.parametrize("raw,old,expected", [
    (None, 1, 0.0), (17.25, 0, 0.0), (17.25, 0.25, 17.25),
    (17.25, 5e-324, 17.25), (-0.0, 1, -0.0),
])
def test_replacement_value_fold_tracks_visibility_separately(raw, old, expected):
    result = fold_set_value(raw, old)
    assert result == expected
    assert math.copysign(1, result) == math.copysign(1, expected)


@pytest.mark.parametrize("raw,old", [
    (math.inf, 0), (-math.inf, 0), (1, -0.1), (1, 1.1), (1, math.nan),
])
def test_zero_weight_does_not_hide_invalid_science_or_weights(raw, old):
    with pytest.raises(UnsupportedEEError, match="finite"):
        fold_set_value(raw, old)


def test_zero_fill_does_not_promote_nominal_float32():
    translator = Translator([], {}, {})
    graph = Graph(translator)
    for raw, is_double in [(const(1), False), (Pixel("to_double", (const(1),)), True)]:
        filled = Pixel("mask_set_value", (raw, const(0.25)))
        assert graph.has_double_precision(filled) is is_double
        assert graph.expression(filled)[:2] == (1.0, None)


def test_setter_precharges_before_emitting_bands_or_mutating_input():
    translator = Translator([], {}, {})
    translator.steps = 49_999
    image = Image([("x", const(7))], {"user": [1]})
    with pytest.raises(UnsupportedEEError, match="50000"):
        translator.invoke("Image.mask", {"image": image, "mask": 0})
    assert image.bands == [("x", const(7))]
    assert image.props == {"user": [1]}
    assert translator.steps == 49_999


def test_float32_expression_rejects_conflicting_selected_asset_grids(context):
    ee, catalog, original_items = context
    source = ee.Image("scene-a")
    value = ee.Image().expression("n-r", {
        "n": source.select("nir"), "r": source.select("red"),
    })
    items = deepcopy(original_items)
    scene = next(item for rows in items.values() for item in rows if item["id"] == "scene-a")
    grid = {"proj:code": "EPSG:4326", "proj:transform": [1, 0, 100, 0, -1, 31]}
    scene["properties"].update(grid)
    scene["assets"] = {name: dict(grid) for name in ("red", "nir")}
    for name in ("red", "nir"):
        scene["assets"][name].update(grid)
    wire = ee.serializer.encode(value, for_cloud_api=False)
    assert compile_expression(wire, catalog, items)["source_item_ids"] == ["scene-a"]
    scene["assets"]["nir"]["proj:transform"] = [1, 0, 100.5, 0, -1, 31]
    with pytest.raises(UnsupportedEEError, match="common pixel grid"):
        compile_expression(wire, catalog, items)
    # Only actual selected branches require alignment. An unused declaration
    # is type checked but cannot make a red-only calculation consume nir.
    red_only = ee.Image().expression("r+1", {
        "r": source.select("red"), "unused": source.select("nir"),
    })
    assert compile_expression(ee.serializer.encode(red_only, for_cloud_api=False),
                              catalog, items)["bands"] == ["red"]


def test_aliases_share_actual_item_asset_checks_but_unused_vars_do_not(context):
    ee, catalog, original = context
    items = deepcopy(original)
    scene = next(item for rows in items.values() for item in rows if item["id"] == "scene-a")
    grid = {"proj:code": "EPSG:4326", "proj:transform": [1, 0, 100, 0, -1, 31]}
    scene["assets"] = {name: dict(grid) for name in ("red", "nir")}
    red = ee.Image("scene-a").select("red")
    alias = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filter(
        ee.Filter.eq("system:index", "scene-a")).first().select("B8")
    value = ee.Image().expression("r+n", {"r": red, "n": alias})
    wire = ee.serializer.encode(value, for_cloud_api=False)
    assert compile_expression(wire, catalog, items)["bands"] == ["red"]
    scene["assets"]["nir"]["proj:transform"] = [1, 0, 100.5, 0, -1, 31]
    with pytest.raises(UnsupportedEEError, match="common pixel grid"):
        compile_expression(wire, catalog, items)
    unused = ee.Image().expression("r", {"r": red, "unused": alias})
    assert compile_expression(ee.serializer.encode(unused, for_cloud_api=False),
                              catalog, items)["bands"] == ["red"]
