"""Pinned SDK shapes and bounded RE2 semantics for static String regexes."""
import json
from pathlib import Path

import pytest
import re2

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.regex_values import (
    MAX_REGEX_PROGRAM_MEMORY,
    compile_pattern,
)
from gee.compat.earthengine.string_regex import (
    STRING_REGEX_FUNCTIONS,
    invoke_string_regex,
)
from gee.ee_python_client import configure_local_ee


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def _sdk_call(ee, expression):
    encoded = ee.serializer.encode(expression, for_cloud_api=False)
    assert encoded["type"] == "Invocation"
    return encoded["functionName"], encoded["arguments"]


def _sdk_value(ee, expression):
    name, arguments = _sdk_call(ee, expression)
    return invoke_string_regex(Translator([], {}, None), name, arguments)


def test_pinned_metadata_and_sdk_shapes_match_the_finite_entry_points(ee):
    metadata = json.loads((ROOT / "vendor/earthengine-js/algorithms.json").read_text())
    definitions = {
        item["name"].removeprefix("algorithms/"): item
        for item in metadata["algorithms"]
        if item["name"].removeprefix("algorithms/") in STRING_REGEX_FUNCTIONS
    }
    assert set(definitions) == STRING_REGEX_FUNCTIONS
    expected = {
        "String.match": ({"input", "regex", "flags"}, {"input", "regex"}, {"g", "i"}),
        "String.replace": ({"input", "regex", "replacement", "flags"},
                           {"input", "regex", "replacement"}, {"g", "i"}),
        "String.split": ({"string", "regex", "flags"}, {"string", "regex"}, {"i"}),
    }
    expressions = [
        ee.String("ab").match("a", "g"),
        ee.String("ab").replace("a", "x", "i"),
        ee.String("ab").split("a", "i"),
    ]
    for expression in expressions:
        name, arguments = _sdk_call(ee, expression)
        all_names, required_names, allowed_flags = expected[name]
        assert set(arguments) <= all_names
        assert required_names <= set(arguments)
        metadata_args = {item["argumentName"]: item for item in definitions[name]["arguments"]}
        assert set(metadata_args) == all_names
        assert metadata_args["flags"]["optional"] is True
        assert metadata_args["flags"]["defaultValue"] == ""
        assert allowed_flags <= set("gi")


def test_official_sdk_match_returns_full_matches_not_capture_groups(ee):
    text = ee.String("ABCabc123")
    assert _sdk_value(ee, text.match("ab", "ig")) == ["AB", "ab"]
    assert _sdk_value(ee, text.match("(abc)(123)")) == ["abc123"]
    assert _sdk_value(ee, text.match("z")) == []
    assert _sdk_value(ee, text.match("", "g")) == [""] * (len("ABCabc123") + 1)


def test_official_sdk_replace_flags_first_global_case_and_zero_width(ee):
    text = ee.String("abc-abc")
    assert _sdk_value(ee, text.replace("abc", "X")) == "X-abc"
    assert _sdk_value(ee, text.replace("abc", "X", "g")) == "X-X"
    assert _sdk_value(ee, ee.String("aBc-Abc").replace("abc", "Z", "ig")) == "Z-Z"
    assert _sdk_value(ee, ee.String("ab").replace("", "X", "g")) == "XaXbX"
    assert _sdk_value(ee, ee.String("abc").replace("z", "X")) == "abc"


def test_terminal_empty_match_is_deduplicated_but_empty_after_nonempty_is_kept():
    assert invoke_string_regex(Translator([], {}, None), "String.match", {
        "input": "ab", "regex": "$", "flags": "g",
    }) == [""]
    assert invoke_string_regex(Translator([], {}, None), "String.replace", {
        "input": "ab", "regex": "$", "replacement": "X", "flags": "g",
    }) == "abX"
    assert invoke_string_regex(Translator([], {}, None), "String.split", {
        "string": "ab", "regex": "$",
    }) == ["ab", ""]
    assert invoke_string_regex(Translator([], {}, None), "String.match", {
        "input": "a", "regex": "a*", "flags": "g",
    }) == ["a", ""]


