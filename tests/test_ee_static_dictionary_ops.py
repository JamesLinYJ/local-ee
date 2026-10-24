"""Pinned SDK construction and bounded static Dictionary semantics."""
import copy
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_core import StaticArray
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_values import GeometryValue
from gee.compat.earthengine.ir import Function, Image, UnsupportedEEError
from gee.compat.earthengine.static_dictionary_ops import invoke_dictionary_extra
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def compile_value(ee, expression):
    encoded = ee.serializer.encode(expression, for_cloud_api=False)
    result = compile_expression(encoded, [], {})
    assert result["kind"] == "value"
    return result["value"]


def invocation(name, **arguments):
    return {"type": "Invocation", "functionName": name, "arguments": arguments}


def sdk_invocations(value):
    found = []

    def visit(node):
        if type(node) is dict:
            if node.get("type") == "Invocation":
                found.append(node)
            for child in node.values():
                visit(child)
        elif type(node) in (list, tuple):
            for child in node:
                visit(child)

    visit(value)
    return found


def test_pinned_sdk_serializes_each_supported_extra_signature(ee):
    dictionary = ee.Dictionary({"a": 1})
    expressions = [
        ("Dictionary.combine", dictionary.combine({"b": 2}), {"first", "second"}),
        ("Dictionary.fromLists", ee.Dictionary.fromLists(["a"], [1]), {"keys", "values"}),
        ("Dictionary.rename", dictionary.rename(["a"], ["b"]), {"dictionary", "from", "to"}),
        ("Dictionary.size", dictionary.size(), {"dictionary"}),
        ("Dictionary.map", dictionary.map(lambda key, value: ee.Number(value).add(1)),
         {"dictionary", "baseAlgorithm"}),
        ("Dictionary.toArray", dictionary.toArray(), {"dictionary"}),
        ("Dictionary.getNumber", dictionary.getNumber("a"), {"dictionary", "key"}),
        ("Dictionary.getString", ee.Dictionary({"a": "x"}).getString("a"),
         {"dictionary", "key"}),
        ("Dictionary.getArray", ee.Dictionary({"a": ee.Array([1])}).getArray("a"),
         {"dictionary", "key"}),
        ("Dictionary.getGeometry", ee.Dictionary({"a": ee.Geometry.Point([1, 2])}).getGeometry("a"),
         {"dictionary", "key"}),
    ]
    for name, expression, expected_arguments in expressions:
        calls = [call for call in sdk_invocations(
            ee.serializer.encode(expression, for_cloud_api=False)
        ) if call.get("functionName") == name]
        assert len(calls) == 1, name
        assert set(calls[0]["arguments"]) == expected_arguments


def test_sdk_merge_and_from_lists_match_independent_expected_values(ee):
    first = {"keep": 1, "same": 2, "nullOnly": None, "nested": {"items": [1, 2]}}
    second = {"same": 7, "added": 9, "nullOnly": 3, "ignored": None}
    original_first, original_second = copy.deepcopy(first), copy.deepcopy(second)
    actual = compile_value(ee, ee.Dictionary(first).combine(second))
    assert actual == {"keep": 1, "same": 7, "nested": {"items": [1, 2]},
                      "nullOnly": 3, "added": 9}
    assert first == original_first and second == original_second
    assert actual["nested"] is not first["nested"]
    assert actual["nested"]["items"] is not first["nested"]["items"]

    keep_first = compile_value(ee, ee.Dictionary({"same": 2}).combine({"same": 7}, False))
    assert keep_first == {"same": 2}
    null_overlay = compile_value(ee, ee.Dictionary({"same": 2}).combine({"same": None}))
    assert null_overlay == {"same": 2}
    # Duplicate list keys use this adapter's explicit last-value-wins policy.
    from_lists = compile_value(ee, ee.Dictionary.fromLists(["x", "y", "x"], [1, 2, 3]))
    assert from_lists == {"x": 3, "y": 2}
    assert compile_value(ee, ee.Dictionary.fromLists(["x"], [None])) == {"x": None}


def test_sdk_empty_dictionary_operations_are_finite(ee):
    empty = ee.Dictionary({})
    assert compile_value(ee, empty.combine({})) == {}
    assert compile_value(ee, ee.Dictionary.fromLists([], [])) == {}
    assert compile_value(ee, empty.rename([], [])) == {}
    assert compile_value(ee, empty.size()) == 0
    assert compile_value(ee, empty.map(lambda key, value: value)) == {}
    assert compile_value(ee, empty.toArray()) == []


