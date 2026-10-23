"""Pinned SDK and finite semantics for static container filtering/selection."""
import json
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Filter, Image, UnsupportedEEError
from gee.compat.earthengine.static_container_selection import (
    STATIC_CONTAINER_SELECTION_FUNCTIONS,
    invoke_static_container_selection,
)
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


def _sdk_calls(value):
    calls = []

    def visit(node):
        if type(node) is dict:
            if node.get("type") == "Invocation":
                calls.append(node)
            for child in node.values():
                visit(child)
        elif type(node) in (list, tuple):
            for child in node:
                visit(child)

    visit(value)
    return calls


def _evaluate_with_owned_hook(ee, expression):
    """Decode the official SDK graph through the integrated static dispatcher."""
    encoded = ee.serializer.encode(expression, for_cloud_api=False)
    return Translator([], {}, None).evaluate(encoded)


def test_pinned_metadata_and_python_sdk_serialize_exact_signatures(ee):
    metadata = json.loads((ROOT / "vendor/earthengine-js/algorithms.json").read_text())
    definitions = {
        item["name"].removeprefix("algorithms/"): item
        for item in metadata["algorithms"]
        if item["name"].removeprefix("algorithms/") in STATIC_CONTAINER_SELECTION_FUNCTIONS
    }
    assert set(definitions) == STATIC_CONTAINER_SELECTION_FUNCTIONS
    for name in STATIC_CONTAINER_SELECTION_FUNCTIONS:
        arguments = definitions[name]["arguments"]
        names = {argument["argumentName"] for argument in arguments}
        if name == "List.filter":
            assert names == {"list", "filter"}
        else:
            assert names == {"dictionary", "selectors", "ignoreMissing"}
            optional = next(argument for argument in arguments
                            if argument["argumentName"] == "ignoreMissing")
            assert optional["optional"] is True and optional["defaultValue"] is False

    expressions = [
        ("List.filter", ee.List([1, 2]).filter(ee.Filter.eq("item", 2)), {"list", "filter"}),
        ("Dictionary.remove", ee.Dictionary({"a": 1}).remove(["a"]),
         {"dictionary", "selectors"}),
        ("Dictionary.select", ee.Dictionary({"a": 1}).select(["a"], True),
         {"dictionary", "selectors", "ignoreMissing"}),
    ]
    for name, expression, expected in expressions:
        encoded = ee.serializer.encode(expression, for_cloud_api=False)
        calls = [call for call in _sdk_calls(encoded) if call.get("functionName") == name]
        assert len(calls) == 1, name
        assert set(calls[0]["arguments"]) == expected, name


def test_sdk_list_filter_uses_the_canonical_filter_ir_and_static_equality(ee):
    greater = ee.List([None, 1, 2, 3, 2]).filter(ee.Filter.gt("item", 1))
    assert _evaluate_with_owned_hook(ee, greater) == [2, 3, 2]

    nested = ee.List([[1, "a"], [2], [1, "a"]]).filter(
        ee.Filter.eq("item", [1, "a"]),
    )
    assert _evaluate_with_owned_hook(ee, nested) == [[1, "a"], [1, "a"]]

    features = ee.List([
        ee.Feature(None, {"kind": "target", "nested": [1]}),
        ee.Feature(None, {"kind": "other", "nested": [2]}),
    ]).filter(ee.Filter.eq("kind", "target"))
    selected = _evaluate_with_owned_hook(ee, features)
    assert [item["properties"]["kind"] for item in selected] == ["target"]


def test_sdk_dictionary_select_remove_preserve_order_nulls_and_ownership(ee):
    source = {"keep": {"values": [1, 2]}, "null": None, "drop": [3]}
    before = json.loads(json.dumps(source))
    selected = _evaluate_with_owned_hook(
        ee, ee.Dictionary(source).select(["drop", "keep", "keep"]),
    )
    assert list(selected) == ["keep", "drop"]
    assert selected == {"keep": {"values": [1, 2]}, "drop": [3]}
    assert selected["keep"] is not source["keep"]
    assert selected["keep"]["values"] is not source["keep"]["values"]

    removed = _evaluate_with_owned_hook(ee, ee.Dictionary(source).remove(["drop"]))
    assert list(removed) == ["keep", "null"]
    assert removed == {"keep": {"values": [1, 2]}, "null": None}
    assert source == before


