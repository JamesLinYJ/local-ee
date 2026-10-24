"""Bounded local Feature identity, selection, geometry and array semantics."""
import numpy as np
import pytest

from gee.compat.earthengine.array_core import StaticArray
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.feature_structure import (
    FEATURE_STRUCTURE_ARGUMENTS,
    FEATURE_STRUCTURE_METHODS,
    invoke_feature_structure,
)
from gee.compat.earthengine import geometry_values
from gee.compat.earthengine import feature_structure
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.public_values import public_value


def _translator():
    return Translator([], [], {})


def _feature(properties=None, geometry=None, *, feature_id=None):
    value = {
        "type": "Feature", "geometry": geometry,
        "properties": {} if properties is None else properties,
    }
    if feature_id is not None:
        value["id"] = feature_id
    return value


def _invoke(name, **arguments):
    return invoke_feature_structure(_translator(), name, arguments)


def test_exported_method_and_argument_contracts_are_complete():
    expected = {
        "Feature.id": (frozenset({"element"}), frozenset()),
        "Feature.select": (
            frozenset({"input", "propertySelectors"}),
            frozenset({"newProperties", "retainGeometry"}),
        ),
        "Feature.setGeometry": (frozenset({"feature"}), frozenset({"geometry"})),
        "Feature.toArray": (frozenset({"feature", "properties"}), frozenset()),
    }
    assert FEATURE_STRUCTURE_ARGUMENTS == expected
    assert FEATURE_STRUCTURE_METHODS == frozenset(expected)


def test_feature_id_reads_only_real_top_level_or_system_index_ids():
    assert _invoke("Feature.id", element=_feature({"system:index": "row-1"})) == "row-1"
    assert _invoke("Feature.id", element=_feature({}, feature_id="row-2")) == "row-2"
    assert _invoke("Feature.id", element=_feature({})) is None
    with pytest.raises(UnsupportedEEError, match="different elements"):
        _invoke(
            "Feature.id",
            element=_feature({"system:index": "row-1"}, feature_id="row-2"),
        )


def test_select_uses_re2_fullmatch_order_rename_and_owned_results():
    source = _feature(
        {"name": "oak", "band.1": 10, "band.2": 20, "drop": [1]},
        {"type": "Point", "coordinates": [1, 2]},
        feature_id="feature-1",
    )
    result = _invoke(
        "Feature.select", input=source,
        propertySelectors=["name", r"band\.[12]"],
        newProperties=["label", "b1", "b2"],
    )
    assert result == {
        "type": "Feature", "geometry": source["geometry"],
        "properties": {"label": "oak", "b1": 10, "b2": 20},
        "id": "feature-1",
    }
    assert result is not source
    assert result["properties"] is not source["properties"]
    result["properties"]["b1"] = 999
    assert source["properties"]["band.1"] == 10


def test_select_literal_names_use_re2_validation_and_exact_lookup(monkeypatch):
    source = _feature({f"field_{index:03d}": index for index in range(300)})
    original = feature_structure.compile_pattern
    subjects = []

    def checked_compile(translator, pattern, texts, ignore_case=False):
        subjects.append((pattern, len(texts)))
        return original(translator, pattern, texts, ignore_case)

    monkeypatch.setattr(feature_structure, "compile_pattern", checked_compile)
    result = _invoke(
        "Feature.select", input=source,
        propertySelectors=["field_001", "field_002"],
    )
    assert result["properties"] == {"field_001": 1, "field_002": 2}
    assert subjects == [("field_001", 0), ("field_002", 0)]


def test_select_preserves_system_index_identity_when_removed_or_renamed():
    source = _feature({"system:index": "row-8", "value": 9})
    removed = _invoke(
        "Feature.select", input=source, propertySelectors=["value"],
    )
    assert removed["properties"] == {"value": 9}
    assert removed["id"] == "row-8"
    assert _invoke("Feature.id", element=removed) == "row-8"
    renamed = _invoke(
        "Feature.select", input=source,
        propertySelectors=["system:index"], newProperties=["row_key"],
    )
    assert renamed["properties"] == {"row_key": "row-8"}
    assert renamed["id"] == "row-8"


def test_select_can_remove_geometry_and_deduplicates_overlapping_regex_matches():
    source = _feature(
        {"a": 1, "ab": 2, "b": 3},
        {"type": "Point", "coordinates": [0, 0]},
    )
    result = _invoke(
        "Feature.select", input=source,
        propertySelectors=["a.*", "ab"], retainGeometry=False,
    )
    assert result["properties"] == {"a": 1, "ab": 2}
    assert result["geometry"] is None


