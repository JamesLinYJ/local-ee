"""Nested FeatureCollection construction and flatten over the pinned SDK."""
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, const
from gee.compat.earthengine.nested_collections import (
    NestedFeatureCollection,
    construct_nested_collection,
    flatten_collection,
)


@pytest.fixture
def ee_sdk():
    import ee

    configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2",
        "a" * 48,
        signatures_path="vendor/earthengine-js/algorithms.json",
    )
    assert ee.__version__ == "1.7.49"
    return ee


def compile_sdk(ee, value):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, [], {})["value"]


def test_nested_constructor_and_flatten_preserve_order_geometry_and_ids(ee_sdk):
    ee = ee_sdk
    first = ee.Feature(ee.Geometry.Point(1, 2), {
        "zone": 1, "system:index": "first",
    })
    second = ee.Feature(None, {"zone": 2})
    third = ee.Feature(ee.Geometry.Point(3, 4), {
        "zone": 3, "system:index": "third",
    })
    child_a = ee.FeatureCollection([first, second])
    child_b = ee.FeatureCollection([ee.FeatureCollection([third])])
    nested = ee.FeatureCollection([child_a, child_b, ee.FeatureCollection([])])

    result = compile_sdk(ee, nested.flatten())

    assert result == {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]},
             "properties": {"zone": 1, "system:index": "first"}},
            {"type": "Feature", "geometry": None,
             "properties": {"zone": 2}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3, 4]},
             "properties": {"zone": 3, "system:index": "third"}},
        ],
    }
    assert compile_sdk(ee, nested.flatten().size()) == 3


def test_map_child_collections_flatten_into_existing_filter_and_aggregate(ee_sdk):
    ee = ee_sdk
    source = ee.FeatureCollection([
        ee.Feature(None, {"zone": 1, "value": 10, "system:index": "a"}),
        ee.Feature(None, {"zone": 2, "value": 20, "system:index": "b"}),
    ]).set("origin", {"name": "parent"})
    nested = source.map(lambda row: ee.FeatureCollection([
        row,
        row.set("value", ee.Number(row.get("value")).add(2)),
    ]).set("child_metadata", "discarded-by-flatten"))
    flattened = nested.flatten()

    result = compile_sdk(ee, flattened)
    assert [row["properties"]["value"] for row in result["features"]] == [10, 12, 20, 22]
    assert [row["properties"]["system:index"] for row in result["features"]] == [
        "a", "a", "b", "b",
    ]
    assert result["properties"] == {"origin": {"name": "parent"}}
    assert all("child_metadata" not in row["properties"] for row in result["features"])

    selected = flattened.filter(ee.Filter.gt("value", 10))
    assert compile_sdk(ee, selected.size()) == 3
    assert compile_sdk(ee, selected.aggregate_array("system:index")) == ["a", "b", "b"]


def test_empty_child_collections_flatten_to_an_empty_owned_table(ee_sdk):
    ee = ee_sdk
    nested = ee.FeatureCollection([
        ee.FeatureCollection([]),
        ee.FeatureCollection([ee.FeatureCollection([])]),
    ])
    assert compile_sdk(ee, nested.flatten()) == {
        "type": "FeatureCollection", "features": [],
    }
    raw_empty = ee.FeatureCollection([]).set("tag", {"names": ["empty"]})
    assert compile_sdk(ee, raw_empty.flatten()) == {
        "type": "FeatureCollection", "features": [],
        "properties": {"tag": {"names": ["empty"]}},
    }


def test_empty_mapped_child_collection_flattens_with_root_metadata(ee_sdk):
    ee = ee_sdk
    source = ee.FeatureCollection([]).set("origin", {"name": "empty"})
    result = source.map(lambda row: ee.FeatureCollection([row])).flatten()

    assert compile_sdk(ee, result) == {
        "type": "FeatureCollection", "features": [],
        "properties": {"origin": {"name": "empty"}},
    }


def test_flat_collections_retain_existing_semantics_and_do_not_claim_nested_flatten(ee_sdk):
    ee = ee_sdk
    flat = ee.FeatureCollection([ee.Feature(None, {"value": 4})])
    assert compile_sdk(ee, flat.size()) == 1
    with pytest.raises(UnsupportedEEError, match="requires a finite nested FeatureCollection"):
        compile_sdk(ee, flat.flatten())


