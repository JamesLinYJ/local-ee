"""Source-lineage preflight for actual and source-free weighted bands."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from gee.compat.earthengine.constant_bands import bind_source_bands
from gee.compat.earthengine.ir import Image, Pixel, Source, UnsupportedEEError, const
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from gee.sampling_spec import decode_sampling_spec
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee_context():
    ee = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert ee.__version__ == "1.7.49"
    metadata, items, _ = synthetic_inputs()
    return ee, [metadata], items


def raster_destination():
    source = Source("local", ("tile-a",), ("nir",))
    band = Pixel("band", (source, "nir"))
    return Image([("nir", band)], {"system:index": "tile-a"}, source)


def test_actual_clipped_weighted_raster_bypasses_constant_only_binding(ee_context):
    ee, catalog, items = ee_context
    red = ee.Image("scene-a").select("red")
    planar_roi = ee.Geometry.Rectangle(
        [1, 0, 5, 1], ee.Projection("EPSG:4326"), False,
    )
    image = red.addBands(
        red.clip(planar_roi).updateMask(0.25).rename("clipped"),
    )

    result = compile_expression(
        ee.serializer.encode(image.sample(dropNulls=False), for_cloud_api=False),
        catalog, items,
    )

    assert result["kind"] == "sample_table"
    validate(result["process_graph"])
    assert decode_sampling_spec(result["sample_spec"])["bands"] == ["red", "clipped"]
    assert result["source_item_ids"] == ["scene-a"]


def test_clipped_actual_science_returns_unchanged_after_bounded_lineage_scan():
    destination = raster_destination()
    band = destination.bands[0][1]
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    clipped = Pixel("clip", (band, geometry))
    weight = Pixel("mask_update", (
        Pixel("mask_validity", (clipped,)), const(0.25),
    ))
    carrier = Pixel("with_mask", (clipped, weight))
    translator = SimpleNamespace(steps=0)

    bound = bind_source_bands(
        Image([("clipped", carrier)], {}), destination, translator=translator,
    )

    assert bound[0][1] is carrier
    assert 0 < translator.steps < 50_000


def test_actual_science_scan_rejects_a_deep_weight_sibling_instead_of_short_circuiting():
    destination = raster_destination()
    weight = const(0.25)
    for _ in range(100):
        weight = Pixel("to_float", (weight,))
    carrier = Pixel("with_mask", (destination.bands[0][1], weight))
    translator = SimpleNamespace(steps=0)

    with pytest.raises(UnsupportedEEError, match="depth 96"):
        bind_source_bands(
            Image([("weighted", carrier)], {}), destination,
            translator=translator,
        )


def test_shared_subtree_cache_checks_its_full_occurrence_height():
    destination = raster_destination()
    shared = destination.bands[0][1]
    for _ in range(10):
        shared = Pixel("to_float", (shared,))
    deep = shared
    for _ in range(84):
        deep = Pixel("to_float", (deep,))
    raw = Pixel("add", (shared, deep))
    carrier = Pixel("with_mask", (raw, const(0.25)))

    with pytest.raises(UnsupportedEEError, match="depth 96"):
        bind_source_bands(
            Image([("weighted", carrier)], {}), destination,
            translator=SimpleNamespace(steps=0),
        )


def test_cached_constant_height_includes_its_scalar_leaf_depth():
    destination = raster_destination()
    shared = const(7)
    deep = shared
    for _ in range(93):
        deep = Pixel("to_float", (deep,))
    raw = Pixel("add", (destination.bands[0][1], shared, deep))
    carrier = Pixel("with_mask", (raw, const(0.25)))

    with pytest.raises(UnsupportedEEError, match="depth 96"):
        bind_source_bands(
            Image([("weighted", carrier)], {}), destination,
            translator=SimpleNamespace(steps=0),
        )


def test_actual_science_scan_is_charged_to_the_shared_work_budget():
    destination = raster_destination()
    carrier = Pixel("with_mask", (
        Pixel("clip", (
            destination.bands[0][1],
            {"type": "Polygon", "coordinates": []},
        )), const(0.25),
    ))
    translator = SimpleNamespace(steps=49_999)

    with pytest.raises(UnsupportedEEError, match="50000-step"):
        bind_source_bands(
            Image([("weighted", carrier)], {}), destination,
            translator=translator,
        )
    assert translator.steps == 49_999


def test_actual_science_scan_caps_large_tuple_siblings_before_iteration():
    destination = raster_destination()
    weight = Pixel("opaque", (tuple(range(50_001)),))
    carrier = Pixel("with_mask", (destination.bands[0][1], weight))
    translator = SimpleNamespace(steps=0)

    with pytest.raises(UnsupportedEEError, match="50000-step"):
        bind_source_bands(
            Image([("weighted", carrier)], {}), destination,
            translator=translator,
        )
    assert translator.steps == 0


def test_mask_only_raster_still_cannot_authorize_source_free_science():
    destination = raster_destination()
    mask_source = Source("local", ("tile-a",), ("mask",))
    mask_band = Pixel("band", (mask_source, "mask"))
    carrier = Pixel("with_mask", (
        const(7), Pixel("mask_validity", (mask_band,)),
    ))

    with pytest.raises(UnsupportedEEError, match="cannot borrow a grid from its mask branch"):
        bind_source_bands(
            Image([("weighted", carrier)], {}), destination,
            translator=SimpleNamespace(steps=0),
        )
