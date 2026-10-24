"""Empty collections validate callback structure without invented sample rows."""
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.feature_map_preflight import preflight_empty_feature_map
from gee.compat.earthengine.ir import Function, UnsupportedEEError


def function(body):
    return Function(["row"], body, {})


def test_unknown_algorithm_in_empty_callback_rejects_instead_of_fake_success():
    body = {"type": "Invocation", "functionName": "Feature.area",
            "arguments": {"feature": {"type": "ArgumentRef", "value": "row"}}}
    with pytest.raises(UnsupportedEEError, match="Unsupported.*empty Feature map"):
        preflight_empty_feature_map(Translator([], {}, {}), function(body))


def test_preparation_argument_schema_rejects_unknown_keys_without_evaluating_row():
    body = {"type": "Invocation", "functionName": "Feature.setGeometry",
            "arguments": {"feature": {"type": "ArgumentRef", "value": "row"},
                          "unexpected": True}}
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        preflight_empty_feature_map(Translator([], {}, {}), function(body))


def test_diamond_references_are_bounded_and_never_evaluate_callback(monkeypatch):
    translator = Translator([], {}, {})
    translator.scope["number"] = {
        "type": "Invocation", "functionName": "Element.getNumber",
        "arguments": {"object": {"type": "ArgumentRef", "value": "row"},
                      "property": "not_present_on_any_actual_row"},
    }
    body = [{"type": "ValueRef", "value": "number"}] * 1000

    def unexpected(*_args, **_kwargs):
        raise AssertionError("empty callback invented or evaluated a row")

    monkeypatch.setattr(translator, "evaluate", unexpected)
    preflight_empty_feature_map(translator, function(body))
    assert 1000 < translator.steps < 5000


def test_scope_and_container_cycles_reject_and_budget_precedes_large_scan():
    translator = Translator([], {}, {})
    translator.scope["cycle"] = {"type": "ValueRef", "value": "cycle"}
    with pytest.raises(UnsupportedEEError, match="cycle"):
        preflight_empty_feature_map(translator, function(translator.scope["cycle"]))
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(UnsupportedEEError, match="cycle"):
        preflight_empty_feature_map(Translator([], {}, {}), function(cyclic))
    translator = Translator([], {}, {})
    translator.steps = 49999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        preflight_empty_feature_map(translator, function([None] * 1000))


def test_instruction_looking_dictionary_fields_are_only_property_values():
    body = {"type": "Dictionary", "value": {
        "functionName": "Feature.area", "arguments": {"ignored": 1},
        "type": "Invocation",
    }}
    preflight_empty_feature_map(Translator([], {}, {}), function(body))


def test_compound_scope_unknown_refs_and_missing_required_arguments_reject():
    translator = Translator([], {}, {})
    body = {"type": "Invocation", "functionName": "Feature.toArray", "arguments": {}}
    with pytest.raises(UnsupportedEEError, match="missing required"):
        preflight_empty_feature_map(translator, function(body))
    with pytest.raises(UnsupportedEEError, match="unknown value reference"):
        preflight_empty_feature_map(Translator([], {}, {}), function({"type": "ValueRef", "value": "absent"}))
    body = {"type": "CompoundValue", "scope": [["x", 1], ["x", 2]], "value": 1}
    with pytest.raises(UnsupportedEEError, match="scope reference"):
        preflight_empty_feature_map(Translator([], {}, {}), function(body))