def _feature(value=1):
    return {"type": "Feature", "geometry": None, "properties": {"value": value}}


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def test_nested_construction_rejects_mixed_rows_and_opaque_image_values():
    translator = Translator([], {}, None)
    child = _fc([_feature()])
    with pytest.raises(UnsupportedEEError, match="cannot mix Features and child collections"):
        construct_nested_collection(translator, [child, _feature()])

    image = Image([("constant", const(1))], {})
    with pytest.raises(UnsupportedEEError, match="cannot contain dynamic Image"):
        construct_nested_collection(translator, [_fc([{
            "type": "Feature", "geometry": None,
            "properties": {"image": image},
        }])])
    with pytest.raises(UnsupportedEEError, match="Image or sampled elements"):
        construct_nested_collection(translator, [_fc([image])])


def test_nested_construction_rejects_cycles_depth_and_row_overflow():
    cyclic = _fc([])
    cyclic["features"].append(cyclic)
    with pytest.raises(UnsupportedEEError, match="cannot be cyclic"):
        construct_nested_collection(Translator([], {}, None), [cyclic])

    too_deep = _fc([_feature()])
    for _ in range(97):
        too_deep = _fc([too_deep])
    with pytest.raises(UnsupportedEEError, match="exceeds depth 96"):
        construct_nested_collection(Translator([], {}, None), [too_deep])

    with pytest.raises(UnsupportedEEError, match="at most 1000 total rows"):
        construct_nested_collection(Translator([], {}, None), [
            _fc([_feature(i) for i in range(501)]),
            _fc([_feature(i) for i in range(500)]),
        ])


def test_nested_total_node_bound_precedes_copy_materialization():
    empty = _fc([])
    branch = _fc([empty] * 10)
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="10000 total nodes"):
        construct_nested_collection(translator, [branch] * 1000)
    assert translator.steps < 50000


def test_flatten_returns_fresh_rows_and_owned_collection_metadata():
    source_row = _feature()
    child = _fc([source_row, source_row])
    source_metadata = {"tag": {"name": "outer"}}
    translator = Translator([], {}, None)
    nested = construct_nested_collection(
        translator, [child], metadata=(source_metadata, True),
    )
    assert isinstance(nested, NestedFeatureCollection)

    output = flatten_collection(translator, nested)
    output["features"][0]["properties"]["value"] = 99
    output["properties"]["tag"]["name"] = "changed"
    assert output["features"][1]["properties"]["value"] == 1
    assert source_row["properties"]["value"] == 1
    assert source_metadata["tag"]["name"] == "outer"


def test_flatten_preserves_explicit_top_level_feature_id():
    source = {
        "type": "Feature", "geometry": None, "properties": {"value": 3},
        "id": "explicit-id",
    }
    nested = construct_nested_collection(
        Translator([], {}, None), [_fc([source])],
    )
    assert flatten_collection(Translator([], {}, None), nested)["features"] == [source]


def test_deep_wide_flatten_keeps_row_buffer_and_work_bounded():
    rows = [_feature(index) for index in range(100)]
    tree = _fc(rows)
    for _ in range(80):
        tree = _fc([tree])
    translator = Translator([], {}, None)

    nested = construct_nested_collection(translator, [tree])
    result = flatten_collection(translator, nested)

    assert [row["properties"]["value"] for row in result["features"]] == list(range(100))
    assert translator.steps < 50000


def test_nested_collection_cannot_be_used_as_a_static_condition():
    nested = construct_nested_collection(
        Translator([], {}, None), [_fc([_feature()])],
    )
    with pytest.raises(UnsupportedEEError, match="not static conditions"):
        bool(nested)


def test_constructor_reserves_child_inspection_before_classification(monkeypatch):
    import gee.compat.earthengine.nested_collections as nested_module

    translator = Translator([], {}, None)
    translator.steps = 49999

    def unexpected_scan(_):
        raise AssertionError("child classification ran before the budget reservation")

    monkeypatch.setattr(nested_module, "is_collection_value", unexpected_scan)
    with pytest.raises(UnsupportedEEError, match="exceeds compilation limits"):
        construct_nested_collection(translator, [_fc([])])


def test_flatten_reserves_root_children_before_inspecting_them(monkeypatch):
    import gee.compat.earthengine.nested_collections as nested_module
    import gee.compat.earthengine.nested_collection_values as value_module

    nested = construct_nested_collection(
        Translator([], {}, None), [_fc([_feature()])],
    )
    translator = Translator([], {}, None)
    translator.steps = 49999
    original = value_module.is_collection_value
    inspected_children = []

    def tracked(value):
        if not isinstance(value, NestedFeatureCollection):
            inspected_children.append(value)
        return original(value)

    monkeypatch.setattr(value_module, "is_collection_value", tracked)
    with pytest.raises(UnsupportedEEError, match="exceeds compilation limits"):
        flatten_collection(translator, nested)
    assert inspected_children == []
