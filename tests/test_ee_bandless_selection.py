"""Pinned EE select/rename empty-list semantics for scalar Images."""
from __future__ import annotations

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_values import GeometryValue
from gee.compat.earthengine.ir import Image, Pixel, Source
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError
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


def _evaluate(context, value):
    ee, catalog, items = context
    wire = ee.serializer.encode(value, for_cloud_api=False)
    return Translator(catalog, items, {}).evaluate(wire), wire


def _walk(value):
    if isinstance(value, dict):
        if value.get("type") == "Invocation":
            yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _resolve(value, scope):
    seen = set()
    while isinstance(value, dict) and value.get("type") == "ValueRef":
        key = value["value"]
        if key in seen or key not in scope:
            raise AssertionError(f"unresolved/cyclic SDK reference: {key}")
        seen.add(key)
        value = scope[key]
    return value


def test_select_empty_uses_official_empty_selector_and_keeps_envelope(context):
    ee, _, _ = context
    source = ee.Image(ee.ImageCollection("sentinel-2-l2a").first())
    selected, wire = _evaluate(context, source.set("marker", "preserved").select([]))
    assert isinstance(selected, Image)
    assert selected.bands == []
    assert selected.source.ids == ("scene-a",)
    assert selected.props["marker"] == "preserved"

    invocation = next(node for node in _walk(wire)
                      if node.get("functionName") == "Image.select")
    selectors = _resolve(invocation["arguments"]["bandSelectors"], dict(wire["scope"]))
    assert selectors == []


def test_empty_selector_and_empty_rename_keep_zero_bands(context):
    ee, _, _ = context
    raster = ee.Image(ee.ImageCollection("sentinel-2-l2a").first())
    selected, _ = _evaluate(context, raster.select([], []))
    renamed, _ = _evaluate(context, raster.select([]).rename([]))
    assert selected.bands == renamed.bands == []
    assert selected.source.ids == renamed.source.ids == ("scene-a",)


def test_empty_rename_still_checks_the_selected_band_count(context):
    ee, _, _ = context
    raster = ee.Image(ee.ImageCollection("sentinel-2-l2a").first())
    with pytest.raises(UnsupportedEEError, match="New band names"):
        _evaluate(context, raster.rename([]))


def test_unknown_nonempty_selectors_remain_explicit_errors(context):
    ee, _, _ = context
    raster = ee.Image(ee.ImageCollection("sentinel-2-l2a").first())
    with pytest.raises(UnsupportedEEError, match="did not match"):
        _evaluate(context, raster.select("no_such_band"))


def test_official_dataset_alias_survives_empty_selection_without_bands(context):
    ee, _, _ = context
    alias = ee.Image(ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").first())
    selected, _ = _evaluate(context, alias.select([]))
    assert selected.bands == []
    assert selected.source.alias is True
    assert selected.source.ids == ("scene-a",)


def test_empty_selection_detaches_nested_properties_and_footprint(context):
    _, catalog, items = context
    translator = Translator(catalog, items, {})
    source = Source("sentinel-2-l2a", ("scene-a",), ("blue",))
    properties = {"nested": {"tags": ["first"]}}
    footprint = {
        "type": "Polygon", "geodesic": False,
        "coordinates": [[[100, 30], [101, 30], [101, 31], [100, 31], [100, 30]]],
    }
    image = Image([("blue", Pixel("band", (source, "blue")))], properties,
                  source, footprint=footprint)
    selected = translator.select(image, [])

    selected.props["nested"]["tags"].append("selected")
    selected.footprint["coordinates"][0][0][0] = 99
    assert image.props["nested"]["tags"] == ["first"]
    assert image.footprint["coordinates"][0][0][0] == 100


def test_empty_selection_owns_tuple_geometry_without_losing_its_model(context):
    _, catalog, items = context
    translator = Translator(catalog, items, {})
    source = Source("sentinel-2-l2a", ("scene-a",), ("blue",))
    coordinates = (((100, 30), (101, 30), (101, 31), (100, 31), (100, 30)),)
    footprint = GeometryValue(
        {"type": "Polygon", "coordinates": coordinates},
        {"geodesic": False, "evenOdd": True}, validated=True,
    )
    image = Image(
        [("blue", Pixel("band", (source, "blue")))], {}, source,
        footprint=footprint,
    )

    selected = translator.select(image, [], [])

    assert selected.bands == []
    assert isinstance(selected.footprint, GeometryValue)
    assert selected.footprint is not footprint
    assert selected.footprint.geometry_metadata["evenOdd"] is True
    selected.footprint["coordinates"][0][0][0] = 99
    assert footprint["coordinates"][0][0][0] == 100


def test_select_precharges_large_names_before_materializing_the_result(context):
    _, catalog, items = context
    translator = Translator(catalog, items, {})
    translator.steps = 49_960
    source = Source("sentinel-2-l2a", ("scene-a",), ("blue",))
    image = Image([("blue", Pixel("band", (source, "blue")))], {}, source)
    with pytest.raises(UnsupportedEEError, match="compilation work budget"):
        translator.select(image, "blue", ["N" * 50_000])
    assert translator.steps == 49_979
    assert image.bands == [("blue", Pixel("band", (source, "blue")))]


def test_empty_select_discards_large_band_names_without_scanning_them(context):
    _, catalog, items = context
    translator = Translator(catalog, items, {})
    image = Image([("N" * 25_000, Pixel("opaque", ()))], {})
    assert translator.select(image, []).bands == []


def test_select_precharges_large_selector_near_shared_budget(context):
    _, catalog, items = context
    translator = Translator(catalog, items, {})
    translator.steps = 49_990
    source = Source("sentinel-2-l2a", ("scene-a",), ("blue",))
    image = Image([("T" * 25_000, Pixel("band", (source, "blue")))], {}, source)
    with pytest.raises(UnsupportedEEError, match="compilation work budget"):
        translator.select(image, "S" * 25_000)
    assert translator.steps == 49_994


def test_exact_selector_does_not_scan_unrelated_long_band_names(context):
    _, catalog, items = context
    translator = Translator(catalog, items, {})
    translator.steps = 49_980
    source = Source("sentinel-2-l2a", ("scene-a",), ("blue",))
    image = Image([
        ("N" * 25_000, Pixel("band", (source, "blue"))),
        ("blue", Pixel("band", (source, "blue"))),
    ], {}, source)
    selected = translator.select(image, "blue")
    assert [name for name, _ in selected.bands] == ["blue"]
    assert translator.steps == 49_999


def test_select_regex_uses_re2_for_official_pattern_matching(context):
    _, catalog, items = context
    source = Source("sentinel-2-l2a", ("scene-a",), ("red", "nir", "SCL"))
    image = Image([
        (name, Pixel("band", (source, name))) for name in ("red", "nir", "SCL")
    ], {}, source)
    selected = Translator(catalog, items, {}).select(image, "r.*")
    assert [name for name, _ in selected.bands] == ["red"]


@pytest.mark.parametrize("pattern", [r"(?=red).*", r"(r)\1", r"\C"])
def test_select_rejects_regex_extensions_outside_re2(context, pattern):
    _, catalog, items = context
    source = Source("sentinel-2-l2a", ("scene-a",), ("red",))
    image = Image([("red", Pixel("band", (source, "red")))], {}, source)
    with pytest.raises(UnsupportedEEError, match="Invalid band selector"):
        Translator(catalog, items, {}).select(image, pattern)
