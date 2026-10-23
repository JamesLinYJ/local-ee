"""Pinned SDK serialization and bounded finite FeatureCollection selection."""
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_values import StaticArray
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.compile import compile_expression
from gee.compat.earthengine import feature_table_construction
from gee.compat.earthengine.feature_table_selection import (
    invoke_feature_table_selection,
)
from gee.compat.earthengine.ir import (
    Collection, Image, ImageSequence, Pixel, SampledFeatures, Source,
    UnsupportedEEError,
)
from gee.compat.earthengine.public_values import public_result
from gee.ee_python_client import configure_local_ee
from gee.compat.earthengine.runtime_feature_ir import RFClassifiedFeatureTable


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def _root_invocation(encoded):
    scope = dict(encoded.get("scope", []))

    def resolve(value):
        if isinstance(value, dict) and value.get("type") == "ValueRef":
            return resolve(scope[value["value"]])
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        return value

    root = resolve(encoded["value"])
    assert root["type"] == "Invocation"
    return root


def _invoke(name, arguments, translator=None):
    return invoke_feature_table_selection(
        translator or Translator([], {}, None), name, arguments,
    )


def _feature(properties, *, geometry=None, feature_id=None):
    result = {"type": "Feature", "geometry": geometry, "properties": properties}
    if feature_id is not None:
        result["id"] = feature_id
    return result


def test_pinned_python_sdk_serializes_selection_and_column_calls(ee):
    collection = ee.FeatureCollection([
        ee.Feature(None, {"label": "oak", "code": 1}),
    ])
    cases = [
        (collection.distinct(["label", "code"]), "Collection.distinct", {"collection", "properties"}),
        (collection.remap([1], [7], "code"), "Collection.remap",
         {"collection", "lookupIn", "lookupOut", "columnName"}),
        (ee.FeatureCollection.fromColumns([[1, 2], ["a", "b"]], ["number", "label"]),
         "Collection.fromColumns", {"columns", "propertyNames"}),
    ]
    for expression, function_name, arguments in cases:
        call = _root_invocation(ee.serializer.encode(expression, for_cloud_api=False))
        assert call["functionName"] == function_name
        assert set(call["arguments"]) == arguments


def test_pinned_sdk_calls_compile_through_the_public_finite_boundary(ee):
    source = ee.FeatureCollection([
        ee.Feature(None, {"key": "a", "class": 1}),
        ee.Feature(None, {"key": "a", "class": 9}),
        ee.Feature(None, {"key": "b", "class": 2}),
    ])

    def compute(expression):
        encoded = ee.serializer.encode(expression, for_cloud_api=False)
        return compile_expression(encoded, [], {})["value"]

    distinct = compute(source.distinct("key"))
    assert [feature["properties"]["key"] for feature in distinct["features"]] == ["a", "b"]
    remapped = compute(source.remap([1, 2], [7, 8], "class"))
    assert [feature["properties"]["class"] for feature in remapped["features"]] == [7, 8]
    columns = compute(ee.FeatureCollection.fromColumns([[1, 2], ["x", "y"]], ["n", "label"]))
    assert [feature["properties"] for feature in columns["features"]] == [
        {"n": 1, "label": "x"}, {"n": 2, "label": "y"},
    ]


def test_distinct_uses_canonical_strong_serialization_and_preserves_first_rows():
    first_geometry = {"type": "Point", "coordinates": [1, 2]}
    source = {
        "type": "FeatureCollection",
        "properties": {"origin": {"tags": ["input"]}},
        "features": [
            _feature({"key": {"z": 2, "a": [1]}, "other": "first"},
                     geometry=first_geometry, feature_id="first"),
            # Mapping key order does not change this local canonical wire form.
            _feature({"key": {"a": [1], "z": 2}, "other": "duplicate"},
                     geometry={"type": "Point", "coordinates": [9, 9]},
                     feature_id="duplicate"),
            _feature({"key": {"a": [2], "z": 2}, "other": "third"},
                     geometry={"type": "Point", "coordinates": [3, 4]},
                     feature_id="third"),
        ],
    }
    result = _invoke("Collection.distinct", {"collection": source, "properties": ["key"]})
    assert [row["id"] for row in result["features"]] == ["first", "third"]
    assert result["features"][0]["geometry"] == first_geometry
    assert result["features"][0]["properties"]["other"] == "first"
    assert result["properties"] == {"origin": {"tags": ["input"]}}

    result["features"][0]["properties"]["key"]["a"].append(9)
    result["features"][0]["geometry"]["coordinates"][0] = 100
    result["properties"]["origin"]["tags"].append("output")
    assert source["features"][0]["properties"]["key"] == {"z": 2, "a": [1]}
    assert source["features"][0]["geometry"] == first_geometry
    assert source["properties"] == {"origin": {"tags": ["input"]}}

    # The local JSON serialization distinguishes 1 from 1.0; this is a
    # deliberate local inference, not a claim about Google's server hash.
    numeric_rows = {"type": "FeatureCollection", "features": [
        _feature({"v": 1}), _feature({"v": 1.0}),
    ]}
    assert len(_invoke("Collection.distinct", {
        "collection": numeric_rows, "properties": ["v"],
    })["features"]) == 2