@pytest.mark.parametrize("arguments", [
    {"input": _feature({}), "propertySelectors": ["[" ]},
    {"input": _feature({}), "propertySelectors": [], "extra": False},
    {"input": _feature({}), "propertySelectors": [], "retainGeometry": 1},
    {"input": _feature({"a": 1}), "propertySelectors": ["a"],
     "newProperties": ["x", "y"]},
    {"input": _feature({"a": 1}), "propertySelectors": ["a"],
     "newProperties": ["x", "x"]},
])
def test_select_rejects_invalid_parameters_even_with_empty_properties(arguments):
    with pytest.raises(UnsupportedEEError):
        _invoke("Feature.select", **arguments)


def test_select_rejects_explicit_identity_conflicts():
    feature = _feature({"key": "other", "system:index": "row-4"})
    with pytest.raises(UnsupportedEEError, match="cannot replace"):
        _invoke(
            "Feature.select", input=feature,
            propertySelectors=["key"], newProperties=["system:index"],
        )
    with pytest.raises(UnsupportedEEError, match="system:index must be a string"):
        _invoke(
            "Feature.select", input=_feature({"key": None}, feature_id="row-4"),
            propertySelectors=["key"], newProperties=["system:index"],
        )


def test_set_geometry_normalizes_owned_geojson_and_preserves_properties_and_id():
    source = _feature(
        {"system:index": "row-9", "name": "hill", "nested": {"x": [1]}},
        {"type": "Point", "coordinates": [1, 2]},
    )
    result = _invoke(
        "Feature.setGeometry", feature=source,
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1]]]},
    )
    assert result["geometry"] == {
        "type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
    }
    assert result["properties"] == source["properties"]
    assert result["properties"] is not source["properties"]
    assert _invoke("Feature.id", element=result) == "row-9"
    result["properties"]["nested"]["x"].append(2)
    assert source["properties"]["nested"]["x"] == [1]


def test_set_geometry_null_clears_geometry_and_rejects_opaque_values():
    source = _feature({"x": 1}, {"type": "Point", "coordinates": [0, 0]})
    assert _invoke("Feature.setGeometry", feature=source)["geometry"] is None
    assert _invoke("Feature.setGeometry", feature=source, geometry=None)["geometry"] is None
    with pytest.raises(UnsupportedEEError):
        _invoke("Feature.setGeometry", feature=source, geometry=object())


def test_set_geometry_revalidates_and_owns_mutable_geometry_values():
    geometry = geometry_values.decode_geometry_bounded(
        _translator(), {"type": "Point", "coordinates": [1, 2], "geodesic": False},
    )
    result = _invoke("Feature.setGeometry", feature=_feature(), geometry=geometry)
    assert result["geometry"] is not geometry
    assert result["geometry"]._geometry_validated is True
    assert result["geometry"].geometry_metadata == {"geodesic": False}
    geometry["coordinates"][0] = 12
    assert result["geometry"]["coordinates"] == [1, 2]


def test_to_array_builds_owned_readonly_rank_one_array():
    source = _feature({"a": 2, "b": 2.5, "c": True})
    result = _invoke("Feature.toArray", feature=source, properties=["a", "b"])
    assert isinstance(result, StaticArray)
    assert result.data.shape == (2,)
    assert result.data.dtype.kind == "f"
    assert not result.data.flags.writeable
    np.testing.assert_array_equal(result.data, [2, 2.5])
    assert public_value(result) == [2.0, 2.5]
    empty = _invoke("Feature.toArray", feature=source, properties=[])
    assert isinstance(empty, StaticArray)
    assert empty.data.shape == (0,)


@pytest.mark.parametrize("properties", [
    ["missing"], ["null"], ["boolean"], ["text"], ["array"],
])
def test_to_array_rejects_missing_null_and_non_numeric_properties(properties):
    source = _feature({
        "null": None, "boolean": True, "text": "2", "array": [1, 2],
    })
    with pytest.raises(UnsupportedEEError):
        _invoke("Feature.toArray", feature=source, properties=properties)


def test_to_array_rejects_inexact_integer_and_limit_overruns():
    source = _feature({"large": 2**53 + 1, "a": 1})
    with pytest.raises(UnsupportedEEError, match="exact Float64"):
        _invoke("Feature.toArray", feature=source, properties=["large"])
    with pytest.raises(UnsupportedEEError, match="10000"):
        _invoke("Feature.toArray", feature=source, properties=["a"] * 10001)


def test_feature_methods_require_concrete_inline_features():
    with pytest.raises(UnsupportedEEError, match="actual inline Feature"):
        _invoke("Feature.select", input=object(), propertySelectors=[])
    with pytest.raises(UnsupportedEEError, match="requires an actual inline Feature"):
        _invoke(
            "Feature.toArray",
            feature={"type": "FeatureCollection", "features": []}, properties=[],
        )
