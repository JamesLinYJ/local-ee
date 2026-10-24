"""Compiler routing and historical explicit-planar clip behavior."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from gee.compat.earthengine.ir import UnsupportedEEError
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def local_catalog():
    metadata, default_items, _ = synthetic_inputs()
    items = deepcopy(default_items)
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32649"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3000000]
    return metadata, items


def compile_sdk(ee, value, *, misalign_scene_b=False):
    metadata, items = local_catalog()
    if misalign_scene_b:
        items["sentinel-2-l2a"][1]["properties"]["proj:transform"][2] += 5
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, [metadata], items)


def _default_polygon():
    return {
        "type": "Polygon",
        "coordinates": [[
            [100.1, 30.1], [100.9, 30.1], [100.9, 30.9],
            [100.1, 30.9], [100.1, 30.1],
        ]],
    }


def test_default_clip_sample_builds_a_separate_weight_process_and_scientific_sample(ee):
    image = (
        ee.ImageCollection("sentinel-2-l2a").first().select("nir")
        .clip(_default_polygon())
    )
    result = compile_sdk(ee, image.sample(scale=10, geometries=True))

    assert result["kind"] == "sample_table"
    assert result["bands"] == ["system:index", "nir", ".geo"]
    nodes = list(result["process_graph"].values())
    coverage = [node for node in nodes
                if node["process_id"] == "local_ee_clip_coverage"]
    masks = [node for node in nodes
             if node["process_id"] == "local_ee_mask_weights"]
    assert len(coverage) == 1
    assert len(masks) == 1
    data_node = result["process_graph"][coverage[0]["arguments"]["data"]["from_node"]]
    assert data_node["process_id"] == "reduce_dimension"
    assert coverage[0]["arguments"]["spec"].startswith(
        '{"model":"great-circle","polygons":['
    )
    assert "mask_polygon" not in [node["process_id"] for node in nodes]
    assert result["source_item_ids"] == ["scene-a"]


def test_explicit_planar_clip_stays_on_the_historical_center_mask_path(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    result = compile_sdk(ee, image.clip({**_default_polygon(), "geodesic": False}))

    ids = [node["process_id"] for node in result["process_graph"].values()]
    assert "mask_polygon" in ids
    assert "local_ee_clip_coverage" not in ids
    assert result["bands"] == ["nir"]


def test_nested_planar_clip_remains_supported_but_spherical_composition_rejects(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    first = {**_default_polygon(), "coordinates": [[
        [100.2, 30.2], [100.8, 30.2], [100.8, 30.8],
        [100.2, 30.8], [100.2, 30.2],
    ]], "geodesic": False}
    second = {**_default_polygon(), "geodesic": False}

    planar = compile_sdk(ee, image.clip(first).clip(second))
    assert [node["process_id"] for node in planar["process_graph"].values()].count(
        "mask_polygon"
    ) == 2

    with pytest.raises(UnsupportedEEError, match="repeated clips"):
        compile_sdk(ee, image.clip(first).clip(_default_polygon()))


@pytest.mark.parametrize("geometry", [
    {**_default_polygon(), "geodesic": True, "evenOdd": False},
    {**_default_polygon(), "geodesic": True, "crs": "EPSG:3857"},
    {"type": "Point", "coordinates": [100.2, 30.3]},
])
def test_geodesic_clip_rejects_unproven_geometry_models(ee, geometry):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    with pytest.raises(UnsupportedEEError):
        compile_sdk(ee, image.clip(geometry))


def test_fractional_mask_and_clip_composition_stays_explicitly_unsupported(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    weighted = image.updateMask(ee.Image.constant(0.5))
    with pytest.raises(UnsupportedEEError, match="fractional mask carrier"):
        compile_sdk(ee, weighted.clip(_default_polygon()))


def test_default_sample_requires_zero_preserving_support_for_exact_clip_identity(ee):
    source = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    clipped = source.clip(_default_polygon())

    # A normal weighted update and scalar/unary math retain the original exact
    # clip weight as an operand of mask_update.
    compile_sdk(ee, clipped.updateMask(ee.Image.constant(0.5)).sample(scale=10))
    compile_sdk(ee, clipped.sqrt().sample(scale=10))
    compile_sdk(ee, clipped.multiply(2).sample(scale=10))
    compile_sdk(ee, clipped.select(["nir"], ["renamed"]).sample(scale=10))

    with pytest.raises(UnsupportedEEError, match="exact clip ROI"):
        compile_sdk(ee, clipped.mask(ee.Image.constant(0.5)).sample(scale=10))
    compile_sdk(
        ee, clipped.mask(ee.Image.constant(0.5)).sample(
            region=_default_polygon(), scale=10,
        ),
    )
    with pytest.raises(UnsupportedEEError, match="exact clip ROI"):
        compile_sdk(
            ee, clipped.mask(ee.Image.constant(0.5)).multiply(2).sample(scale=10),
        )
    with pytest.raises(UnsupportedEEError, match="exact clip ROI"):
        compile_sdk(
            ee, clipped.mask().updateMask(ee.Image.constant(0.5)).sample(scale=10),
        )

    # A setter can be followed by a new mask from the matching source clip;
    # this restores an exact zero-support operand through mask_update.
    compile_sdk(
        ee, clipped.mask(ee.Image.constant(0.5))
        .updateMask(clipped.mask()).sample(scale=10),
    )


def test_default_sample_requires_the_first_image_clip_identity(ee):
    source = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    roi_a = _default_polygon()
    roi_b = {
        "type": "Polygon",
        "coordinates": [[
            [101.1, 30.1], [101.9, 30.1], [101.9, 30.9],
            [101.1, 30.9], [101.1, 30.1],
        ]],
    }
    clipped_a = source.clip(roi_a)
    clipped_b = source.clip(roi_b)

    with pytest.raises(UnsupportedEEError, match="exact clip ROI"):
        compile_sdk(ee, clipped_a.addBands(clipped_b, overwrite=True).sample(scale=10))
    with pytest.raises(UnsupportedEEError, match="exact clip ROI"):
        compile_sdk(ee, clipped_a.select([]).addBands(clipped_b).sample(scale=10))

    # A names=[] addBands is a no-op and keeps the first image's exact identity.
    compile_sdk(
        ee, clipped_a.addBands(clipped_b, names=[]).sample(scale=10),
    )

    # A truly source-free empty destination adopts the donor's exact footprint
    # and identity together.
    donor = ee.Image().select([]).addBands(clipped_b)
    compile_sdk(ee, donor.sample(scale=10))