def test_dictionary_missing_selectors_and_regex_ambiguity(ee):
    dictionary = ee.Dictionary({"B1": 1, "B2": 2, "B[1-2]": 3, "other": None})
    assert _evaluate_with_owned_hook(ee, dictionary.select(["B1"])) == {"B1": 1}
    assert _evaluate_with_owned_hook(
        ee, dictionary.remove(["missing"], ignoreMissing=True),
    ) == {"B1": 1, "B2": 2, "B[1-2]": 3, "other": None}
    with pytest.raises(UnsupportedEEError, match="did not match"):
        _evaluate_with_owned_hook(ee, dictionary.select(["missing"]))
    # The literal-looking key cannot take precedence over the regex.
    assert _evaluate_with_owned_hook(ee, dictionary.select(["B[1-2]"])) == {"B1": 1, "B2": 2}
    assert _evaluate_with_owned_hook(ee, dictionary.select([r"B\[1-2\]"])) == {"B[1-2]": 3}
    assert _evaluate_with_owned_hook(ee, dictionary.remove(["B.*"])) == {"other": None}
    assert _evaluate_with_owned_hook(ee, dictionary.select(["B"], True)) == {}


@pytest.mark.parametrize("name,arguments", [
    ("List.filter", {"list": [1]}),
    ("List.filter", {"list": [1], "filter": {"name": "equals"}}),
    ("List.filter", {"list": [1], "filter": Filter("equals", {}), "other": 1}),
    ("List.filter", {"list": [Image([], {})], "filter": Filter("equals", {})}),
    ("Dictionary.select", {"dictionary": {"a": 1}, "selectors": [1]}),
    ("Dictionary.remove", {"dictionary": {"a": 1}, "selectors": ["a"], "ignoreMissing": 1}),
    ("Dictionary.select", {"dictionary": {"a": 1}, "selectors": ["a"], "extra": True}),
])
def test_dynamic_wrong_type_and_unknown_arguments_fail(name, arguments):
    with pytest.raises(UnsupportedEEError):
        invoke_static_container_selection(Translator([], {}, None), name, arguments)


def test_dictionary_regex_missing_and_work_budget_reject_before_unbounded_work():
    with pytest.raises(UnsupportedEEError):
        invoke_static_container_selection(Translator([], {}, None), "Dictionary.remove", {
            "dictionary": {}, "selectors": ["(?=a)"], "ignoreMissing": True,
        })
    over_budget = Translator([], {}, None)
    over_budget.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_static_container_selection(over_budget, "Dictionary.select", {
            "dictionary": {"a": [1]}, "selectors": ["a"],
        })


def test_list_filter_work_budget_and_owned_nested_copy():
    original = {"nested": {"values": [1, 2]}}
    result = invoke_static_container_selection(Translator([], {}, None), "List.filter", {
        "list": [original], "filter": Filter("equals", {
            "leftField": "item", "rightValue": original,
        }),
    })
    assert result == [original]
    assert result[0] is not original
    assert result[0]["nested"] is not original["nested"]
    assert result[0]["nested"]["values"] is not original["nested"]["values"]

    feature = {"type": "Feature", "geometry": None,
               "properties": {"kind": "keep", "nested": [1, 2]}}
    result = invoke_static_container_selection(Translator([], {}, None), "List.filter", {
        "list": [feature], "filter": Filter("equals", {
            "leftField": "kind", "rightValue": "keep",
        }),
    })
    assert result == [feature]
    assert result[0] is not feature
    assert result[0]["properties"] is not feature["properties"]
    assert result[0]["properties"]["nested"] is not feature["properties"]["nested"]

    over_budget = Translator([], {}, None)
    over_budget.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_static_container_selection(over_budget, "List.filter", {
            "list": [1], "filter": Filter("equals", {
                "leftField": "item", "rightValue": 1,
            }),
        })


@pytest.mark.parametrize("items,filt", [
    ([], Filter("calendarRange", {"start": 1, "field": []})),
    ([], Filter("calendarRange", {"start": 1, "field": {}})),
    ([], Filter("equals", {
        "leftField": "item", "rightValue": 1, "unexpected": True,
    })),
    ([], Filter("equals", {"leftField": "item"})),
    ([1], Filter("equals", {"leftField": "kind", "rightValue": "x"})),
    ([], Filter("unsupportedRegex", {})),
])
def test_list_filter_preflights_invalid_filter_even_without_a_matching_item(items, filt):
    with pytest.raises(UnsupportedEEError):
        invoke_static_container_selection(Translator([], {}, None), "List.filter", {
            "list": items, "filter": filt,
        })


def test_list_filter_preflights_invalid_nested_branch_before_short_circuit():
    filt = Filter("or", {"filters": [
        Filter("equals", {"leftField": "item", "rightValue": 1}),
        Filter("equals", {
            "leftField": "item", "rightValue": 2, "unexpected": True,
        }),
    ]})
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_static_container_selection(Translator([], {}, None), "List.filter", {
            "list": [1], "filter": filt,
        })
