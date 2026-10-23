"""Finite static Number.parse and pinned SDK serialization checks."""
import json
import math
from pathlib import Path
import shutil
import subprocess

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine import number_parse
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression


ROOT = Path(__file__).resolve().parents[1]
_OMITTED = object()


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def invoke(input_value, radix=_OMITTED, *, translator=None):
    arguments = {"input": input_value}
    if radix is not _OMITTED:
        arguments["radix"] = radix
    return number_parse.invoke_number_parse(
        translator or Translator([], {}, {}), "Number.parse", arguments,
    )


@pytest.mark.parametrize(("text", "radix", "expected"), [
    ("42", _OMITTED, 42.0), ("  -42  ", None, -42.0),
    ("1.25", 10, 1.25), (".5", 10, 0.5), ("1.", 10, 1.0),
    ("1.25e2", _OMITTED, 125.0), ("1e-3", _OMITTED, 0.001),
    ("1e-1000000", 10, 0.0),
    ("ff", 16, 255.0), ("-1010", 2, -10.0), ("Z", 36, 35.0),
    ("9007199254740992", 10, float(2**53)),
])
def test_bounded_decimal_and_radix_forms(text, radix, expected):
    actual = invoke(text, radix)
    assert actual == pytest.approx(expected)


def test_maximum_length_integer_is_processed_without_large_integer_conversion():
    text = "0" * (number_parse.MAX_PARSE_INPUT_CHARS - 1) + "1"
    assert invoke(text, 10) == 1.0
    decimal_text = "0." + "1" * (number_parse.MAX_PARSE_INPUT_CHARS - 2)
    assert invoke(decimal_text, 10) == float(decimal_text)


def test_negative_zero_is_preserved_for_decimal_and_radix_forms():
    for text, radix in (("-0.0", 10), ("-0", 2)):
        value = invoke(text, radix)
        assert value == 0.0
        assert math.copysign(1.0, value) == -1.0


@pytest.mark.parametrize("text,radix", [
    ("9007199254740993", 10), ("20000000000001", 16),
    ("9007199254740992.1", 10), ("NaN", 10), ("Infinity", 10),
    ("1e9999", 10), ("1e1000000", 10), ("0x10", 10), ("1.5", 16), ("+", 10),
    (".", 10), ("1e", 10), ("1__0", 10), ("1\u0662", 10),
])
def test_invalid_or_unsafe_values_reject(text, radix):
    with pytest.raises(UnsupportedEEError):
        invoke(text, radix)


@pytest.mark.parametrize("value", [
    None, True, 42, 1.5, [], {}, float("nan"),
])
def test_input_must_be_a_static_string(value):
    with pytest.raises(UnsupportedEEError):
        invoke(value)


@pytest.mark.parametrize("radix", [True, False, "16", 1, 37, 2.5, float("nan"), 1e300])
def test_radix_must_be_a_bounded_exact_integer(radix):
    with pytest.raises(UnsupportedEEError):
        invoke("12", radix)


def test_unknown_or_missing_arguments_reject():
    translator = Translator([], {}, {})
    with pytest.raises(UnsupportedEEError):
        number_parse.invoke_number_parse(translator, "Number.parse", {})
    with pytest.raises(UnsupportedEEError):
        number_parse.invoke_number_parse(
            translator, "Number.parse", {"input": "1", "locale": "en"},
        )


def test_input_and_work_limits_are_checked_before_parsing(monkeypatch):
    translator = Translator([], {}, {})
    translator.steps = 50_000

    def should_not_parse(*_args):
        raise AssertionError("decimal parser ran before work preflight")

    monkeypatch.setattr(number_parse, "_decimal", should_not_parse)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke("1.25", 10, translator=translator)
    assert translator.steps == 50_000

    long_input = "0" * (number_parse.MAX_PARSE_INPUT_CHARS + 1)
    translator.steps = 0
    with pytest.raises(UnsupportedEEError, match="characters"):
        invoke(long_input, translator=translator)
    assert translator.steps == 0


def test_pinned_sdk_signature_and_python_wire_defaults(ee):
    algorithms = json.loads((ROOT / "vendor/earthengine-js/algorithms.json").read_text())[
        "algorithms"
    ]
    signature = next(item for item in algorithms if item["name"] == "algorithms/Number.parse")
    input_arg, radix_arg = signature["arguments"]
    assert (input_arg["argumentName"], input_arg["type"]) == ("input", "String")
    assert (radix_arg["argumentName"], radix_arg["type"]) == ("radix", "Integer")
    assert radix_arg["optional"] is True
    assert radix_arg["defaultValue"] == 10.0
    assert "must equal 10 or not be specified" in radix_arg["description"]

    expected = [
        {"type": "Invocation", "arguments": {"input": "42"}, "functionName": "Number.parse"},
        {"type": "Invocation", "arguments": {"input": "42"}, "functionName": "Number.parse"},
        {"type": "Invocation", "arguments": {"input": "ff", "radix": 16},
         "functionName": "Number.parse"},
    ]
    actual = [
        ee.serializer.encode(ee.Number.parse("42"), for_cloud_api=False),
        ee.serializer.encode(ee.Number.parse("42", None), for_cloud_api=False),
        ee.serializer.encode(ee.Number.parse("ff", 16), for_cloud_api=False),
    ]
    assert actual == expected


def _compiled_sdk_parse(ee, text, radix=_OMITTED):
    value = ee.Number.parse(text) if radix is _OMITTED else ee.Number.parse(text, radix)
    encoded = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(encoded, [], {})


@pytest.mark.parametrize(("text", "radix", "expected"), [
    ("42", _OMITTED, 42.0), ("1.25", 10, 1.25), ("ff", 16, 255.0),
    ("9007199254740992", 10, float(2**53)),
])
def test_pinned_python_sdk_parse_compiles_to_finite_values(ee, text, radix, expected):
    result = _compiled_sdk_parse(ee, text, radix)
    assert result["kind"] == "value"
    assert result["value"] == pytest.approx(expected)


@pytest.mark.parametrize(("text", "radix"), [
    ("not-a-number", _OMITTED), ("1e1000000", 10),
    ("9007199254740993", 10), ("1.5", 16),
])
def test_pinned_python_sdk_parse_compiler_rejects_invalid_and_unsafe_values(ee, text, radix):
    with pytest.raises(UnsupportedEEError):
        _compiled_sdk_parse(ee, text, radix)


def test_pinned_javascript_sdk_radix_serialization():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the pinned JavaScript SDK serializer check")
    script = r"""
const fs = require('node:fs');
global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs');
const raw = JSON.parse(fs.readFileSync('vendor/earthengine-js/algorithms.json')).algorithms;
const signatures = Object.fromEntries(raw.map(a => [a.name.replace(/^algorithms\//, ''), {
  description: a.description, returns: a.returnType,
  args: (a.arguments || []).map(x => ({name: x.argumentName, type: x.type,
    optional: !!x.optional, ...('defaultValue' in x ? {default: x.defaultValue} : {})}))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
const encoded = [
  ee.Serializer.encode(ee.Number.parse('42')),
  ee.Serializer.encode(ee.Number.parse('42', null)),
  ee.Serializer.encode(ee.Number.parse('ff', 16))
];
console.log(JSON.stringify(encoded));
"""
    result = subprocess.run(
        [node, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        {"type": "Invocation", "arguments": {"input": "42"}, "functionName": "Number.parse"},
        {"type": "Invocation", "arguments": {"input": "42", "radix": None},
         "functionName": "Number.parse"},
        {"type": "Invocation", "arguments": {"input": "ff", "radix": 16},
         "functionName": "Number.parse"},
    ]
