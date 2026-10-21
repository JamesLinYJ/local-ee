"""Pinned SDK Join.inner behavior over finite local ImageCollections."""
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.inner_join import (
    apply_inner,
    construct_inner,
)
from gee.compat.earthengine.ir import (
    Filter,
    Image,
    ImageSequence,
    Pixel,
    Source,
    UnsupportedEEError,
)
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=Path(__file__).resolve().parents[1]
        / "vendor/earthengine-js/algorithms.json",
    )


@pytest.fixture
def local():
    rows = [
        ("p-a", "primary", "a", 100),
        ("p-b", "primary", "b", 200),
        ("s-a1", "secondary", "a", 103),
        ("s-a2", "secondary", "a", 108),
        ("s-b", "secondary", "b", 207),
        ("s-none", "secondary", "x", 500),
    ]
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
    }
    items = [{
        "id": image_id,
        "bbox": [0, 0, 2, 2],
        "geometry": geometry,
        "properties": {
            "system:index": image_id,
            "side": side,
            "group": group,
            "time": timestamp,
        },
    } for image_id, side, group, timestamp in rows]
    catalog = [{
        "id": "sentinel-2-l2a",
        "cube:dimensions": {"bands": {"values": ["red"]}},
    }]
    return catalog, {"sentinel-2-l2a": items}


def _collections(ee):
    collection = ee.ImageCollection("sentinel-2-l2a")
    return (
        collection.filter(ee.Filter.eq("side", "primary")),
        collection.filter(ee.Filter.eq("side", "secondary")),
    )


def _compile(ee, value, local):
    encoded = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(encoded, *local)["value"]


def test_pinned_sdk_defaults_create_cartesian_feature_pairs(ee, local):
    primary, secondary = _collections(ee)
    join = ee.Join.inner()
    result = _compile(ee, join.apply(
        primary,
        secondary,
        ee.Filter.equals(leftValue="constant", rightValue="constant"),
    ), local)

    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 8
    assert all(feature["geometry"] is None for feature in result["features"])
    assert all(set(feature["properties"]) == {"primary", "secondary"}
               for feature in result["features"])
    pairs = [
        (feature["properties"]["primary"]["id"],
         feature["properties"]["secondary"]["id"])
        for feature in result["features"]
    ]
    assert pairs == [
        ("p-a", "s-a1"), ("p-a", "s-a2"), ("p-a", "s-b"), ("p-a", "s-none"),
        ("p-b", "s-a1"), ("p-b", "s-a2"), ("p-b", "s-b"), ("p-b", "s-none"),
    ]
    assert all(feature["properties"]["primary"]["type"] == "Image"
               and feature["properties"]["secondary"]["type"] == "Image"
               for feature in result["features"])


def test_pinned_sdk_custom_keys_and_unmatched_pairs_are_empty(ee, local):
    primary, secondary = _collections(ee)
    result = _compile(ee, ee.Join.inner(
        primaryKey="left_image", secondaryKey="right_image",
    ).apply(primary, secondary, ee.Filter.equals(
        leftField="group", rightField="group",
    )), local)

    assert len(result["features"]) == 3
    assert all(set(feature["properties"]) == {"left_image", "right_image"}
               for feature in result["features"])
    assert [
        (feature["properties"]["left_image"]["id"],
         feature["properties"]["right_image"]["id"])
        for feature in result["features"]
    ] == [("p-a", "s-a1"), ("p-a", "s-a2"), ("p-b", "s-b")]

    empty = _compile(ee, ee.Join.inner().apply(
        primary,
        secondary,
        ee.Filter.equals(leftValue="no-match", rightValue="other"),
    ), local)
    assert empty == {"type": "FeatureCollection", "features": []}


def test_pinned_sdk_measured_pairs_attach_max_difference(ee, local):
    primary, secondary = _collections(ee)
    result = _compile(ee, ee.Join.inner(measureKey="time_delta").apply(
        primary,
        secondary,
        ee.Filter.maxDifference(
            difference=10,
            leftField="time",
            rightField="time",
        ),
    ), local)

    assert [
        (feature["properties"]["primary"]["id"],
         feature["properties"]["secondary"]["id"],
         feature["properties"]["time_delta"])
        for feature in result["features"]
    ] == [("p-a", "s-a1", 3), ("p-a", "s-a2", 8), ("p-b", "s-b", 7)]