def test_distinct_geometry_empty_selection_and_undefined_values_are_explicit():
    source = {"type": "FeatureCollection", "features": [
        _feature({"v": 1}, geometry={"type": "Point", "coordinates": [0, 0]}),
        _feature({"v": 1}, geometry={"type": "Point", "coordinates": [1, 0]}),
    ]}
    geometry_rows = _invoke("Collection.distinct", {
        "collection": source, "properties": [".geo"],
    })["features"]
    assert len(geometry_rows) == 2
    assert len(_invoke("Collection.distinct", {
        "collection": source, "properties": [],
    })["features"]) == 1

    with pytest.raises(UnsupportedEEError, match="selected property is missing"):
        _invoke("Collection.distinct", {
            "collection": {"type": "FeatureCollection", "features": [_feature({})]},
            "properties": "v",
        })
    with pytest.raises(UnsupportedEEError, match="null or missing"):
        _invoke("Collection.distinct", {
            "collection": {"type": "FeatureCollection", "features": [_feature({"v": None})]},
            "properties": "v",
        })
    with pytest.raises(UnsupportedEEError, match="selected property is missing"):
        _invoke("Collection.distinct", {
            "collection": source, "properties": ["missing"],
        })
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        _invoke("Collection.distinct", {"collection": source, "properties": [], "extra": 1})


def test_distinct_preflights_canonical_escaped_and_utf8_bytes():
    value = {"é🔥": ["quote\" slash\\ line\n control\x01"]}
    source = {"type": "FeatureCollection", "features": [
        _feature({"v": value}), _feature({"v": value.copy()}),
    ]}
    rows = _invoke("Collection.distinct", {
        "collection": source, "properties": ["v"],
    })["features"]
    assert len(rows) == 1


def test_remap_drops_unmatched_rows_and_preserves_row_identity_and_ownership():
    geometry = {"type": "Point", "coordinates": [4, 5]}
    source = {
        "type": "FeatureCollection",
        "properties": {"band_order": ["nir", "red"]},
        "features": [
            _feature({"class": 1, "nested": {"keep": [7]}},
                     geometry=geometry, feature_id="one"),
            _feature({"class": 9, "nested": {"drop": True}}, feature_id="unmatched"),
            _feature({"class": "water", "nested": {"keep": [8]}}, feature_id="two"),
            _feature({"nested": {"missing": True}}, feature_id="missing"),
            _feature({"class": None}, feature_id="null"),
        ],
    }
    result = _invoke("Collection.remap", {
        "collection": source, "lookupIn": [1, "water"], "lookupOut": [4, 8],
        "columnName": "class",
    })
    assert [row["id"] for row in result["features"]] == ["one", "two"]
    assert [row["properties"]["class"] for row in result["features"]] == [4, 8]
    assert result["features"][0]["geometry"] == geometry
    assert result["features"][0]["properties"]["nested"] == {"keep": [7]}
    assert result["properties"] == {"band_order": ["nir", "red"]}

    result["features"][0]["properties"]["nested"]["keep"].append(99)
    result["features"][0]["geometry"]["coordinates"].append(6)
    result["properties"]["band_order"].reverse()
    assert source["features"][0]["properties"]["nested"] == {"keep": [7]}
    assert source["features"][0]["geometry"] == geometry
    assert source["properties"]["band_order"] == ["nir", "red"]


def test_remap_rejects_ambiguous_types_duplicates_lengths_and_unknown_arguments():
    source = {"type": "FeatureCollection", "features": [_feature({"v": 1})]}
    base = {"collection": source, "lookupIn": [1], "lookupOut": [2], "columnName": "v"}
    cases = [
        ({**base, "lookupOut": []}, "equal lengths"),
        ({**base, "lookupIn": [1, 1], "lookupOut": [2, 3]}, "must be unique"),
        ({**base, "lookupIn": [1.0]}, "strings or exact integers"),
        ({**base, "lookupOut": [2.0]}, "lookupOut values must be integers"),
        ({**base, "extra": True}, "Unsupported algorithm arguments"),
    ]
    for arguments, message in cases:
        with pytest.raises(UnsupportedEEError, match=message):
            _invoke("Collection.remap", arguments)
    float_column = {"type": "FeatureCollection", "features": [_feature({"v": 1.0})]}
    with pytest.raises(UnsupportedEEError, match="column values must be strings or integers"):
        _invoke("Collection.remap", {**base, "collection": float_column})


