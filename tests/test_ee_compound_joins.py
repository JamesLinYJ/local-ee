"""Measured conjunctions for preceding/following joins using the pinned SDK."""
import json
from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import Translator, UnsupportedEEError, compile_expression
from gee.compat.earthengine.ir import Filter, Image, ImageSequence
from gee.compat.earthengine.join_conditions import validate_condition
from gee.compat.earthengine.join_ops import invoke_join


BASE = 1_700_000_000_000
LIMIT = 200


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=Path(__file__).resolve().parents[1] / "vendor/earthengine-js/algorithms.json",
    )


@pytest.fixture
def local():
    rows = [
        ("p-a", "primary", BASE, "g", 2),
        ("p-missing", "primary", "missing", "g", 2),
        ("p-null", "primary", None, "g", 2),
        ("s-prior-far", "secondary", BASE - 300, "g", 0),
        ("s-prior-first", "secondary", BASE - 100, "g", 0),
        ("s-prior-tie", "secondary", BASE - 100, "g", 0),
        ("s-prior-boundary", "secondary", BASE - LIMIT, "g", 0),
        ("s-prior-outside", "secondary", BASE - LIMIT - 1, "g", 0),
        ("s-follow-first", "secondary", BASE + 100, "g", 0),
        ("s-follow-tie", "secondary", BASE + 100, "g", 0),
        ("s-follow-boundary", "secondary", BASE + LIMIT, "g", 0),
        ("s-follow-outside", "secondary", BASE + LIMIT + 1, "g", 0),
        ("s-wrong-group", "secondary", BASE + 1, "other", 0),
    ]
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
    items = []
    for iid, side, timestamp, group, quality in rows:
        properties = {
            "system:index": iid, "side": side, "group": group, "quality": quality,
        }
        if timestamp != "missing":
            properties["system:time_start"] = timestamp
        items.append({"id": iid, "bbox": [0, 0, 2, 2], "geometry": geometry, "properties": properties})
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": ["red", "nir"]}}}]
    return catalog, {"sentinel-2-l2a": items}


def _collections(ee):
    source = ee.ImageCollection("sentinel-2-l2a")
    return source.filter(ee.Filter.eq("side", "primary")), source.filter(ee.Filter.eq("side", "secondary"))


def _condition(ee, direction):
    temporal_order = ee.Filter.greaterThan if direction == "preceding" else ee.Filter.lessThan
    # The pinned gte alias uses primary quality as its left field and becomes a
    # Not around a scalar comparison in the serialized DAG.
    return ee.Filter.And(
        ee.Filter.maxDifference(
            difference=LIMIT,
            leftField="system:time_start",
            rightField="system:time_start",
        ),
        temporal_order(leftField="system:time_start", rightField="system:time_start"),
        ee.Filter.equals(leftField="group", rightField="group"),
        ee.Filter.gte("quality", 1),
    )


def _compile(ee, value, local):
    encoded = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(encoded, *local)


def _reference(primary_time, primary_quality, secondary_rows, direction, threshold):
    """Independent scalar reference with stable source-order tie selection."""
    candidates = []
    for index, (item_id, timestamp, group) in enumerate(secondary_rows):
        ordered = timestamp < primary_time if direction == "preceding" else timestamp > primary_time
        distance = abs(primary_time - timestamp)
        if ordered and distance <= threshold and group == "g" and primary_quality >= 1:
            candidates.append((distance, index, item_id))
    if not candidates:
        return None
    distance, _, item_id = min(candidates)
    return item_id, distance