def test_unmeasured_inner_keeps_max_difference_inside_boolean_or(ee, local):
    primary, secondary = _collections(ee)
    condition = ee.Filter.Or(
        ee.Filter.maxDifference(difference=10, leftField="time", rightField="time"),
        ee.Filter.equals(leftValue="always", rightValue="always"),
    )
    result = _compile(ee, ee.Join.inner().apply(primary, secondary, condition), local)

    assert len(result["features"]) == 8
    assert all(set(feature["properties"]) == {"primary", "secondary"}
               for feature in result["features"])
    with pytest.raises(UnsupportedEEError, match="cannot contain a measured"):
        _compile(ee, ee.Join.inner(measureKey="delta").apply(
            primary, secondary, condition,
        ), local)


@pytest.mark.parametrize("arguments", [
    {"unknown": True},
    {"primaryKey": "same", "secondaryKey": "same"},
    {"primaryKey": "same", "secondaryKey": "other", "measureKey": "same"},
    {"primaryKey": "nested.key"},
    {"secondaryKey": ""},
])
def test_constructor_rejects_unknown_and_colliding_or_invalid_keys(arguments):
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError):
        construct_inner(translator, arguments)


def test_apply_requires_image_collections_and_bounded_inputs_and_output():
    translator = Translator([], {}, None)
    join = construct_inner(translator, {})
    condition = Filter("equals", {"leftValue": "x", "rightValue": "x"})
    with pytest.raises(UnsupportedEEError, match="Expected an ImageCollection"):
        apply_inner(Translator([], {}, None), {
            "join": join, "primary": Image([], {}), "secondary": ImageSequence([]),
            "condition": condition,
        })

    image = Image([("red", Pixel("constant", (1,)))], {"system:index": "x"})
    too_many = ImageSequence([image] * 1001)
    with pytest.raises(UnsupportedEEError, match="at most 1000"):
        apply_inner(Translator([], {}, None), {
            "join": join, "primary": too_many, "secondary": ImageSequence([]),
            "condition": condition,
        })

    with pytest.raises(UnsupportedEEError, match="at most 1000 matched output pairs"):
        apply_inner(Translator([], {}, None), {
            "join": join, "primary": ImageSequence([image, image]),
            "secondary": ImageSequence([image] * 501), "condition": condition,
        })


def test_pair_checks_use_shared_work_budget():
    image = Image([("red", Pixel("constant", (1,)))], {"system:index": "x"})
    condition = Filter("equals", {"leftValue": "x", "rightValue": "unmatched"})
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        apply_inner(Translator([], {}, None), {
            "join": construct_inner(Translator([], {}, None), {}),
            "primary": ImageSequence([image] * 225),
            "secondary": ImageSequence([image] * 225),
            "condition": condition,
        })


def test_measured_inner_join_does_not_repeat_the_numeric_predicate():
    image = Image([("red", Pixel("constant", (1,)))], {"time": 0})
    translator = Translator([], {}, None)
    output = apply_inner(translator, {
        "join": construct_inner(translator, {"measureKey": "delta"}),
        "primary": ImageSequence([image] * 850),
        "secondary": ImageSequence([image]),
        "condition": Filter("maxDifference", {
            "difference": 0, "leftField": "time", "rightField": "time",
        }),
    })
    assert len(output["features"]) == 850
    assert all(feature["properties"]["delta"] == 0 for feature in output["features"])
    assert translator.steps < 50000


def test_inner_feature_properties_retain_real_source_images():
    translator = Translator([], {}, None)
    primary = Image(
        [("red", Pixel("constant", (1,)))],
        {"system:index": "p0", "key": "x"},
        Source("local", ("p0",), ("red",)),
    )
    secondary = Image(
        [("red", Pixel("constant", (2,)))],
        {"system:index": "s0", "key": "x"},
        Source("local", ("s0",), ("red",)),
    )
    output = apply_inner(translator, {
        "join": construct_inner(translator, {}),
        "primary": ImageSequence([primary]),
        "secondary": ImageSequence([secondary]),
        "condition": Filter("equals", {"leftField": "key", "rightValue": "x"}),
    })

    feature = output["features"][0]
    assert feature["geometry"] is None
    assert feature["properties"]["primary"] is primary
    assert feature["properties"]["secondary"] is secondary
    assert feature["properties"]["primary"].source.ids == ("p0",)
    assert feature["properties"]["secondary"].source.ids == ("s0",)