def test_from_columns_is_column_major_keeps_explicit_nulls_and_copies_values():
    nested = {"items": [1]}
    columns = [[10, 20], ["a", None], [nested, {"items": [2]}]]
    result = _invoke("Collection.fromColumns", {
        "columns": columns, "propertyNames": ["count", "label", "payload"],
    })
    assert result == {
        "type": "FeatureCollection",
        "features": [
            _feature({"count": 10, "label": "a", "payload": {"items": [1]}}),
            _feature({"count": 20, "label": None, "payload": {"items": [2]}}),
        ],
    }
    result["features"][0]["properties"]["payload"]["items"].append(9)
    assert nested == {"items": [1]}


def test_from_columns_preflights_array_and_image_public_shapes():
    image = Image([("constant", Pixel("constant", (1,)))], {"system:index": "scene-1"})
    result = _invoke("Collection.fromColumns", {
        "columns": [[StaticArray(np.array([[1, 2], [3, 4]]))], [image]],
        "propertyNames": ["array", "image"],
    })
    public = public_result({"kind": "value", "value": result, "warnings": []})
    properties = public["value"]["features"][0]["properties"]
    assert properties["array"] == [[1, 2], [3, 4]]
    assert properties["image"]["id"] == "scene-1"
    assert properties["image"]["bands"] == [{"id": "constant"}]


def test_from_columns_rejects_mismatched_rows_types_and_unknown_parameters():
    cases = [
        ({"columns": [[1], [2, 3]], "propertyNames": ["a", "b"]}, "equal row counts"),
        ({"columns": [[1]], "propertyNames": []}, "equal lengths"),
        ({"columns": [[1], [2]], "propertyNames": ["x", "x"]}, "must be unique"),
        ({"columns": [[1]], "propertyNames": ["x"], "propertyTypes": ["Integer"]},
         "propertyTypes is unsupported"),
        ({"columns": [(1, 2)], "propertyNames": ["x"]}, "literal list columns"),
        ({"columns": [[1]], "propertyNames": ["x"], "ignored": True},
         "Unsupported algorithm arguments"),
    ]
    for arguments, message in cases:
        with pytest.raises(UnsupportedEEError, match=message):
            _invoke("Collection.fromColumns", arguments)


def test_dynamic_receivers_are_rejected_and_shared_budgets_remain_bounded():
    image = Image([("constant", Pixel("constant", (1,)))], {})
    dynamic_tables = [
        SampledFeatures(image, "{}"),
        RFClassifiedFeatureTable(None, None, "{}", (), None, None),
        Collection(Source("images", (), ()), image),
        ImageSequence([image]),
    ]
    for table in dynamic_tables:
        for name, arguments in [
            ("Collection.distinct", {"collection": table, "properties": ["x"]}),
            ("Collection.remap", {"collection": table, "lookupIn": [],
                                   "lookupOut": [], "columnName": "x"}),
        ]:
            with pytest.raises(UnsupportedEEError, match="dynamic sample|classified tables|ImageCollections"):
                _invoke(name, arguments)

    with pytest.raises(UnsupportedEEError, match="static JSON"):
        _invoke("Collection.fromColumns", {
            "columns": [[SampleValue()]], "propertyNames": ["x"],
        })

    for name, arguments in [
        ("Collection.distinct", {"collection": object(), "properties": ["x"]}),
        ("Collection.remap", {"collection": object(), "lookupIn": [],
                               "lookupOut": [], "columnName": "x"}),
    ]:
        with pytest.raises(UnsupportedEEError):
            _invoke(name, arguments)

    translator = Translator([], {}, None)
    translator.steps = 49_995
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        _invoke("Collection.fromColumns", {
            "columns": [[1]], "propertyNames": ["x"],
        }, translator)

def test_from_columns_preflights_repeated_property_names_against_output_limit(monkeypatch):
    monkeypatch.setattr(feature_table_construction, "_MAX_JSON_BYTES", 1000)
    with pytest.raises(UnsupportedEEError, match="1 MB public JSON limit"):
        _invoke("Collection.fromColumns", {
            "columns": [[1] * 20], "propertyNames": ["long_property_name_" * 2],
        })


def test_selection_copy_paths_preflight_the_full_result_before_copy(monkeypatch):
    monkeypatch.setattr(feature_table_construction, "_MAX_JSON_BYTES", 700)
    source = {"type": "FeatureCollection", "features": [
        _feature({"kind": index, "long_property_name_" * 2: index})
        for index in range(20)
    ]}
    with pytest.raises(UnsupportedEEError, match="1 MB public JSON limit"):
        _invoke("Collection.distinct", {"collection": source, "properties": "kind"})
    with pytest.raises(UnsupportedEEError, match="1 MB public JSON limit"):
        _invoke("Collection.remap", {
            "collection": source, "lookupIn": list(range(20)),
            "lookupOut": list(range(20, 40)), "columnName": "kind",
        })


class SampleValue:
    """Opaque value used to confirm fromColumns rejects non-finite cells."""
