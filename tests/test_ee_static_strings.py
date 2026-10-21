"""Pinned SDK String calls and bounded local static semantics."""
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.string_values import invoke_string
from gee.compat.earthengine.value_ops import invoke_value
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def output(ee, value):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, [], {})["value"]


def test_official_python_string_constructor_and_basic_methods(ee):
    assert output(ee, ee.String(ee.Number(42)).cat(" units")) == "42 units"
    assert output(ee, ee.String(ee.Number(1.5))) == "1.5"
    assert output(ee, ee.String("earth").cat(" engine").length()) == 12
    assert output(ee, ee.String("alpha").compareTo("alpha")) == 0
    assert output(ee, ee.String("alpha").compareTo("beta")) == -1
    assert output(ee, ee.String("gamma").compareTo("beta")) == 1


def test_sdk_string_methods_reject_wrong_serialized_types_and_unknown_params(ee):
    # The official typed method wrapper emits the declared String constructor
    # for a computed Number, which is a supported conversion path here.
    assert output(ee, ee.String("prefix").cat(ee.Number(4))) == "prefix4"

    wrong_type = {"type": "Invocation", "functionName": "String.cat",
                  "arguments": {"string1": "prefix", "string2": 4}}
    with pytest.raises(UnsupportedEEError, match="must be a string"):
        compile_expression(wrong_type, [], {})

    unknown = ee.serializer.encode(ee.String("left").cat("right"), for_cloud_api=False)
    unknown["arguments"]["unexpected"] = "value"
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(unknown, [], {})


def test_string_constructor_restricts_conversion_to_strings_and_finite_numbers(ee):
    expression = {"type": "Invocation", "functionName": "String",
                  "arguments": {"input": {"type": "Dictionary", "value": {"x": 1}}}}
    with pytest.raises(UnsupportedEEError, match="only static strings and finite numbers"):
        compile_expression(expression, [], {})

    for value in (True, None, float("inf"), float("nan")):
        with pytest.raises(UnsupportedEEError):
            invoke_value(Translator([], {}, None), "String", {"input": value})

    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_value(Translator([], {}, None), "String", {"input": "a", "value": "b"})
    with pytest.raises(UnsupportedEEError, match="requires input"):
        invoke_value(Translator([], {}, None), "String", {})


@pytest.mark.parametrize("name,arguments", [
    ("String.cat", {"string1": "x", "string2": 1}),
    ("String.length", {"string": None}),
    ("String.compareTo", {"string1": "x", "string2": []}),
    ("String.cat", {"string1": "x"}),
])
def test_static_string_methods_reject_type_and_missing_argument_errors(name, arguments):
    with pytest.raises(UnsupportedEEError):
        Translator([], {}, None).static(name, arguments)


def test_string_work_is_charged_before_cat_and_comparison(ee):
    translator = Translator([], {}, None)
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_string(translator, "String.cat", {"string1": "x", "string2": "y"})
    assert translator.steps == 49_999

    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_string(translator, "String.cat", {"string1": "x" * 50_001, "string2": ""})
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_string(translator, "String.compareTo", {
            "string1": "x" * 50_001, "string2": "x" * 50_001,
        })

    # Only 15 small iterate steps are needed to cross the budget: materialized
    # results stay at or below 16,384 characters before the next cat rejects.
    doubling = ee.List([0] * 15).iterate(
        lambda _item, previous: ee.String(previous).cat(ee.String(previous)), "x"
    )
    with pytest.raises(UnsupportedEEError, match="shared string work budget"):
        output(ee, doubling)


def test_string_unicode_policy_is_codepoint_based_and_unverified_for_google():
    translator = Translator([], {}, None)
    assert invoke_string(translator, "String.length", {"string": "😀"}) == 1
    # Python code-point order places U+10000 after U+E000. A UTF-16 code-unit
    # comparison would order the surrogate pair before U+E000; Google behavior
    # is unverified, as stated in string_values.py.
    assert invoke_string(Translator([], {}, None), "String.compareTo", {
        "string1": "\U00010000", "string2": "\ue000",
    }) == 1