def test_sdk_rename_and_size_match_independent_expected_values(ee):
    source = {"old": {"v": [4]}, "stay": 8}
    before = copy.deepcopy(source)
    actual = compile_value(ee, ee.Dictionary(source).rename(["old"], ["new"]))
    assert actual == {"stay": 8, "new": {"v": [4]}}
    assert actual["new"] is not source["old"]
    assert source == before
    overwritten = compile_value(
        ee, ee.Dictionary({"old": 1, "new": 2}).rename(["old"], ["new"], True),
    )
    assert overwritten == {"new": 1}
    assert compile_value(ee, ee.Dictionary(source).size()) == 2


def test_sdk_map_computes_values_and_drops_nulls(ee):
    doubled = ee.Dictionary({"a": 1, "b": 4}).map(
        lambda key, value: ee.Number(value).multiply(2)
    )
    assert compile_value(ee, doubled) == {"a": 2, "b": 8}
    removed = ee.Dictionary({"a": 1, "b": 4}).map(
        lambda key, value: ee.Algorithms.If(ee.Number(1).eq(1), None, value)
    )
    assert compile_value(ee, removed) == {}


def test_sdk_to_array_defaults_keys_and_honors_array_axis(ee):
    scalar_values = ee.Dictionary({"z": 9, "a": 1, "m": 5})
    assert compile_value(ee, scalar_values.toArray()) == [1, 5, 9]
    arrays = ee.Dictionary({
        "left": ee.Array([1, 2]), "right": ee.Array([10, 20]),
    })
    assert compile_value(ee, arrays.toArray(["left", "right"], 0)) == [[1, 2], [10, 20]]
    assert compile_value(ee, arrays.toArray(["left", "right"], 1)) == [[1, 10], [2, 20]]
    with pytest.raises(UnsupportedEEError, match="axis"):
        compile_value(ee, arrays.toArray(["left", "right"], -1))


def test_sdk_typed_getters_preserve_number_string_array_and_geometry(ee):
    dictionary = ee.Dictionary({
        "n": 12, "s": "green", "a": ee.Array([[1, 2], [3, 4]]),
        "g": ee.Geometry.Point([1, 2]),
    })
    assert compile_value(ee, dictionary.getNumber("n")) == 12
    assert compile_value(ee, dictionary.getString("s")) == "green"
    assert compile_value(ee, dictionary.getArray("a")) == [[1, 2], [3, 4]]
    assert compile_value(ee, dictionary.getGeometry("g")) == {
        "type": "Point", "coordinates": [1, 2],
    }


def test_dictionary_geometry_values_keep_exact_type_and_sidecars_in_owned_copies():
    geometry = GeometryValue(
        {"type": "Point", "coordinates": [1, 2]},
        {"geodesic": False}, validated=True,
    )
    source = {"g": geometry, "nested": {"g": geometry}}
    combined = invoke_dictionary_extra(
        Translator([], {}, None), "Dictionary.combine",
        {"first": source, "second": {}},
    )
    owned = combined["g"]
    assert type(owned) is GeometryValue
    assert owned is not geometry
    assert owned.geometry_metadata == {"geodesic": False}
    assert owned.geometry_metadata is not geometry.geometry_metadata
    assert combined["nested"]["g"] is not geometry

    result = invoke_dictionary_extra(
        Translator([], {}, None), "Dictionary.getGeometry",
        {"dictionary": source, "key": "g"},
    )
    assert type(result) is GeometryValue
    assert result == geometry
    assert result.geometry_metadata == {"geodesic": False}
    result["coordinates"][0] = 99
    assert geometry["coordinates"] == [1, 2]


def test_dictionary_static_values_reject_unknown_dict_subclasses_and_mutated_geometry():
    class ForeignGeometry(dict):
        pass

    with pytest.raises(UnsupportedEEError, match="ForeignGeometry"):
        invoke_dictionary_extra(
            Translator([], {}, None), "Dictionary.size",
            {"dictionary": {"g": ForeignGeometry({
                "type": "Point", "coordinates": [1, 2],
            })}},
        )

    geometry = GeometryValue(
        {"type": "Point", "coordinates": [1, 2]}, validated=True,
    )
    geometry["coordinates"][0] = 181
    with pytest.raises(UnsupportedEEError, match="coordinates"):
        invoke_dictionary_extra(
            Translator([], {}, None), "Dictionary.getGeometry",
            {"dictionary": {"g": geometry}, "key": "g"},
        )

    flagged = GeometryValue(
        {"type": "Point", "coordinates": [1, 2]}, validated=True,
    )
    flagged.geometry_metadata["geodesic"] = True
    with pytest.raises(UnsupportedEEError, match="spherical"):
        invoke_dictionary_extra(
            Translator([], {}, None), "Dictionary.getGeometry",
            {"dictionary": {"g": flagged}, "key": "g"},
        )