@pytest.mark.parametrize("direction", ["preceding", "following"])
def test_compound_save_best_matches_independent_directional_reference(ee, local, direction):
    primary, secondary = _collections(ee)
    joined = ee.ImageCollection(ee.Join.saveBest("match", "delta").apply(
        primary, secondary, _condition(ee, direction),
    ))
    encoded = ee.serializer.encode(joined, for_cloud_api=False)
    serialized = json.dumps(encoded)
    assert "Filter.maxDifference" in serialized
    assert "Filter.not" in serialized
    decoded = json.loads(serialized)
    assert decoded["type"] == "CompoundValue"
    result = compile_expression(encoded, *local)

    secondary_rows = [
        ("s-prior-far", BASE - 300, "g"),
        ("s-prior-first", BASE - 100, "g"),
        ("s-prior-tie", BASE - 100, "g"),
        ("s-prior-boundary", BASE - LIMIT, "g"),
        ("s-prior-outside", BASE - LIMIT - 1, "g"),
        ("s-follow-first", BASE + 100, "g"),
        ("s-follow-tie", BASE + 100, "g"),
        ("s-follow-boundary", BASE + LIMIT, "g"),
        ("s-follow-outside", BASE + LIMIT + 1, "g"),
        ("s-wrong-group", BASE + 1, "other"),
    ]
    expected = _reference(BASE, 2, secondary_rows, direction, LIMIT)
    assert expected == (
        ("s-prior-first", 100) if direction == "preceding" else ("s-follow-first", 100)
    )
    assert result["source_item_ids"] == ["p-a"]
    matched = result["features"][0]["properties"]["match"]
    assert (matched["id"], matched["properties"]["delta"]) == expected

    primary_item = next(item for item in local[1]["sentinel-2-l2a"] if item["id"] == "p-a")
    primary_item["properties"]["quality"] = 0
    assert compile_expression(encoded, *local)["source_item_ids"] == []


@pytest.mark.parametrize(("direction", "expected_ids"), [
    ("preceding", ["s-prior-first", "s-prior-tie", "s-prior-boundary"]),
    ("following", ["s-follow-first", "s-follow-tie", "s-follow-boundary"]),
])
def test_compound_save_all_keeps_ties_and_inclusive_threshold(ee, local, direction, expected_ids):
    primary, secondary = _collections(ee)
    joined = ee.ImageCollection(ee.Join.saveAll("matches", measureKey="delta").apply(
        primary, secondary, _condition(ee, direction),
    ))
    result = _compile(ee, joined, local)
    actual = [
        (row["id"], row["properties"]["delta"])
        for row in result["features"][0]["properties"]["matches"]
    ]
    assert actual == [
        (item_id, 200 if item_id.endswith("boundary") else 100)
        for item_id in expected_ids
    ]


def test_compound_save_first_attaches_measure_to_the_selected_match(ee, local):
    primary, secondary = _collections(ee)
    joined = ee.ImageCollection(ee.Join.saveFirst("match", measureKey="delta").apply(
        primary, secondary, _condition(ee, "preceding"),
    ))
    result = _compile(ee, joined, local)
    matched = result["features"][0]["properties"]["match"]
    assert matched["id"] == "s-prior-first"
    assert matched["properties"]["delta"] == 100


def test_compound_outer_keeps_missing_and_null_time_rows_without_matches(ee, local):
    primary, secondary = _collections(ee)
    joined = ee.ImageCollection(ee.Join.saveFirst("match", outer=True).apply(
        primary, secondary, _condition(ee, "preceding"),
    ))
    result = _compile(ee, joined, local)
    assert result["source_item_ids"] == ["p-a", "p-missing", "p-null"]
    for feature in result["features"][1:]:
        assert "match" not in feature["properties"]


@pytest.mark.parametrize(("condition_kind", "expected_ids"), [
    ("or", [
        "s-prior-first", "s-prior-tie", "s-follow-first", "s-follow-tie", "s-wrong-group",
    ]),
    ("not", [
        "s-prior-far", "s-prior-boundary", "s-prior-outside",
        "s-follow-boundary", "s-follow-outside",
    ]),
])
def test_unmeasured_boolean_or_not_keep_max_difference_predicate_semantics(
    ee, local, condition_kind, expected_ids,
):
    primary, secondary = _collections(ee)
    numeric = ee.Filter.maxDifference(
        difference=100,
        leftField="system:time_start",
        rightField="system:time_start",
    )
    if condition_kind == "or":
        condition = ee.Filter.Or(
            numeric,
            ee.Filter.equals(leftField="side", rightValue="never"),
        )
    else:
        condition = ee.Filter.Not(numeric)
    joined = ee.ImageCollection(ee.Join.saveAll("matches").apply(primary, secondary, condition))
    result = _compile(ee, joined, local)
    actual = [row["id"] for row in result["features"][0]["properties"]["matches"]]
    assert actual == expected_ids


