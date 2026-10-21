"""Official SDK local joins, source identity and independent pixel controls."""
import json
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import Translator, UnsupportedEEError, compile_expression
from gee.compat.earthengine.ir import Filter, Image, ImageSequence, Pixel
from gee.compat.earthengine.join_ops import invoke_join
from gee.compat.earthengine.public_values import public_value
from test_ee_translate import evaluate_graph


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=Path(__file__).resolve().parents[1] / "vendor/earthengine-js/algorithms.json",
    )


@pytest.fixture
def local():
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": ["red", "nir"]}}}]
    rows = [
        ("p-a", "primary", "alpha", 9), ("p-b", "primary", "beta", 5),
        ("p-none", "primary", "gamma", 1), ("p-null", "primary", None, 1),
        ("s-a2", "secondary", "alpha", 2), ("s-a1", "secondary", "alpha", 1),
        ("s-b", "secondary", "beta", 1), ("s-a-tie", "secondary", "alpha", 1),
        ("s-null", "secondary", None, 1),
    ]
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
    items = {"sentinel-2-l2a": [{
        "id": iid, "bbox": [0, 0, 2, 2], "geometry": geometry,
        "properties": {"system:index": iid, "system:time_start": 1000, "side": side, "group": group, "rank": rank},
    } for iid, side, group, rank in rows]}
    return catalog, items


def _collections(ee):
    collection = ee.ImageCollection("sentinel-2-l2a")
    return collection.filter(ee.Filter.eq("side", "primary")), collection.filter(ee.Filter.eq("side", "secondary"))


def _join(ee, join, condition=None):
    primary, secondary = _collections(ee)
    if condition is None:
        condition = ee.Filter.equals(leftField="group", rightField="group")
    return ee.ImageCollection(join.apply(primary, secondary, condition))


def _compile(ee, value, local):
    return compile_expression(ee.serializer.encode(value, for_cloud_api=False), *local)


@pytest.mark.parametrize("operation,expected", [
    ("simple", ["p-a", "p-b"]), ("inverted", ["p-none", "p-null"]),
])
def test_sdk_simple_inverted_preserve_primary_order_and_metadata(ee, local, operation, expected):
    result = _compile(ee, _join(ee, getattr(ee.Join, operation)()), local)
    assert result["source_item_ids"] == expected
    assert [row["properties"]["system:index"] for row in result["features"]] == expected
    assert all("match" not in row["properties"] for row in result["features"])
    assert result["bands"] == ["red", "nir"]


@pytest.mark.parametrize("ordering,ascending,expected", [
    (None, True, "s-a2"), ("rank", True, "s-a1"), ("rank", False, "s-a2"),
])
def test_save_first_ordering_and_stable_ties(ee, local, ordering, ascending, expected):
    joined = _join(ee, ee.Join.saveFirst("match", ordering=ordering, ascending=ascending))
    result = _compile(ee, joined, local)
    assert result["source_item_ids"] == ["p-a", "p-b"]
    match = result["features"][0]["properties"]["match"]
    assert match["type"] == "Image" and match["id"] == expected
    assert match["bands"] == [{"id": "red"}, {"id": "nir"}]
    json.dumps(result, allow_nan=False)
    # The match remains a real source image, accessible to subsequent SDK calls.
    matched_id = ee.Image(ee.Image(joined.first()).get("match")).get("system:index")
    assert _compile(ee, matched_id, local)["value"] == expected


def test_save_all_retains_all_observations_and_composes_with_list_map(ee, local):
    joined = _join(ee, ee.Join.saveAll("matches", ordering="rank"))
    first = ee.Image(joined.first())
    ids = ee.List(first.get("matches")).map(lambda image: ee.Image(image).get("system:index"))
    assert _compile(ee, ids, local)["value"] == ["s-a1", "s-a-tie", "s-a2"]
    result = _compile(ee, joined, local)
    assert [image["id"] for image in result["features"][0]["properties"]["matches"]] == ["s-a1", "s-a-tie", "s-a2"]


@pytest.mark.parametrize("multi", [False, True])
def test_join_map_set_preserves_typed_match_for_later_image_access(ee, local, multi):
    joined = _join(ee, ee.Join.saveFirst("match", ordering="rank"))
    if multi:
        annotated = joined.map(lambda image: image.set({"reviewed": True, "rank_plus": ee.Number(image.get("rank")).add(1)}))
    else:
        annotated = joined.map(lambda image: image.set("reviewed", True))
    result = _compile(ee, annotated, local)
    assert all(feature["properties"]["reviewed"] is True for feature in result["features"])
    assert result["features"][0]["properties"]["match"]["id"] == "s-a1"
    if multi:
        assert result["features"][0]["properties"]["rank_plus"] == 10
    matched_id = ee.Image(ee.Image(annotated.first()).get("match")).get("system:index")
    assert _compile(ee, matched_id, local)["value"] == "s-a1"
    json.dumps(result, allow_nan=False)


def test_nested_join_matches_have_a_json_safe_bounded_description(ee, local):
    joined = _join(ee, ee.Join.saveFirst("match", ordering="rank"))
    twice = ee.Join.saveFirst("repeat").apply(
        joined, joined, ee.Filter.equals(leftField="system:index", rightField="system:index")
    )
    result = _compile(ee, twice, local)
    nested = result["features"][0]["properties"]["repeat"]["properties"]["match"]
    assert nested["id"] == "s-a1"
    assert "Pixel" not in json.dumps(result, allow_nan=False)


