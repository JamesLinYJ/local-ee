"""Finite-grid binding for source-free independent mask value/weight bands."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from gee.compat.earthengine.constant_bands import bind_source_bands
from gee.compat.earthengine import constant_mask_binding
from gee.compat.earthengine.ir import Image, Pixel, Source, UnsupportedEEError, const
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs
from gee.sampling_spec import decode_sampling_spec


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


def test_binary_guard_inside_constant_setter_binds_without_skipping_validation(ee_context):
    from gee.compat.earthengine.decoder import Translator

    ee, catalog, items = ee_context
    constant = ee.Image.constant(3).updateMask(0).mask(1).rename("restored")
    image = Translator(catalog, items, {}).evaluate(
        ee.serializer.encode(constant, for_cloud_api=False))
    assert constant_mask_binding._fold_closed_scalar(image.bands[0][1].args[0]) == 0
    result = compile_expression(ee.serializer.encode(
        ee.Image("scene-a").select("red").addBands(constant).sample(dropNulls=False),
        for_cloud_api=False), catalog, items)
    assert [name for name in result["bands"] if name not in {"system:index", ".geo"}] == ["red", "restored"]
    assert result["source_item_ids"] == ["scene-a"]
    bad = Pixel("mask_guard", (Pixel("constant", (float("inf"),)),))
    with pytest.raises(UnsupportedEEError, match="finite"):
        constant_mask_binding._fold_closed_scalar(bad)


def children(pixel):
    if isinstance(pixel, Pixel):
        yield pixel
        for argument in pixel.args:
            yield from children(argument)
    elif isinstance(pixel, (tuple, list)):
        for child in pixel:
            yield from children(child)


def assert_grid_pair(pixel, destination):
    assert pixel.op == "with_mask"
    raw, weight = pixel.args
    raw_constants = [node for node in children(raw) if node.op == "on_grid"]
    weight_constants = [node for node in children(weight) if node.op == "on_grid"]
    assert raw_constants and weight_constants
    for node in (*raw_constants, *weight_constants):
        assert node.args[1] is destination.bands[0][1]
        assert node.args[2] is destination.source


def test_direct_with_mask_branches_bind_separately_to_the_destination_science_grid():
    destination = raster_destination()
    source = Image([("fractional", Pixel("with_mask", (const(7), const(0.25))))], {})
    translator = SimpleNamespace(steps=0)

    bound = bind_source_bands(source, destination, translator=translator)

    assert len(bound) == 1
    assert_grid_pair(bound[0][1], destination)
    assert translator.steps > 0
    raw, weight = bound[0][1].args
    assert raw.args[0].args == (7,)
    assert weight.args[0].args == (0.25,)


def test_setter_projection_closure_and_internal_nodata_remain_in_the_dag():
    destination = raster_destination()
    missing_old_science = Pixel(
        "to_float", (Pixel("if", (const(0), const(7), const(None))),),
    )
    old = Pixel("mask_set_value", (missing_old_science, const(0)))
    nodata = Pixel("mask_apply", (const(None), const(1)))
    carrier = Pixel("with_mask", (old, Pixel("mask_update", (
        Pixel("mask_validity", (old,)), nodata,
    ))))
    translator = SimpleNamespace(steps=0)

    bound = bind_source_bands(
        Image([("filled", carrier)], {}), destination, translator=translator,
    )[0][1]

    assert_grid_pair(bound, destination)
    ops = [node.op for node in children(bound)]
    assert ops.count("mask_set_value") == 2
    assert "mask_validity" in ops and "mask_update" in ops and "mask_apply" in ops
    assert all(not (node.op == "constant" and node.args == (None,)) for node in children(bound))
    assert any(node.op == "on_grid" for node in children(bound.args[1]))


def test_float32_cast_stays_on_science_value_and_does_not_narrow_weight():
    destination = raster_destination()
    carrier = Pixel("with_mask", (
        Pixel("to_float", (const(16_777_219),)), const(0.25),
    ))
    source = Image([("fractional", Pixel("to_float", (carrier,)))], {})

    bound = bind_source_bands(source, destination, translator=SimpleNamespace(steps=0))[0][1]

    raw, weight = bound.args
    assert raw.op == "to_float"
    assert raw.args[0].op == "to_float"
    assert raw.args[0].args[0].op == "on_grid"
    assert raw.args[0].args[0].args[0].args == (16_777_219,)
    assert weight.op == "on_grid"
    assert weight.args[0].args == (0.25,)


def test_weight_only_raster_cannot_supply_the_missing_science_grid():
    destination = raster_destination()
    weight_source = Source("local", ("tile-a",), ("mask",))
    mask_band = Pixel("band", (weight_source, "mask"))
    carrier = Pixel("with_mask", (const(7), Pixel("mask_validity", (mask_band,))))

    with pytest.raises(UnsupportedEEError, match="cannot borrow a grid from its mask branch"):
        bind_source_bands(
            Image([("fractional", carrier)], {}), destination,
            translator=SimpleNamespace(steps=0),
        )


@pytest.mark.parametrize(("invalid", "message"), [
    (-0.001, "finite weights in\\[0,1\\]"),
    (1.001, "finite weights in\\[0,1\\]"),
    (float("nan"), "non-finite"),
    (float("inf"), "non-finite"),
])
def test_closed_scalar_weight_still_obeys_finite_unit_interval_policy(invalid, message):
    destination = raster_destination()
    source = Image([("fractional", Pixel("with_mask", (
        const(7), Pixel("constant", (invalid,)),
    )))], {})

    with pytest.raises(UnsupportedEEError, match=message):
        bind_source_bands(source, destination, translator=SimpleNamespace(steps=0))


def test_explicitly_clipped_masked_constant_remains_rejected():
    destination = raster_destination()
    clipped = Pixel("clip", (const(7), {"type": "Polygon", "coordinates": []}))
    source = Image([("fractional", Pixel("with_mask", (clipped, const(0.25))))], {})

    with pytest.raises(UnsupportedEEError):
        bind_source_bands(source, destination, translator=SimpleNamespace(steps=0))


def test_unbound_carrier_stays_unbound_and_missing_translator_cannot_bypass_budget():
    source = Image([("fractional", Pixel("with_mask", (const(7), const(0.25))))], {})
    # Without an actual destination, the original carrier is left unbound.
    unbound = bind_source_bands(source, Image([], {}), translator=SimpleNamespace(steps=0))
    assert unbound[0][1] is source.bands[0][1]
    with pytest.raises(UnsupportedEEError, match="shared50000-step work budget"):
        bind_source_bands(source, raster_destination())


def test_binding_precharges_shared_work_before_destination_scan_and_rejects_over_budget():
    destination = raster_destination()
    source = Image([("fractional", Pixel("with_mask", (const(7), const(0.25))))], {})
    translator = SimpleNamespace(steps=49_990)

    with pytest.raises(UnsupportedEEError, match="50000-step"):
        bind_source_bands(source, destination, translator=translator)
    assert translator.steps == 49_990


def test_destination_band_count_is_reserved_before_any_closure_planner_scan(monkeypatch):
    destination = raster_destination()
    destination.bands = destination.bands * 50_001
    source = Image([("fractional", Pixel("with_mask", (const(7), const(0.25))))], {})
    translator = SimpleNamespace(steps=0)

    def planner_must_not_run(*args, **kwargs):
        pytest.fail("destination list must be capped before closure planning")

    monkeypatch.setattr(
        "gee.compat.earthengine.scalar_work_plan.plan_scalar_input_work",
        planner_must_not_run,
    )
    with pytest.raises(UnsupportedEEError, match="shared50000-step"):
        bind_source_bands(source, destination, translator=translator)
    assert 0 < translator.steps < 50_000


def test_masked_destination_depth_is_checked_before_science_grid_scan(monkeypatch):
    destination = raster_destination()
    deep = destination.bands[0][1]
    for _ in range(100):
        deep = Pixel("to_float", (deep,))
    destination.bands = [("nir", deep)]
    source = Image([("fractional", Pixel("with_mask", (const(7), const(0.25))))], {})

    def science_scan_must_not_run(*args, **kwargs):
        pytest.fail("depth preflight must precede the memoized science-grid scan")

    monkeypatch.setattr(constant_mask_binding, "has_science_grid", science_scan_must_not_run)
    with pytest.raises(UnsupportedEEError, match="depth 96"):
        bind_source_bands(source, destination, translator=SimpleNamespace(steps=0))


def test_ordinary_constant_binding_keeps_generic_grid_scan_without_science_rescan(monkeypatch):
    destination = raster_destination()
    source = Image([("constant", const(7))], {})

    def science_scan_must_not_run(*args, **kwargs):
        pytest.fail("ordinary constant binding must not add an uncharged science scan")

    monkeypatch.setattr(constant_mask_binding, "has_science_grid", science_scan_must_not_run)
    bound = bind_source_bands(
        source, destination, translator=SimpleNamespace(steps=0),
    )

    assert bound[0][1].op == "on_grid"
    assert bound[0][1].args[1] is destination.bands[0][1]


def test_public_constant_none_remains_outside_the_masked_binding_path():
    with pytest.raises(UnsupportedEEError, match="finite numeric"):
        bind_source_bands(
            Image([("null", const(None))], {}), raster_destination(),
            translator=SimpleNamespace(steps=0),
        )


def test_official_sdk_setter_chain_binds_before_the_audited_sample_consumer(ee_context):
    ee, catalog, items = ee_context
    raster = ee.ImageCollection("sentinel-2-l2a").first().select("red")
    image = ee.Image(7).mask(0).mask(1).set("owner", "first").addBands(raster)
    encoded = ee.serializer.encode(image.sample(dropNulls=False), for_cloud_api=False)

    result = compile_expression(encoded, catalog, items)
    owner = compile_expression(
        ee.serializer.encode(image.get("owner"), for_cloud_api=False), catalog, items,
    )

    assert result["kind"] == "sample_table"
    validate(result["process_graph"])
    assert decode_sampling_spec(result["sample_spec"])["bands"] == ["constant", "red"]
    assert result["source_item_ids"] == ["scene-a"]
    assert owner["value"] == "first"

