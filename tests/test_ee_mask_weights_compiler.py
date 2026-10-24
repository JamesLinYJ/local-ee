"""Offline compiler acceptance for independent fractional mask weights."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.ir import Image, Pixel, Source, UnsupportedEEError, const
from gee.compat.earthengine.image_mask_weights import invoke_mask_weights
from gee.compat.earthengine.mask_weights_graph import _require_observation_keys
from gee.compat.earthengine.pixel_math_graph import _PixelFactsWalker
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-mask-weights-wave64-v1.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture(scope="module")
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def local_catalog(*, misalign_scene_b=False):
    metadata, default_items, _ = synthetic_inputs()
    items = deepcopy(default_items)
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32649"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3000000]
    if misalign_scene_b:
        items["sentinel-2-l2a"][1]["properties"]["proj:transform"][2] += 5
    return metadata, items


def compile_fixture(name, *, misalign_scene_b=False):
    metadata, items = local_catalog(misalign_scene_b=misalign_scene_b)
    return compile_expression(FIXTURE["sdk_expressions"][name], [metadata], items)


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_sdk(ee, value, *, misalign_scene_b=False):
    metadata, items = local_catalog(misalign_scene_b=misalign_scene_b)
    return compile_expression(encode(ee, value), [metadata], items)


def mask_weight_operations(result):
    return [
        json.loads(node["arguments"]["spec"])["op"]
        for node in result["process_graph"].values()
        if node["process_id"] == "local_ee_mask_weights"
    ]


def test_fractional_mask_getter_compiles_numeric_weight_bands_without_multiplying_values():
    result = compile_fixture("maskGetter")

    assert result["kind"] == "image"
    assert result["bands"] == ["red", "nir"]
    assert result["has_time_dimension"] is False
    operations = mask_weight_operations(result)
    assert operations.count("validity") == 2
    assert operations.count("update") == 2
    assert "apply" not in operations
    process_ids = [node["process_id"] for node in result["process_graph"].values()]
    assert "multiply" not in process_ids
    assert "local_ee_mask_weights" in process_ids
    assert process_ids.index("local_ee_to_double") < process_ids.index("local_ee_mask_weights")


def test_default_mask_getter_and_repeated_fractional_updates_keep_the_ordered_weight_ir():
    omitted = compile_fixture("maskGetter")
    explicit_null = compile_fixture("maskGetterNullDefault")
    assert omitted["process_graph"] == explicit_null["process_graph"]
    assert omitted["bands"] == explicit_null["bands"]

    stacked = compile_fixture("stackedMaskGetter")
    operations = mask_weight_operations(stacked)
    assert stacked["bands"] == ["red", "nir"]
    assert operations.count("validity") == 2
    assert operations.count("update") == 4
    assert "apply" not in operations


def test_a_mask_with_its_own_fractional_mask_is_applied_before_replacement():
    result = compile_fixture("weightedMaskInput")

    assert result["bands"] == ["red"]
    operations = mask_weight_operations(result)
    assert operations.count("validity") == 2
    assert operations.count("update") == 2
    assert operations.count("apply") == 1
    assert "multiply" not in [node["process_id"] for node in result["process_graph"].values()]


def test_fractional_update_rejects_out_of_range_literals_and_unsupported_band_counts(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select(["red", "nir"])
    for invalid_weight in (-0.0001, 1.0001):
        with pytest.raises(UnsupportedEEError, match=r"finite mask values in\[0,1\]"):
            compile_sdk(ee, image.updateMask(ee.Image.constant(invalid_weight)).mask())

    three_bands = ee.Image.constant([0.25, 0.5, 0.75])
    with pytest.raises(UnsupportedEEError, match="one broadcast mask band or the same number"):
        compile_sdk(ee, image.updateMask(three_bands).mask())


def test_mask_getter_update_by_band_order_retains_the_source_names():
    result = compile_fixture("maskGetterByOrder")

    assert result["bands"] == ["red", "nir"]
    assert mask_weight_operations(result).count("update") == 2


@pytest.mark.parametrize(
    "name,expected_bands",
    [("selectMaskGetter", ["nir"]), ("renameMaskGetter", ["R", "N"]),
     ("addBandsMaskGetter", ["blue", "R", "N"])],
)
def test_select_rename_and_addbands_transport_weighted_bands(name, expected_bands):
    result = compile_fixture(name)

    assert result["bands"] == expected_bands
    assert "update" in mask_weight_operations(result)


def test_mapped_getter_and_per_image_mean_or_tobands_keep_each_real_item_lineage():
    mapped = compile_fixture("weightedMapMaskGetter")
    assert mapped["kind"] == "collection"
    assert mapped["has_time_dimension"] is True
    assert mapped["source_item_ids"] == ["scene-a", "scene-b", "scene-c"]
    assert [feature["id"] for feature in mapped["features"]] == [
        "scene-a", "scene-b", "scene-c",
    ]
    assert all([band["id"] for band in feature["bands"]] == ["nir"]
               for feature in mapped["features"])

    for name, expected_bands in (
        ("mappedMaskGetterMean", ["nir"]),
        ("mappedMaskGetterToBands", ["scene-a_nir", "scene-b_nir", "scene-c_nir"]),
    ):
        result = compile_fixture(name)
        assert result["kind"] == "image"
        assert result["bands"] == expected_bands
        assert result["source_item_ids"] == ["scene-a", "scene-b", "scene-c"]
        graph_sources = [
            node["arguments"]["_gee_item_ids"]
            for node in result["process_graph"].values()
            if node["process_id"] == "load_collection"
        ]
        assert graph_sources == [["scene-a"], ["scene-b"], ["scene-c"]]
        assert mask_weight_operations(result).count("update") == 3


def test_binary_update_mask_keeps_the_existing_boolean_path():
    result = compile_fixture("binaryUpdateCompatibility")

    assert result["bands"] == ["nir"]
    assert "local_ee_mask_weights" not in [
        node["process_id"] for node in result["process_graph"].values()
    ]


@pytest.mark.parametrize(
    "name",
    ["weightedArithmetic", "weightedUnmask", "weightedCollectionMean"],
)
def test_unhandled_weighted_value_consumers_fail_instead_of_claiming_mask_semantics(name):
    with pytest.raises(UnsupportedEEError, match="Fractional image masks require a mask-aware consumer"):
        compile_fixture(name)


def test_distinct_spatial_first_images_may_have_different_dates_when_their_grids_align(ee):
    collection = ee.ImageCollection("sentinel-2-l2a")
    first = collection.filter(ee.Filter.eq(name="system:index", value="scene-a"))
    second = collection.filter(ee.Filter.eq(name="system:index", value="scene-b"))
    image = first.first().select("red")
    mask = second.first().select("SCL").multiply(0.01)

    result = compile_sdk(ee, image.updateMask(mask).mask())
    assert result["bands"] == ["red"]
    assert result["has_time_dimension"] is False
    assert "update" in mask_weight_operations(result)

    with pytest.raises(UnsupportedEEError, match="common pixel grid"):
        compile_sdk(ee, image.updateMask(mask).mask(), misalign_scene_b=True)


def test_timed_mask_operands_compare_actual_catalog_observation_keys():
    metadata, items = local_catalog()
    translator = Translator([metadata], items, None)
    pixels = [
        Pixel("band", (Source("sentinel-2-l2a", ("scene-a", "scene-b"), ("red",)), "red")),
        Pixel("band", (Source("sentinel-2-l2a", ("scene-b", "scene-c"), ("SCL",)), "SCL")),
    ]
    facts = _PixelFactsWalker(translator)

    with pytest.raises(UnsupportedEEError, match="matching actual observation time keys"):
        _require_observation_keys(Graph(translator), pixels, facts)


def test_band_precharge_rejects_work_over_the_shared_compiler_budget_before_expansion():
    translator = Translator([], {}, None)
    translator.steps = 49_500
    image = Image(
        [(f"b{index}", const(1.0)) for index in range(42)], {},
    )
    mask = Image([("mask", const(0.5))], {})

    with pytest.raises(UnsupportedEEError, match="shared50000-step compilation work budget"):
        invoke_mask_weights(translator, "Image.updateMask", {"image": image, "mask": mask})
    assert translator.steps == 49_500
