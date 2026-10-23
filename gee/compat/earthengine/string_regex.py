"""Finite ``String.match``, ``String.replace`` and ``String.split`` semantics.

Matching is performed by the shared bounded RE2 adapter. Local replacement
strings are literal text only: dollar/backslash replacement escapes are
rejected because the pinned Earth Engine docs do not define their expansion
rules. Regex capture groups are intentionally omitted from match/split output,
matching the documented list-of-matched-strings and split examples.
"""
from __future__ import annotations

import re2

from .ir import fail
from .regex_values import (
    MAX_REGEX_OUTPUT_ITEMS,
    charge_output,
    compile_pattern,
    measure_utf8,
)


STRING_REGEX_FUNCTIONS = frozenset({
    "String.match", "String.replace", "String.split",
})


_ARGUMENTS = {
    "String.match": ({"input", "regex"}, {"flags"}),
    "String.replace": ({"input", "regex", "replacement"}, {"flags"}),
    "String.split": ({"string", "regex"}, {"flags"}),
}


def _arguments(translator, name, arguments):
    required, optional = _ARGUMENTS[name]
    translator.allowed(arguments, required | optional)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def _string(value, label):
    if type(value) is not str:
        fail(f"{label} must be a string")
    return value


def _flags(value, name):
    if type(value) is not str:
        fail(f"{name} flags must be a string")
    allowed = "i" if name == "String.split" else "gi"
    if len(value) > len(allowed):
        expected = "i" if name == "String.split" else "g and/or i"
        fail(f"{name} flags must contain unique supported flags ({expected})")
    if any(flag not in allowed for flag in value) or len(set(value)) != len(value):
        expected = "i" if name == "String.split" else "g and/or i"
        fail(f"{name} flags must contain unique supported flags ({expected})")
    return "g" in value, "i" in value


def _collect_spans(translator, compiled, text, *, global_match, label):
    """Collect bounded full-match spans; offset-list growth is charged first."""
    spans = []
    try:
        matches = compiled.finditer(text) if global_match else (compiled.search(text),)
        for match in matches:
            if match is None:
                break
            span = match.span(0)
            # google-re2 1.1.20251105 can yield the terminal zero-width span
            # twice for patterns such as '$'. Keep distinct adjacent empties,
            # including an empty span after a nonempty terminal match.
            if spans and span == spans[-1]:
                continue
            if len(spans) >= MAX_REGEX_OUTPUT_ITEMS:
                fail(f"{label} exceeds 10000 output items")
            charge_output(translator, 1, 0, label + " match offsets")
            spans.append(span)
    except re2.error:
        # Preserve the compatibility error type without switching to another
        # regex implementation if the binding fails while scanning.
        fail(f"{label} failed in the bounded RE2 matcher")
    return spans


def _match(translator, arguments):
    name = "String.match"
    _arguments(translator, name, arguments)
    text = _string(arguments["input"], name + " input")
    regex = _string(arguments["regex"], name + " regex")
    global_match, ignore_case = _flags(arguments.get("flags", ""), name)
    text_bytes = measure_utf8(translator, text, name + " input")
    compiled = compile_pattern(translator, regex, (text,), ignore_case)

    # Full-match substrings are non-overlapping, so their aggregate size is
    # bounded by the subject. Reserve that output before RE2 scans it.
    charge_output(translator, len(text), text_bytes, name)
    charge_output(translator, 1, 0, name + " result list")
    spans = _collect_spans(
        translator, compiled, text, global_match=global_match, label=name,
    )
    charge_output(translator, len(spans), 0, name + " result items")
    return [text[start:end] for start, end in spans]


def _replace(translator, arguments):
    name = "String.replace"
    _arguments(translator, name, arguments)
    text = _string(arguments["input"], name + " input")
    regex = _string(arguments["regex"], name + " regex")
    replacement = _string(arguments["replacement"], name + " replacement")
    text_bytes = measure_utf8(translator, text, name + " input")
    replacement_bytes = measure_utf8(translator, replacement, name + " replacement")
    if "$" in replacement or "\\" in replacement:
        fail("String.replace supports literal replacement text only; '$' and backslash escapes are unsupported")
    global_match, ignore_case = _flags(arguments.get("flags", ""), name)
    compiled = compile_pattern(translator, regex, (text,), ignore_case)

    max_matches = len(text) + 1 if global_match else 1
    output_chars = len(text) + max_matches * len(replacement)
    output_bytes = text_bytes + max_matches * replacement_bytes
    # This deliberate worst-case reservation bounds global zero-width matches
    # and replacement expansion before scanning or building the result.
    charge_output(translator, output_chars, output_bytes, name)
    spans = _collect_spans(
        translator, compiled, text, global_match=global_match, label=name,
    )
    chunk_count = 2 * len(spans) + 1
    charge_output(translator, chunk_count, 0, name + " output chunks")
    if not spans:
        return text
    chunks = []
    cursor = 0
    for start, end in spans:
        chunks.append(text[cursor:start])
        chunks.append(replacement)
        cursor = end
    chunks.append(text[cursor:])
    return "".join(chunks)


def _split(translator, arguments):
    name = "String.split"
    _arguments(translator, name, arguments)
    text = _string(arguments["string"], name + " string")
    regex = _string(arguments["regex"], name + " regex")
    _, ignore_case = _flags(arguments.get("flags", ""), name)
    text_bytes = measure_utf8(translator, text, name + " string")
    if regex == "":
        count = len(text)
        if count > MAX_REGEX_OUTPUT_ITEMS:
            fail(f"{name} exceeds 10000 output items")
        charge_output(translator, len(text), text_bytes, name)
        charge_output(translator, count, 0, name + " result items")
        return list(text)

    compiled = compile_pattern(translator, regex, (text,), ignore_case)
    # Split pieces contain only subject text with separators removed. Their
    # total size cannot exceed the original string, even for zero-width RE2
    # matches; reserve that bound before searching.
    charge_output(translator, len(text), text_bytes, name)
    spans = _collect_spans(
        translator, compiled, text, global_match=True, label=name,
    )
    item_count = len(spans) + 1
    if item_count > MAX_REGEX_OUTPUT_ITEMS:
        fail(f"{name} exceeds 10000 output items")
    charge_output(translator, item_count, 0, name + " result items")
    pieces = []
    cursor = 0
    for start, end in spans:
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return pieces


def invoke_string_regex(translator, name, arguments):
    """Evaluate a supported regex String method on finite literal values."""
    if name == "String.match":
        return _match(translator, arguments)
    if name == "String.replace":
        return _replace(translator, arguments)
    if name == "String.split":
        return _split(translator, arguments)
    fail(f"Unsupported static String regex operation: {name}")

