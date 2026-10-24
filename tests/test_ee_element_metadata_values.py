"""Bounded typed Element metadata operations over local concrete values."""
import numpy as np
import pytest

from gee.compat.earthengine.array_core import StaticArray
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.element_metadata_values import (
    ELEMENT_METADATA_VALUE_ARGUMENTS,
    ELEMENT_METADATA_VALUE_METHODS,
    invoke_element_metadata_values,
)
from gee.compat.earthengine.ir import Image, Pixel, Source, UnsupportedEEError


def _translator():
    return Translator([], [], {})


def _feature(properties, *, feature_id=None):
    value = {"type": "Feature", "geometry": None, "properties": properties}
    if feature_id is not None:
        value["id"] = feature_id
    return value


def _invoke(name, **arguments):
    return invoke_element_metadata_values(_translator(), name, arguments)


def test_exported_method_and_argument_contracts_are_complete():
    expected = {
        "Element.getNumber": (frozenset({"object", "property"}), frozenset()),
        "Element.getString": (frozenset({"object", "property"}), frozenset()),
        "Element.getArray": (frozenset({"object", "property"}), frozenset()),
        "Element.toDictionary": (frozenset({"element"}), frozenset({"properties"})),
        "Element.replaceProperties": (
            frozenset({"destination"}), frozenset({"source"}),
        ),
    }
    assert ELEMENT_METADATA_VALUE_ARGUMENTS == expected
    assert ELEMENT_METADATA_VALUE_METHODS == frozenset(expected)


def test_typed_getters_preserve_types_and_owned_array_values():
    data = np.array([[1, 2], [3, 4]], dtype=np.int64)
    data.flags.writeable = False
    feature = _feature({"n": 7, "text": "birch", "array": StaticArray(data)})

    assert _invoke("Element.getNumber", object=feature, property="n") == 7
    assert _invoke("Element.getString", object=feature, property="text") == "birch"
    result = _invoke("Element.getArray", object=feature, property="array")
    assert isinstance(result, StaticArray)
    assert result is not feature["properties"]["array"]
    assert result.data is not data
    assert not result.data.flags.writeable
    np.testing.assert_array_equal(result.data, data)


@pytest.mark.parametrize("method", [
    "Element.getNumber", "Element.getString", "Element.getArray",
])
def test_typed_getters_use_nullable_missing_and_null_semantics(method):
    feature = _feature({"explicitNull": None})
    assert _invoke(method, object=feature, property="missing") is None
    assert _invoke(method, object=feature, property="explicitNull") is None


@pytest.mark.parametrize(("method", "value"), [
    ("Element.getNumber", True),
    ("Element.getNumber", "4"),
    ("Element.getString", 4),
    ("Element.getArray", [1, 2]),
])
def test_typed_getters_reject_coercions(method, value):
    with pytest.raises(UnsupportedEEError):
        _invoke(method, object=_feature({"value": value}), property="value")


def test_to_dictionary_excludes_system_keys_and_keeps_typed_ir_owned():
    nested = {"values": [1, 2]}
    static = StaticArray(np.array([3.0, 4.0]))
    source_image = Image(
        [("band", Pixel("constant", (5,)))], {"imageProp": "source"},
        Source("asset", ("image-1",), ("band",)),
    )
    feature = _feature({
        "plain": nested,
        "coefficients": static,
        "joined": source_image,
        "system:index": "row-1",
        "system:time_start": 123,
    })

    result = _invoke("Element.toDictionary", element=feature)
    assert set(result) == {"plain", "coefficients", "joined"}
    assert isinstance(result["coefficients"], StaticArray)
    assert result["coefficients"] is not static
    assert isinstance(result["joined"], Image)
    assert result["joined"] is not source_image
    assert result["joined"].source == source_image.source
    assert result["joined"].bands[0][1] is source_image.bands[0][1]
    result["plain"]["values"].append(9)
    assert nested["values"] == [1, 2]
    selected = _invoke(
        "Element.toDictionary", element=feature,
        properties=["system:index", "missing", "plain"],
    )
    assert selected == {"system:index": "row-1", "plain": {"values": [1, 2]}}


def test_collection_dictionary_reads_only_real_collection_metadata():
    row = _feature({"row": 2})
    collection = {
        "type": "FeatureCollection", "features": [row],
        "properties": {"title": "plots", "system:index": "not-a-row-id"},
    }
    result = _invoke("Element.toDictionary", element=collection)
    assert result == {"title": "plots"}
    assert result is not collection["properties"]