def test_save_all_cannot_bypass_whole_response_metadata_budget(ee, local):
    source = local[1]["sentinel-2-l2a"][0]
    local[1]["sentinel-2-l2a"] = [{
        **source, "id": f"{side}-{index}",
        "properties": {"system:index": f"{side}-{index}", "side": side, "group": "same"},
    } for side in ("primary", "secondary") for index in range(100)]
    joined = _join(ee, ee.Join.saveAll("matches"))
    # 10,000 equality checks are below the 50,000-step compiler limit, but
    # duplicating every match into every public row must obey one output cap.
    with pytest.raises(UnsupportedEEError, match="materialization limits|1 MB"):
        _compile(ee, joined, local)


@pytest.mark.parametrize("operation,key", [("saveFirst", "match"), ("saveAll", "matches")])
def test_outer_unmatched_rows_are_preserved_without_fabricated_match(ee, local, operation, key):
    joined = _join(ee, getattr(ee.Join, operation)(key, outer=True))
    result = _compile(ee, joined, local)
    assert result["source_item_ids"] == ["p-a", "p-b", "p-none", "p-null"]
    for row in result["features"][2:]:
        assert key not in row["properties"]
    # Missing metadata and explicitly null metadata do not become equality keys.
    del local[1]["sentinel-2-l2a"][3]["properties"]["group"]
    assert _compile(ee, joined, local)["source_item_ids"] == result["source_item_ids"]


def test_compound_join_filter_binds_left_and_right_to_distinct_images(ee, local):
    condition = ee.Filter.And(
        ee.Filter.equals(leftField="group", rightField="group"),
        ee.Filter.greaterThan(leftField="rank", rightField="rank"),
        ee.Filter.Not(ee.Filter.equals(leftField="rank", rightValue=5)),
    )
    joined = _join(ee, ee.Join.simple(), condition)
    assert _compile(ee, joined, local)["source_item_ids"] == ["p-a"]


def test_empty_collections_and_bare_join_do_not_materialize_a_fake_image(ee, local):
    primary, secondary = _collections(ee)
    equality = ee.Filter.equals(leftField="group", rightField="group")
    for left, right in ((primary.limit(0), secondary), (primary, secondary.limit(0))):
        result = _compile(ee, ee.Join.simple().apply(left, right, equality), local)
        assert result["source_item_ids"] == [] and result["features"] == []
    with pytest.raises(UnsupportedEEError, match="not a computable output"):
        _compile(ee, ee.Join.simple(), local)


def test_joined_image_bands_compile_to_the_correct_independent_sources(ee, local):
    joined = _join(ee, ee.Join.saveFirst("match", ordering="rank"))
    pair = ee.Image(joined.first())
    combined = pair.select("red").addBands(ee.Image(pair.get("match")).select("nir").rename("matched_nir"))
    result = _compile(ee, combined, local)
    arrays = {
        "p-a": {"red": np.array([1.0, 3.0]), "nir": np.array([9.0, 11.0])},
        "s-a1": {"red": np.array([100.0, 300.0]), "nir": np.array([7.0, np.nan])},
    }
    values, names, timed = evaluate_graph(result, arrays)
    assert names == ["red", "matched_nir"] and timed is False
    np.testing.assert_equal(values, [[1.0, 3.0], [7.0, np.nan]])
    assert result["source_item_ids"] == ["p-a", "s-a1"]


@pytest.mark.parametrize("join,reason", [
    (lambda ee: ee.Join.saveFirst("match", measureKey="distance"), "measures"),
    (lambda ee: ee.Join.saveAll("matches", ordering="nested.rank"), "flat"),
])
def test_unimplemented_join_options_fail_explicitly(ee, local, join, reason):
    with pytest.raises(UnsupportedEEError, match=reason):
        _compile(ee, _join(ee, join(ee)), local)


def test_ordering_missing_property_and_unsupported_condition_are_not_ignored(ee, local):
    joined = _join(ee, ee.Join.saveFirst("match", ordering="absent"))
    with pytest.raises(UnsupportedEEError, match="ordering property"):
        _compile(ee, joined, local)
    spatial = _join(ee, ee.Join.simple(), ee.Filter.intersects(leftField=".geo", rightField=".geo"))
    with pytest.raises(UnsupportedEEError, match="Unsupported local join condition"):
        _compile(ee, spatial, local)


def test_pair_budget_applies_to_catalogue_work_outside_serialized_dag():
    translator = Translator([], {}, None)
    image = Image([("red", Pixel("constant", (1,)))], {"key": "primary"})
    other = Image([("red", Pixel("constant", (2,)))], {"key": "secondary"})
    join = invoke_join(translator, "Join.simple", {})
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        invoke_join(translator, "Join.apply", {
            "join": join, "primary": ImageSequence([image] * 300),
            "secondary": ImageSequence([other] * 300),
            "condition": Filter("equals", {"leftField": "key", "rightField": "key"}),
        })


def test_frames_and_constructor_arguments_are_bounded():
    translator = Translator([], {}, None)
    for args in ({"matchKey": "match", "outer": "true"}, {"matchKey": "match", "ignored": 1}):
        with pytest.raises(UnsupportedEEError):
            invoke_join(translator, "Join.saveFirst", args)
    image = Image([], {"key": 1})
    with pytest.raises(UnsupportedEEError, match="1000 images"):
        invoke_join(translator, "Join.apply", {
            "join": invoke_join(translator, "Join.simple", {}),
            "primary": ImageSequence([image] * 1001), "secondary": ImageSequence([]),
            "condition": Filter("equals", {"leftField": "key", "rightField": "key"}),
        })


def test_public_join_description_never_exposes_pixel_ir():
    image = Image([("red", Pixel("constant", (3,)))], {"system:index": "scene"})
    public = public_value({"matched": image})
    assert public["matched"]["id"] == "scene"
    assert "Pixel" not in json.dumps(public)
