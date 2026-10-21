"""Pinned SDK serialization and independent controls for numeric time joins."""
import json
import math
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from test_ee_translate import evaluate_graph


BASE = 1_700_000_000_000  # epoch milliseconds
LIMIT = 800


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=Path(__file__).resolve().parents[1] / "vendor/earthengine-js/algorithms.json",
    )


@pytest.fixture
def local():
    rows = [
        ("p-a", "primary", BASE),
        ("p-b", "primary", BASE),  # duplicate primary timestamp remains a distinct image
        ("p-later", "primary", BASE + 2_000),
        ("p-missing", "primary", "missing"),
        ("p-null", "primary", None),
        ("s-too-far", "secondary", BASE + 1_001),
        ("s-exact-first", "secondary", BASE),
        ("s-exact-second", "secondary", BASE),
        ("s-first-tie", "secondary", BASE + 800),
        ("s-second-tie", "secondary", BASE - 800),
        ("s-near-2-first", "secondary", BASE + 2_250),
        ("s-near-2-duplicate", "secondary", BASE + 2_250),
        ("s-null", "secondary", None),
        ("s-missing", "secondary", "missing"),
    ]
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
    items = []
    for iid, side, timestamp in rows:
        properties = {"system:index": iid, "side": side, "group": "g"}
        if timestamp != "missing":
            properties["system:time_start"] = timestamp
        items.append({"id": iid, "bbox": [0, 0, 2, 2], "geometry": geometry, "properties": properties})
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": ["red", "nir"]}}}]
    return catalog, {"sentinel-2-l2a": items}


def _collections(ee):
    source = ee.ImageCollection("sentinel-2-l2a")
    return source.filter(ee.Filter.eq("side", "primary")), source.filter(ee.Filter.eq("side", "secondary"))


def _condition(ee, difference=LIMIT):
    return ee.Filter.maxDifference(
        difference=difference,
        leftField="system:time_start",
        rightField="system:time_start",
    )


def _join(ee, join, condition=None):
    primary, secondary = _collections(ee)
    return ee.ImageCollection(join.apply(primary, secondary, condition or _condition(ee)))


def _compile(ee, expression, local):
    # Every positive operation is built by the pinned official SDK and reaches
    # the same decoder used by Python and JavaScript callers.
    encoded = ee.serializer.encode(expression, for_cloud_api=False)
    return compile_expression(encoded, *local)


def _reference_best(primary_rows, secondary_rows, threshold):
    """Hand-derived absolute-distance reference, including stable input ties."""
    expected = {}
    for primary_id, primary_time in primary_rows:
        candidates = []
        for index, (secondary_id, secondary_time) in enumerate(secondary_rows):
            distance = abs(primary_time - secondary_time)
            if distance <= threshold:
                candidates.append((distance, index, secondary_id))
        if candidates:
            distance, _, secondary_id = min(candidates)
            expected[primary_id] = (secondary_id, distance)
    return expected


def test_save_best_matches_reference_and_keeps_measure_on_selected_image(ee, local):
    joined = _join(ee, ee.Join.saveBest("best", "delta"))
    result = _compile(ee, joined, local)
    primary = [("p-a", BASE), ("p-b", BASE), ("p-later", BASE + 2_000)]
    secondary = [
        ("s-too-far", BASE + 1_001),
        ("s-exact-first", BASE),
        ("s-exact-second", BASE),
        ("s-first-tie", BASE + 800),
        ("s-second-tie", BASE - 800),
        ("s-near-2-first", BASE + 2_250),
        ("s-near-2-duplicate", BASE + 2_250),
    ]
    expected = _reference_best(primary, secondary, LIMIT)
    assert result["source_item_ids"] == list(expected)
    for feature in result["features"]:
        primary_id = feature["properties"]["system:index"]
        best = feature["properties"]["best"]
        expected_id, expected_delta = expected[primary_id]
        assert best["id"] == expected_id
        assert best["properties"]["delta"] == expected_delta
        assert "delta" not in feature["properties"]
    # The <= 800 ms threshold is inclusive; a candidate 1001 ms away fails.
    assert expected["p-a"] == ("s-exact-first", 0)
    assert expected["p-later"] == ("s-near-2-first", 250)
    assert "s-too-far" not in {entry[0] for entry in expected.values()}
    json.dumps(result, allow_nan=False)


def test_save_best_selected_image_drives_downstream_pixel_sources(ee, local):
    joined = _join(ee, ee.Join.saveBest("best", "delta"))
    primary = ee.Image(joined.first())
    match = ee.Image(primary.get("best"))
    combined = primary.select("red").addBands(match.select("nir").rename("matched_nir"))
    result = _compile(ee, combined, local)
    arrays = {
        "p-a": {"red": np.array([1.0, 3.0]), "nir": np.array([9.0, 11.0])},
        "s-exact-first": {"red": np.array([100.0, 300.0]), "nir": np.array([7.0, np.nan])},
    }
    values, names, timed = evaluate_graph(result, arrays)
    assert names == ["red", "matched_nir"] and timed is False
    np.testing.assert_equal(values, [[1.0, 3.0], [7.0, np.nan]])
    assert result["source_item_ids"] == ["p-a", "s-exact-first"]