def test_official_sdk_split_discards_capture_groups_and_splits_unicode(ee):
    assert _sdk_value(ee, ee.String("aBAbcD").split("(BA|c)")) == ["a", "b", "D"]
    assert _sdk_value(ee, ee.String("a,😀,b").split(",")) == ["a", "😀", "b"]
    assert _sdk_value(ee, ee.String("abc").split("")) == ["a", "b", "c"]
    assert _sdk_value(ee, ee.String("").split("")) == []
    assert _sdk_value(ee, ee.String("aBAbcD").split("ab", "i")) == ["", "", "cD"]


def test_unicode_case_fold_and_re2_unicode_classes():
    assert invoke_string_regex(Translator([], {}, None), "String.match", {
        "input": "ÄBCä", "regex": "ä", "flags": "ig",
    }) == ["Ä", "ä"]
    assert invoke_string_regex(Translator([], {}, None), "String.match", {
        "input": "xαβ 12", "regex": r"\p{Greek}+",
    }) == ["αβ"]


@pytest.mark.parametrize("pattern", [r"(?=a)", r"(a)\1", r"\C"])
def test_re2_subset_rejects_unsupported_or_byte_oriented_syntax(pattern):
    with pytest.raises(UnsupportedEEError, match="unsupported by RE2"):
        invoke_string_regex(Translator([], {}, None), "String.match", {
            "input": "aaa", "regex": pattern,
        })


@pytest.mark.parametrize("name,args", [
    ("String.match", {"input": "x", "regex": "x", "flags": "gg"}),
    ("String.match", {"input": "x", "regex": "x", "flags": "m"}),
    ("String.match", {"input": "x", "regex": "x", "flags": None}),
    ("String.replace", {"input": "x", "regex": "x", "replacement": "y", "flags": "ii"}),
    ("String.replace", {"input": "x", "regex": "x", "replacement": "y", "extra": 1}),
    ("String.replace", {"input": "x", "regex": "x"}),
    ("String.split", {"string": "x", "regex": "x", "flags": "g"}),
    ("String.split", {"string": "x", "regex": "x", "flags": "m"}),
    ("String.split", {"string": "x", "regex": None}),
])
def test_invalid_arguments_and_flags_fail_explicitly(name, args):
    with pytest.raises(UnsupportedEEError):
        invoke_string_regex(Translator([], {}, None), name, args)


@pytest.mark.parametrize("replacement", ["$1", r"\1", r"\g<name>"])
def test_ambiguous_replacement_expansions_are_rejected(replacement):
    with pytest.raises(UnsupportedEEError, match="literal replacement"):
        invoke_string_regex(Translator([], {}, None), "String.replace", {
            "input": "abc", "regex": "(a)(bc)", "replacement": replacement,
        })


@pytest.mark.parametrize("pattern,texts", [
    ("x", ("bad\ud800",)),
    ("bad\udfff", ("x",)),
    ("x", ["ok", 1]),
    ("x", "not-a-list"),
])
def test_shared_compiler_requires_bounded_utf8_subjects(pattern, texts):
    with pytest.raises(UnsupportedEEError):
        compile_pattern(Translator([], {}, None), pattern, texts)


def test_shared_compiler_uses_one_mib_re2_without_subject_retention():
    compiled = compile_pattern(Translator([], {}, None), r"\w+", ["abc", "雪"])
    assert compiled.fullmatch("abc")
    assert compiled.options.max_mem == MAX_REGEX_PROGRAM_MEMORY
    assert compiled.options.log_errors is False


def test_pattern_text_and_program_work_are_charged_before_scanning():
    translator = Translator([], {}, None)
    translator.steps = 49_990
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_string_regex(translator, "String.match", {
            "input": "abc", "regex": "a",
        })
    assert translator.steps <= 50_000

    too_long_pattern = "a" * 4_097
    with pytest.raises(UnsupportedEEError, match="4096-byte limit"):
        compile_pattern(Translator([], {}, None), too_long_pattern, [])


def test_replacement_expansion_is_reserved_before_scanning_or_joining():
    translator = Translator([], {}, None)
    replacement = "x" * 25_000
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_string_regex(translator, "String.replace", {
            "input": "a", "regex": "a", "replacement": replacement,
        })
    assert translator.steps <= 50_000