@pytest.mark.parametrize("condition", [
    lambda ee: ee.Filter.Or(
        ee.Filter.maxDifference(LIMIT, leftField="system:time_start", rightField="system:time_start"),
        ee.Filter.equals(leftField="group", rightField="group"),
    ),
    lambda ee: ee.Filter.Not(ee.Filter.maxDifference(
        LIMIT, leftField="system:time_start", rightField="system:time_start",
    )),
    lambda ee: ee.Filter.And(
        ee.Filter.maxDifference(LIMIT, leftField="system:time_start", rightField="system:time_start"),
        ee.Filter.maxDifference(LIMIT, leftField="system:time_start", rightValue=BASE),
    ),
])
def test_ambiguous_measured_logical_shapes_fail_explicitly(ee, local, condition):
    primary, secondary = _collections(ee)
    joined = ee.Join.saveBest("match", "delta").apply(primary, secondary, condition(ee))
    with pytest.raises(UnsupportedEEError, match="cannot contain a measured|maxDifference measures"):
        _compile(ee, joined, local)


def test_condition_unknown_arguments_and_child_counts_fail_before_collection_work():
    translator = Translator([], {}, None)
    join = invoke_join(translator, "Join.saveAll", {"matchesKey": "matches"})
    empty = ImageSequence([])
    unknown = Filter("equals", {
        "leftField": "group", "rightValue": "g", "ignored": True,
    })
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_join(translator, "Join.apply", {
            "join": join, "primary": empty, "secondary": empty, "condition": unknown,
        })

    oversized = Filter("and", {"filters": [
        Filter("equals", {"leftField": "group", "rightValue": "g"})
        for _ in range(1001)
    ]})
    with pytest.raises(UnsupportedEEError, match="at most 1000 child filters"):
        validate_condition(Translator([], {}, None), oversized)


def test_validation_and_pair_evaluation_keep_the_shared_work_budget():
    numeric = Filter("maxDifference", {
        "difference": LIMIT, "leftField": "time", "rightField": "time",
    })
    scalar = Filter("equals", {"leftField": "group", "rightField": "group"})
    condition = Filter("and", {"filters": [numeric, scalar]})

    translator = Translator([], {}, None)
    translator.steps = 49998
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        validate_condition(translator, condition)

    translator = Translator([], {}, None)
    join = invoke_join(translator, "Join.saveBest", {"matchKey": "match", "measureKey": "delta"})
    image = Image([], {"time": 100, "group": "g"})
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        invoke_join(translator, "Join.apply", {
            "join": join,
            "primary": ImageSequence([image] * 100),
            "secondary": ImageSequence([image] * 100),
            "condition": condition,
        })


def test_long_scalar_comparison_is_charged_before_pair_work_exceeds_budget():
    translator = Translator([], {}, None)
    translator.steps = 49_000
    join = invoke_join(translator, "Join.saveAll", {"matchesKey": "matches"})
    key = "shared-prefix-" + "x" * 1_000
    left = Image([], {"key": key})
    right = Image([], {"key": key})
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        invoke_join(translator, "Join.apply", {
            "join": join,
            "primary": ImageSequence([left]),
            "secondary": ImageSequence([right]),
            "condition": Filter("equals", {"leftField": "key", "rightField": "key"}),
        })


def test_join_string_ordering_keys_are_charged_for_repeated_prefix_scans():
    translator = Translator([], {}, None)
    join = invoke_join(translator, "Join.saveFirst", {
        "matchKey": "match", "ordering": "rank",
    })
    primary = Image([], {"group": "g"})
    secondary = ImageSequence([
        Image([], {"group": "g", "rank": "r" * 5_000 + str(index)})
        for index in range(16)
    ])
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        invoke_join(translator, "Join.apply", {
            "join": join,
            "primary": ImageSequence([primary]),
            "secondary": secondary,
            "condition": Filter("equals", {"leftField": "group", "rightField": "group"}),
        })

