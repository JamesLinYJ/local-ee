"""Pending clip footprints survive every public Image-producing root adapter."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import pytest

from gee.compat.earthengine.ir import UnsupportedEEError
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
LOCAL_URL = "http://127.0.0.1:8787/openeo/1.2"
LOCAL_TOKEN = "a" * 48


@pytest.fixture(scope="module")
def local_ee():
    metadata, default_items, _ = synthetic_inputs()
    items = deepcopy(default_items)
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32649"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3000000]

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            LOCAL_URL, LOCAL_TOKEN,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        yield ee, metadata, items
    assert guard.evidence()["attempt_count"] == 0


def _polygon(west):
    return {
        "type": "Polygon",
        "coordinates": [[
            [west, 30.1], [west + 0.3, 30.1], [west + 0.3, 30.9],
            [west, 30.9], [west, 30.1],
        ]],
    }


def _wire(ee, value):
    return ee.serializer.encode(value, is_compound=True, for_cloud_api=False)


def _compile(ee, value, metadata, items):
    return compile_expression(_wire(ee, value), [metadata], items)


@contextmanager
def _local_getinfo_compiler(ee, metadata, items):
    """Exercise the official SDK getInfo method at the local compile boundary."""
    original = ee.data.computeValue
    requests = []

    def compute_value(value):
        compiled = compile_expression(
            _wire(ee, value), [metadata], items, for_image_metadata=True,
        )
        requests.append(compiled)
        if compiled["kind"] == "value":
            return compiled["value"]
        if compiled["kind"] in {"image", "collection"}:
            return {
                "type": "ImageCollection" if compiled["kind"] == "collection" else "Image",
                "bands": [{"id": name} for name in compiled["bands"]],
                "properties": compiled.get("properties", {}),
            }
        raise AssertionError(f"Unexpected getInfo compile kind: {compiled['kind']}")

    ee.data.computeValue = compute_value
    try:
        yield requests
    finally:
        ee.data.computeValue = original


def _base(ee):
    return ee.ImageCollection("sentinel-2-l2a").first().select("nir")


def test_expression_ternary_keeps_pending_roi_through_sdk_getinfo_and_sample(local_ee):
    ee, metadata, items = local_ee
    source = _base(ee)
    clipped = source.clip(_polygon(100.1))
    result = clipped.expression("1 ? image : image", {"image": clipped})

    with _local_getinfo_compiler(ee, metadata, items) as requests:
        with pytest.raises(UnsupportedEEError, match="conservative source envelope"):
            result.geometry().getInfo()
        assert requests == []

        # Unclipped expressions keep the ordinary source geometry API.
        plain = source.expression("1 ? image : image", {"image": source})
        geometry = plain.geometry().getInfo()
        assert geometry["type"] == "Polygon"
        assert geometry["geodesic"] is False
        assert len(requests) == 1
    assert _compile(ee, plain.sample(), metadata, items)["kind"] == "sample_table"

    with pytest.raises(UnsupportedEEError, match="pending geodesic clip"):
        _compile(ee, result.sample(), metadata, items)


def test_expression_ternary_with_disjoint_clip_identities_stays_ambiguous(local_ee):
    ee, metadata, items = local_ee
    source = _base(ee)
    left = source.clip(_polygon(100.1))
    right = source.clip(_polygon(100.6))
    result = source.expression("1 ? left : right", {"left": left, "right": right})

    with _local_getinfo_compiler(ee, metadata, items):
        with pytest.raises(UnsupportedEEError, match="conservative source envelope"):
            result.geometry().getInfo()
    with pytest.raises(UnsupportedEEError, match="pending geodesic clip"):
        _compile(ee, result.sample(), metadata, items)


def test_collection_geometry_and_fresh_sequence_images_keep_pending_identity(local_ee):
    ee, metadata, items = local_ee
    clipped = _base(ee).clip(_polygon(100.1))
    collection = ee.ImageCollection.fromImages([clipped])
    derived = [
        collection.toBands(),
        collection.median(),
        collection.qualityMosaic("nir"),
    ]

    with _local_getinfo_compiler(ee, metadata, items):
        with pytest.raises(UnsupportedEEError, match="conservative source envelope"):
            collection.geometry().getInfo()
        for image in derived:
            with pytest.raises(UnsupportedEEError, match="conservative source envelope"):
                image.geometry().getInfo()

    # toBands retains the exact one-band clip weight, while the arithmetic
    # reducers and mosaic remain conservative and require an explicit region.
    assert _compile(ee, derived[0].sample(), metadata, items)["kind"] == "sample_table"
    for image in derived[1:]:
        with pytest.raises(UnsupportedEEError, match="pending geodesic clip"):
            _compile(ee, image.sample(), metadata, items)


def test_unmask_union_tracks_pending_replacement_footprint(local_ee):
    ee, metadata, items = local_ee
    source = _base(ee)
    replacement = source.clip(_polygon(100.6))
    union = source.unmask(replacement, sameFootprint=False)

    with _local_getinfo_compiler(ee, metadata, items):
        with pytest.raises(UnsupportedEEError, match="conservative source envelope"):
            union.geometry().getInfo()
    with pytest.raises(UnsupportedEEError, match="pending geodesic clip"):
        _compile(ee, union.sample(), metadata, items)

    same_footprint = source.clip(_polygon(100.1)).unmask(
        replacement, sameFootprint=True,
    )
    with _local_getinfo_compiler(ee, metadata, items):
        with pytest.raises(UnsupportedEEError, match="conservative source envelope"):
            same_footprint.geometry().getInfo()


def test_collection_filters_do_not_read_a_pending_clip_as_exact_geometry(local_ee):
    ee, metadata, items = local_ee
    source = ee.ImageCollection("sentinel-2-l2a")
    roi = _polygon(100.1)
    mapped = source.map(lambda image: image.clip(roi))

    # Geometry predicates cannot use the source-row envelope once map() has
    # introduced an unresolved exact clip footprint. This check must happen
    # before the translator scans catalogue items.
    spatial = mapped.filterBounds(roi)
    with pytest.raises(UnsupportedEEError, match="conservative source envelope"):
        _compile(ee, spatial.size(), metadata, items)

    has_geometry = mapped.filter(ee.Filter.hasGeometry())
    with pytest.raises(UnsupportedEEError, match="conservative source envelope"):
        _compile(ee, has_geometry.size(), metadata, items)

    # Metadata-only filtering remains independent of the unresolved footprint.
    metadata_only = mapped.filter(ee.Filter.eq("system:index", "missing-item"))
    assert _compile(ee, metadata_only.size(), metadata, items)["kind"] == "value"

    # The explicitly constructed ImageSequence route uses the same geometry
    # guard, including the hasGeometry predicate.
    explicit = ee.ImageCollection.fromImages([_base(ee).clip(roi)])
    explicit_filtered = explicit.filter(ee.Filter.hasGeometry())
    with pytest.raises(UnsupportedEEError, match="conservative source envelope"):
        _compile(ee, explicit_filtered.size(), metadata, items)