def test_replace_properties_preserves_feature_identity_and_rejects_conflicts():
    destination = _feature({"old": 1, "system:index": "feature-7"})
    source = _feature({"new": 2})
    result = _invoke(
        "Element.replaceProperties", destination=destination, source=source,
    )
    assert result["properties"] == {"new": 2}
    assert result["id"] == "feature-7"
    assert destination["properties"] == {"old": 1, "system:index": "feature-7"}
    conflict = _feature({"system:index": "other"})
    with pytest.raises(UnsupportedEEError, match="conflicts"):
        _invoke("Element.replaceProperties", destination=destination, source=conflict)


def test_replace_properties_preserves_image_source_and_clears_inherited_metadata():
    pixel = Pixel("constant", (1,))
    source = Source("asset", ("scene-1",), ("red",))
    destination = Image(
        [("red", pixel)], {"system:index": "scene-1", "old": "remove"}, source,
        inherit_props=True, copied_props=("legacy",),
    )
    cleared = _invoke("Element.replaceProperties", destination=destination)
    assert isinstance(cleared, Image)
    assert cleared.props == {"system:index": "scene-1"}
    assert cleared.source == source
    assert cleared.bands == [("red", pixel)]
    assert cleared.inherit_props is False
    assert cleared.copied_props == ()
    replaced = _invoke(
        "Element.replaceProperties", destination=destination,
        source=_feature({"system:index": "scene-1", "new": 3}),
    )
    assert replaced.props == {"system:index": "scene-1", "new": 3}
    assert destination.props["old"] == "remove"


@pytest.mark.parametrize("arguments", [
    {"element": {"type": "FeatureCollection", "features": []}, "unknown": 1},
    {"object": _feature({}), "property": "x", "defaultValue": 0},
    {"destination": _feature({}), "source": None, "ignored": True},
])
def test_invalid_arguments_are_rejected_even_for_empty_receivers(arguments):
    method = (
        "Element.toDictionary" if "element" in arguments else
        "Element.getNumber" if "object" in arguments else
        "Element.replaceProperties"
    )
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        _invoke(method, **arguments)


def test_empty_collection_and_invalid_receivers_are_explicit():
    empty = {"type": "FeatureCollection", "features": [], "properties": {}}
    assert _invoke("Element.toDictionary", element=empty) == {}
    mapped = Image([], {"known": 1}, mapped=True)
    assert _invoke("Element.getNumber", object=mapped, property="known") == 1
    with pytest.raises(UnsupportedEEError, match="mapped Image property"):
        _invoke("Element.getNumber", object=mapped, property="unknown")
    with pytest.raises(UnsupportedEEError, match="concrete Image"):
        _invoke("Element.toDictionary", element=object())


def test_cycle_and_output_budget_are_checked_before_copying():
    cyclic = {}
    cyclic["self"] = cyclic
    with pytest.raises(UnsupportedEEError, match="cycl"):
        _invoke("Element.toDictionary", element=_feature({"cycle": cyclic}))
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        _invoke("Element.toDictionary", element=_feature({"large": "x" * 1_000_001}))
    translator = _translator()
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_element_metadata_values(
            translator, "Element.toDictionary", {"element": _feature({"a": 1})},
        )


def test_array_scan_work_is_reserved_before_numpy_finiteness_scan(monkeypatch):
    translator = _translator()
    data = np.ones((3_000,), dtype=np.float64)
    original = np.isfinite
    scans = []

    def checked_finiteness(values):
        assert translator.steps >= values.size
        scans.append(values.size)
        return original(values)

    monkeypatch.setattr(np, "isfinite", checked_finiteness)
    result = invoke_element_metadata_values(
        translator, "Element.getArray",
        {"object": _feature({"array": StaticArray(data)}), "property": "array"},
    )
    assert result.data.size == 3_000
    assert scans


def test_array_scan_is_not_started_when_precharge_exceeds_budget(monkeypatch):
    translator = _translator()
    translator.steps = 47_000

    def uncharged_scan(_values):
        pytest.fail("array finiteness scan began before work reservation")

    monkeypatch.setattr(np, "isfinite", uncharged_scan)
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_element_metadata_values(
            translator, "Element.getArray",
            {"object": _feature({"array": StaticArray(np.ones(3_000))}),
             "property": "array"},
        )