def test_save_first_and_save_all_attach_measures_with_their_documented_match(ee, local):
    unordered = _join(ee, ee.Join.saveFirst("match", measureKey="delta"))
    unordered_result = _compile(ee, unordered, local)
    unordered_match = unordered_result["features"][0]["properties"]["match"]
    assert (unordered_match["id"], unordered_match["properties"]["delta"]) == ("s-exact-first", 0)

    first = _join(ee, ee.Join.saveFirst(
        "match", ordering="system:time_start", ascending=True, measureKey="delta",
    ))
    first_result = _compile(ee, first, local)
    first_match = first_result["features"][0]["properties"]["match"]
    assert first_match["id"] == "s-second-tie"
    assert first_match["properties"]["delta"] == 800
    assert "delta" not in first_result["features"][0]["properties"]

    all_matches = _join(ee, ee.Join.saveAll(
        "matches", ordering="system:time_start", ascending=True, measureKey="delta",
    ))
    all_result = _compile(ee, all_matches, local)
    matches = all_result["features"][0]["properties"]["matches"]
    assert [(match["id"], match["properties"]["delta"]) for match in matches] == [
        ("s-second-tie", 800), ("s-exact-first", 0),
        ("s-exact-second", 0), ("s-first-tie", 800),
    ]


def test_unary_max_difference_uses_absolute_numeric_milliseconds(ee, local):
    collection, _ = _collections(ee)
    within_one_second = collection.filter(ee.Filter.maxDifference(
        difference=1_000, leftField="system:time_start", rightValue=BASE,
    ))
    result = _compile(ee, within_one_second, local)
    assert result["source_item_ids"] == ["p-a", "p-b"]

    negative = collection.filter(ee.Filter.maxDifference(
        difference=-1, leftField="system:time_start", rightValue=BASE,
    ))
    assert _compile(ee, negative.size(), local)["value"] == 0


def test_outer_preserves_rows_with_missing_or_null_times_without_match_properties(ee, local):
    joined = _join(ee, ee.Join.saveBest("best", "delta", outer=True))
    result = _compile(ee, joined, local)
    assert result["source_item_ids"] == ["p-a", "p-b", "p-later", "p-missing", "p-null"]
    for feature in result["features"][-2:]:
        assert "best" not in feature["properties"]

    local[1]["sentinel-2-l2a"] = [
        item for item in local[1]["sentinel-2-l2a"]
        if item["properties"]["side"] == "primary" or item["id"] in {"s-null", "s-missing"}
    ]
    no_numeric_matches = _compile(ee, joined, local)
    assert no_numeric_matches["source_item_ids"] == result["source_item_ids"]
    assert all("best" not in item["properties"] for item in no_numeric_matches["features"])


@pytest.mark.parametrize("constructor,condition", [
    (lambda ee: ee.Join.saveBest("best", "delta"), lambda ee: ee.Filter.equals(leftField="group", rightField="group")),
    (lambda ee: ee.Join.saveBest("best", "delta"), lambda ee: ee.Filter.And(
        _condition(ee), _condition(ee, difference=400),
    )),
    (lambda ee: ee.Join.saveFirst("match", measureKey="delta"), lambda ee: ee.Filter.Or(
        _condition(ee), ee.Filter.equals(leftField="group", rightField="group"),
    )),
    (lambda ee: ee.Join.saveAll("matches", measureKey="delta"), lambda ee: ee.Filter.Not(_condition(ee))),
])
def test_measure_joins_reject_conditions_without_one_unambiguous_measure(ee, local, constructor, condition):
    with pytest.raises(UnsupportedEEError, match="single Filter.maxDifference|compound measures"):
        _compile(ee, _join(ee, constructor(ee), condition(ee)), local)


def test_nonfinite_difference_and_metadata_are_rejected(ee, local):
    primary, _ = _collections(ee)
    bad_filter = primary.filter(ee.Filter.maxDifference(
        difference=math.nan, leftField="system:time_start", rightValue=BASE,
    ))
    with pytest.raises(UnsupportedEEError, match="finite"):
        _compile(ee, bad_filter, local)

    next(item for item in local[1]["sentinel-2-l2a"] if item["id"] == "s-missing")["properties"]["system:time_start"] = math.inf
    with pytest.raises(UnsupportedEEError, match="finite"):
        _compile(ee, _join(ee, ee.Join.saveBest("best", "delta")), local)


def test_temporal_join_work_and_frame_limits_are_enforced(ee, local):
    geometry = local[1]["sentinel-2-l2a"][0]["geometry"]
    catalog_item = local[1]["sentinel-2-l2a"][0]
    local[1]["sentinel-2-l2a"] = [
        {
            **catalog_item,
            "id": f"{side}-{index}",
            "geometry": geometry,
            "properties": {
                "system:index": f"{side}-{index}",
                "side": side,
                "system:time_start": BASE + index,
            },
        }
        for side in ("primary", "secondary")
        for index in range(125)
    ]
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        _compile(ee, _join(ee, ee.Join.saveBest("best", "delta")), local)

    local[1]["sentinel-2-l2a"] = [
        {
            **catalog_item,
            "id": f"p-{index}",
            "geometry": geometry,
            "properties": {"system:index": f"p-{index}", "side": "primary", "system:time_start": BASE},
        }
        for index in range(1001)
    ]
    with pytest.raises(UnsupportedEEError, match="1000 frames"):
        _compile(ee, _join(ee, ee.Join.saveBest("best", "delta")), local)
