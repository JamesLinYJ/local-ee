"""Casts and grid-only constants must not escape independent mask ownership."""
from __future__ import annotations

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.ir import Image, Pixel, Source, const, unary
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


def compiled(context, value):
    ee, catalog, items = context
    return compile_expression(
        ee.serializer.encode(value, for_cloud_api=False), catalog, items,
    )


def scene(ee):
    return ee.Image(ee.ImageCollection("sentinel-2-l2a").first()).select("red")


@pytest.mark.parametrize("op", ["to_float", "to_double"])
def test_cast_changes_only_the_science_branch_and_keeps_prior_stages(op):
    raw = Pixel("to_float", (const(16777219),))
    weight = const(0.12345678901234568)
    carrier = Pixel("with_mask", (raw, weight))
    original = Image([("red", carrier)], {"kind": "source"})
    cast = unary(original, op)

    assert cast is not original and cast.bands is not original.bands
    assert original.bands[0][1] is carrier
    result = cast.bands[0][1]
    assert result.op == "with_mask"
    assert result.args[0].op == op
    assert result.args[0].args == (raw,)
    assert result.args[1] is weight


@pytest.mark.parametrize("method", ["toFloat", "toDouble", "float", "double"])
def test_official_cast_aliases_reach_the_audited_sampler_only(context, method):
    ee, _, _ = context
    weighted = scene(ee).updateMask(0.25)
    cast = getattr(weighted, method)()
    result = compiled(context, cast.sample(dropNulls=False))

    assert result["kind"] == "sample_table"
    assert result["bands"] == ["system:index", "red", ".geo"]
    assert any(node["process_id"] == "local_ee_mask_weights"
               for node in result["process_graph"].values())
    with pytest.raises(UnsupportedEEError, match="mask-aware consumer"):
        compiled(context, cast)


def test_constant_class_uses_raw_grid_without_reading_masked_values(context):
    ee, _, _ = context
    weighted = scene(ee).toDouble().updateMask(0.25)
    training = weighted.addBands(ee.Image.constant(2).rename("class"))
    # Selecting only the class does not materialize a public unmasked science
    # band. The constant owns its validity on the finite source footprint.
    result = compiled(context, training.select("class"))
    processes = [node["process_id"] for node in result["process_graph"].values()]
    assert result["bands"] == ["class"]
    assert "local_ee_constant_on_grid" in processes
    assert "local_ee_mask_weights" not in processes
    assert result["source_item_ids"] == ["scene-a"]
    with pytest.raises(UnsupportedEEError, match="mask-aware consumer"):
        compiled(context, training.select("red"))


@pytest.mark.parametrize("wrapper", ["arithmetic", "clip", "unmask", "integer"])
def test_grid_template_does_not_strip_masks_under_unsupported_wrappers(context, wrapper):
    ee, _, _ = context
    weighted = scene(ee).updateMask(0.25)
    if wrapper == "arithmetic":
        wrapped = weighted.add(1)
    elif wrapper == "clip":
        wrapped = weighted.clip(ee.Geometry.Rectangle([0, 0, 1, 1], None, False))
    elif wrapper == "unmask":
        wrapped = weighted.unmask(0)
    else:
        wrapped = weighted.toInt()
    classes = wrapped.addBands(ee.Image.constant(2).rename("class")).select("class")
    with pytest.raises(UnsupportedEEError, match="mask-aware consumer"):
        compiled(context, classes)


@pytest.mark.parametrize("consumer", ["sample", "sample_roi", "sample_regions"])
def test_scalar_science_does_not_invent_a_grid_from_its_mask(context, consumer):
    ee, _, _ = context
    weighted = ee.Image.constant(2).updateMask(scene(ee).multiply(0.5))
    if consumer == "sample_regions":
        samples = weighted.sampleRegions(collection=ee.FeatureCollection([
            ee.Feature(ee.Geometry.Point([100.5, 30.5])),
        ]))
    elif consumer == "sample_roi":
        samples = weighted.sample(region=ee.Geometry.Rectangle(
            [100, 30, 101, 31], None, False,
        ))
    else:
        samples = weighted.sample()
    with pytest.raises(UnsupportedEEError):
        compiled(context, samples)


@pytest.mark.parametrize("wrapped", [False, True])
def test_internal_phantom_source_cannot_authorize_a_scalar_as_raster(context, wrapped):
    _, catalog, items = context
    source = Source("sentinel-2-l2a", ("scene-a",), ("red",))
    raw = Pixel("constant", (1, source))
    if wrapped:
        raw = Pixel("to_double", (raw, source))
    weight = Pixel("reduce_t", (Pixel("band", (source, "red")), "first"))
    graph = Graph(Translator(catalog, items, {}))
    with pytest.raises(UnsupportedEEError, match="source lineage must match"):
        graph.expression(Pixel("mask_apply", (raw, weight)))
    assert not any(node["process_id"] == "local_ee_mask_weights"
                   for node in graph.graph.values())
