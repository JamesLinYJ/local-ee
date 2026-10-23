"""Pinned SDK serialization and bounded static String family behavior."""
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, UnsupportedEEError
from gee.compat.earthengine.string_values import (
    STRING_EXTRA_FUNCTIONS,
    invoke_string,
)
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


def test_pinned_sdk_serializes_the_added_string_operations(ee):
    calls = [
        ("String.equals", ee.String("left").equals("right"), {"reference", "target"}),
        ("String.index", ee.String("left").index("e"), {"target", "pattern"}),
        ("String.rindex", ee.String("left").rindex("e"), {"target", "pattern"}),
        ("String.slice", ee.String("left").slice(-2), {"string", "start"}),
        ("String.slice", ee.String("left").slice(1, 3), {"string", "start", "end"}),
        ("String.toLowerCase", ee.String("LEFT").toLowerCase(), {"string"}),
        ("String.toUpperCase", ee.String("left").toUpperCase(), {"string"}),
        ("String.trim", ee.String(" left ").trim(), {"string"}),
        ("String.encodeJSON", ee.String.encodeJSON({"x": [1]}), {"object"}),
        ("String.decodeJSON", ee.String('{"x":1}').decodeJSON(), {"string"}),
    ]
    for expected_name, value, expected_arguments in calls:
        expression = ee.serializer.encode(value, for_cloud_api=False)
        invocations = []

        def collect(item):
            if isinstance(item, dict):
                if item.get("type") == "Invocation":
                    invocations.append(item)
                else:
                    for child in item.values():
                        collect(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    collect(child)

        collect(expression)
        matching = [item for item in invocations if item["functionName"] == expected_name]
        assert matching
        assert set(matching[-1]["arguments"]) == expected_arguments
    assert STRING_EXTRA_FUNCTIONS == frozenset(name for name, _, _ in calls)


def test_equals_search_and_slice_use_codepoint_offsets_and_sdk_defaults(ee):
    assert output(ee, ee.String("x").equals("x")) is True
    assert output(ee, ee.String("x").equals("y")) is False
    assert output(ee, ee.String("1").equals(ee.Number(1))) is False
    text = ee.String("A😀baba")
    assert output(ee, text.index("😀b")) == 1
    assert output(ee, text.rindex("aba")) == 3
    assert output(ee, text.index("")) == 0
    assert output(ee, text.rindex("")) == 6
    assert output(ee, text.slice(-4, -1)) == "bab"
    assert output(ee, text.slice(3)) == "aba"
    assert output(ee, text.slice(100)) == ""


def test_case_conversion_expansion_trim_and_json_roundtrips(ee):
    assert output(ee, ee.String("Straße").toUpperCase()) == "STRASSE"
    assert output(ee, ee.String("İABC").toLowerCase()) == "i\u0307abc"
    assert output(ee, ee.String("\u00a0\t hello \u3000").trim()) == "hello"
    encoded = ee.String.encodeJSON({
        "unicode": "雪😀", "quote": '"\\', "integerFloat": 1.0,
        "small": 1e-6, "large": 1e21,
    })
    assert output(ee, encoded) == (
        '{"unicode":"雪😀","quote":"\\\"\\\\","integerFloat":1,'
        '"small":0.000001,"large":1e+21}'
    )
    decoded = ee.String('{ "é": [true, null, -0, 1e-6] }').decodeJSON()
    assert output(ee, decoded) == {"é": [True, None, 0, 1e-6]}


@pytest.mark.parametrize("name,arguments", [
    ("String.equals", {"reference": 1, "target": "1"}),
    ("String.index", {"target": "abc", "pattern": None}),
    ("String.rindex", {"target": "abc"}),
    ("String.slice", {"string": "abc", "start": True}),
    ("String.slice", {"string": "abc", "start": 0, "end": 1.5}),
    ("String.toLowerCase", {"string": None}),
    ("String.toUpperCase", {"string": []}),
    ("String.trim", {"string": "abc", "unexpected": 1}),
    ("String.encodeJSON", {}),
    ("String.encodeJSON", {"object": [], "unexpected": 1}),
    ("String.decodeJSON", {"string": 1}),
    ("String.decodeJSON", {}),
])
def test_string_family_rejects_bad_types_missing_and_unknown_arguments(name, arguments):
    with pytest.raises(UnsupportedEEError):
        invoke_string(Translator([], {}, None), name, arguments)


def test_search_precharges_linear_work_and_handles_overlapping_matches():
    translator = Translator([], {}, None)
    assert invoke_string(translator, "String.index", {
        "target": "abababa", "pattern": "ababa",
    }) == 0
    assert invoke_string(Translator([], {}, None), "String.rindex", {
        "target": "abababa", "pattern": "ababa",
    }) == 2
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_string(translator, "String.index", {
            "target": "a" * 25_001, "pattern": "a" * 25_001,
        })
    assert translator.steps == 0


def test_case_expansion_and_trim_are_charged_before_result_allocation():
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_string(translator, "String.toUpperCase", {"string": "ß" * 20_001})
    assert translator.steps == 20_001

    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_string(translator, "String.trim", {"string": " " * 50_001})
    assert translator.steps == 0


@pytest.mark.parametrize("text,match", [
    ('{"duplicate":1,"duplicate":2}', "duplicate"),
    ("NaN", "non-finite"),
    ("Infinity", "non-finite"),
    ("1e999", "finite"),
    ("9007199254740993", r"2\^53"),
    ("[" * 97 + "0" + "]" * 97, "depth"),
])
def test_decode_json_rejects_duplicates_nonfinite_unsafe_depth_and_invalid(text, match):
    with pytest.raises(UnsupportedEEError, match=match):
        invoke_string(Translator([], {}, None), "String.decodeJSON", {"string": text})


def test_decode_json_input_and_json_encoding_obey_work_and_cycle_guards():
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_string(translator, "String.decodeJSON", {"string": '"' + "x" * 25_000 + '"'})
    assert translator.steps == 0

    cycle = []
    cycle.append(cycle)
    with pytest.raises(UnsupportedEEError, match="cyclic"):
        invoke_string(Translator([], {}, None), "String.encodeJSON", {"object": cycle})

    with pytest.raises(UnsupportedEEError, match="finite JSON"):
        invoke_string(Translator([], {}, None), "String.encodeJSON", {
            "object": {"bad": Image([], {})},
        })


def test_json_serialization_preserves_input_ownership_and_bounds_expansion():
    value = {"control": "\x01", "nested": [1, True, None]}
    original = {"control": "\x01", "nested": [1, True, None]}
    encoded = invoke_string(Translator([], {}, None), "String.encodeJSON", {"object": value})
    assert encoded == '{"control":"\\u0001","nested":[1,true,null]}'
    assert value == original

    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_string(translator, "String.encodeJSON", {"object": "\x01" * 30_000})
    assert translator.steps <= 50_000