@pytest.mark.parametrize("arguments", [
    {"first": {"a": 1}},
    {"first": {"a": 1}, "second": {"b": 2}, "ignored": True},
    {"first": {"a": 1}, "second": {"b": 2}, "overwrite": 1},
])
def test_invalid_combine_arguments_fail_explicitly(arguments):
    with pytest.raises(UnsupportedEEError):
        compile_expression(invocation("Dictionary.combine", **arguments), [], {})


@pytest.mark.parametrize("name,args", [
    ("Dictionary.fromLists", {"keys": ["a"], "values": [1, 2]}),
    ("Dictionary.fromLists", {"keys": ["a", 1], "values": [1, 2]}),
    ("Dictionary.rename", {"dictionary": {"a": 1}, "from": ["a"], "to": []}),
    ("Dictionary.rename", {"dictionary": {"a": 1}, "from": ["missing"], "to": ["b"]}),
    ("Dictionary.rename", {"dictionary": {"a": 1, "b": 2}, "from": ["a"], "to": ["b"]}),
    ("Dictionary.rename", {"dictionary": {"a": 1}, "from": ["a", "a"], "to": ["b", "c"]}),
    ("Dictionary.rename", {"dictionary": {"a": 1, "b": 2}, "from": ["a", "b"], "to": ["c", "c"]}),
    ("Dictionary.getNumber", {"dictionary": {"a": "1"}, "key": "a"}),
    ("Dictionary.getString", {"dictionary": {"a": 1}, "key": "a"}),
    ("Dictionary.getArray", {"dictionary": {"a": [1, 2]}, "key": "a"}),
    ("Dictionary.getGeometry", {"dictionary": {"a": {"type": "Point", "coordinates": [1, 2]}}, "key": "missing"}),
    ("Dictionary.toArray", {"dictionary": {"a": 1}, "keys": ["missing"]}),
    ("Dictionary.toArray", {"dictionary": {"a": 1}, "axis": True}),
    ("Dictionary.select", {"dictionary": {"a": 1}, "selectors": ["(?=a)"]}),
    ("Dictionary.remove", {"dictionary": {"a": 1}, "selectors": [r"(a)\1"]}),
])
def test_invalid_types_conflicts_and_regex_selectors_fail(name, args):
    with pytest.raises(UnsupportedEEError):
        compile_expression(invocation(name, **args), [], {})


def test_cycles_opaque_models_input_ownership_and_work_budget():
    translator = Translator([], {}, {})
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(UnsupportedEEError, match="cycles"):
        invoke_dictionary_extra(translator, "Dictionary.size", {"dictionary": {"x": cyclic}})

    with pytest.raises(UnsupportedEEError, match="Image"):
        invoke_dictionary_extra(translator, "Dictionary.size", {
            "dictionary": {"opaque": Image([], {})},
        })

    array = StaticArray(np.asarray([[1, 2], [3, 4]], dtype=np.int64))
    original = {"a": {"array": array, "list": [1, 2]}}
    merged = invoke_dictionary_extra(
        translator, "Dictionary.combine", {"first": original, "second": {"b": 3}},
    )
    assert merged["a"]["array"] is not array
    assert merged["a"]["array"].data.shape == (2, 2)
    assert not merged["a"]["array"].data.flags.writeable
    assert merged["a"]["list"] is not original["a"]["list"]
    assert array.data.flags.writeable  # Input ownership and mutability stay with caller.

    near_limit = Translator([], {}, {})
    near_limit.steps = 49_999
    before = {"x": [1, 2]}
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_dictionary_extra(near_limit, "Dictionary.combine", {
            "first": before, "second": {"y": 3},
        })
    assert before == {"x": [1, 2]}


def test_array_accessor_accepts_cell_limit_and_rejects_one_over():
    source = StaticArray(np.zeros(10_000, dtype=np.float64))
    result = invoke_dictionary_extra(Translator([], {}, {}), "Dictionary.getArray", {
        "dictionary": {"a": source}, "key": "a",
    })
    assert result.data.shape == (10_000,)
    assert result is not source and result.data is not source.data
    too_large = StaticArray(np.zeros(10_001, dtype=np.float64))
    with pytest.raises(UnsupportedEEError, match="10000"):
        invoke_dictionary_extra(Translator([], {}, {}), "Dictionary.getArray", {
            "dictionary": {"a": too_large}, "key": "a",
        })


def test_static_map_rejects_wrong_callback_arity_and_nonstatic_values():
    translator = Translator([], {}, {})
    with pytest.raises(UnsupportedEEError, match="two-argument"):
        invoke_dictionary_extra(translator, "Dictionary.map", {
            "dictionary": {"a": 1}, "baseAlgorithm": Function(["value"], 1, {}),
        })
    with pytest.raises(UnsupportedEEError, match="Image"):
        invoke_dictionary_extra(translator, "Dictionary.map", {
            "dictionary": {"a": 1}, "baseAlgorithm": Function(
                ["key", "value"], Image([], {}), {},
            ),
        })
