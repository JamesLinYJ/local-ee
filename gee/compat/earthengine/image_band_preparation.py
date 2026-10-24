"""Bounded band-name preparation, slicing, concatenation and cast aliases."""
from __future__ import annotations

import math
from dataclasses import replace

from .ir import Image, as_image, fail, integer, unary
from .regex_values import (
    MAX_REGEX_TEXTS,
    MAX_REGEX_TEXT_BYTES,
    charge_output,
    compile_pattern,
    measure_utf8,
)


BAND_PREPARATION_FUNCTIONS = frozenset({
    "Image.regexpRename", "Image.slice", "Image.cat", "Image.float", "Image.double",
})
BAND_PREPARATION_ARGUMENTS = {
    "Image.regexpRename": (frozenset({"input", "regex", "replacement"}), frozenset({"all"})),
    "Image.slice": (frozenset({"image", "start"}), frozenset({"end"})),
    "Image.cat": (frozenset({"images"}), frozenset()),
    "Image.float": (frozenset({"value"}), frozenset()),
    "Image.double": (frozenset({"value"}), frozenset()),
}
_MAX_BANDS = 10_000
_MAX_WORK = 50_000


def _charge(translator, amount, label):
    if (type(amount) is not int or amount < 0
            or type(translator.steps) is not int or translator.steps < 0
            or translator.steps + amount > _MAX_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps += amount


def _required(translator, name, arguments, required, optional=()):
    translator.allowed(arguments, set(required) | set(optional))
    missing = set(required) - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def _replacement_tokens(replacement, group_count):
    """Compile documented $n capture references; unmatched groups expand empty."""
    tokens = []
    literal = []
    index = 0
    while index < len(replacement):
        if (replacement[index] != "$" or index + 1 >= len(replacement)
                or not "0" <= replacement[index + 1] <= "9"):
            literal.append(replacement[index])
            index += 1
            continue
        digits_start = index + 1
        group = int(replacement[digits_start])
        if group > group_count:
            fail("Image.regexpRename replacement references an unknown capture group")
        end = digits_start + 1
        while end < len(replacement) and "0" <= replacement[end] <= "9":
            candidate = group * 10 + int(replacement[end])
            if candidate > group_count:
                break
            group = candidate
            end += 1
        if literal:
            tokens.append(("literal", "".join(literal)))
            literal.clear()
        tokens.append(("group", group))
        index = end
    if literal:
        tokens.append(("literal", "".join(literal)))
    return tokens


def _utf8_range_size(text, start, end):
    size = 0
    for index in range(start, end):
        code = ord(text[index])
        size += 1 if code < 0x80 else 2 if code < 0x800 else 4 if code > 0xFFFF else 3
    return size


def _utf8_size(text):
    size = 0
    for character in text:
        code = ord(character)
        size += 1 if code < 0x80 else 2 if code < 0x800 else 4 if code > 0xFFFF else 3
    return size


def _matches(compiled, text, all_matches):
    try:
        found = compiled.finditer(text) if all_matches else (compiled.search(text),)
        previous = None
        for match in found:
            if match is None:
                break
            span = match.span(0)
            # The pinned google-re2 binding may report the same terminal
            # zero-width span twice. Earth Engine replacement consumes it once.
            if span == previous:
                continue
            previous = span
            yield match
    except Exception as exc:
        # Do not let a matcher implementation detail cross the compiler API.
        if exc.__class__.__module__.startswith("re2"):
            fail("Image.regexpRename failed in the bounded RE2 matcher")
        raise


def _replacement_size(text, match, tokens):
    chars = 0
    byte_count = 0
    for kind, item in tokens:
        if kind == "literal":
            chars += len(item)
            byte_count += sum(1 if ord(c) < 0x80 else 2 if ord(c) < 0x800 else 4 if ord(c) > 0xFFFF else 3 for c in item)
        else:
            start, end = match.span(item)
            if start >= 0:
                chars += end - start
                byte_count += _utf8_range_size(text, start, end)
    return chars, byte_count


def _expand_replacement(match, tokens):
    pieces = []
    for kind, item in tokens:
        if kind == "literal":
            pieces.append(item)
        else:
            value = match.group(item)
            pieces.append("" if value is None else value)
    return "".join(pieces)


def _regexp_rename(translator, arguments):
    name = "Image.regexpRename"
    _required(translator, name, arguments, {"input", "regex", "replacement"}, {"all"})
    image = arguments["input"]
    if not isinstance(image, Image):
        fail(f"{name} requires an Image")
    pattern, replacement = arguments["regex"], arguments["replacement"]
    if type(pattern) is not str or type(replacement) is not str:
        fail(f"{name} regex and replacement must be strings")
    all_matches = arguments.get("all")
    if all_matches is None:
        all_matches = True
    if type(all_matches) is not bool:
        fail(f"{name} all must be a boolean or null")

    count = len(image.bands)
    if count > min(_MAX_BANDS, MAX_REGEX_TEXTS):
        fail(f"{name} supports at most 10000 bands")
    # Reserve the name list before scanning the image's band table.
    _charge(translator, count + 1, name + " band scan")
    old_names = [band_name for band_name, _ in image.bands]
    compiled = compile_pattern(translator, pattern, old_names)
    measure_utf8(translator, replacement, name + " replacement")
    tokens = _replacement_tokens(replacement, compiled.groups)

    program_size = max(1, compiled.programsize) + max(1, compiled.reverseprogramsize)
    subject_chars = sum(len(value) for value in old_names)
    _charge(translator, subject_chars + count, name + " UTF-8 size scan")
    scan_measure = subject_chars + sum(_utf8_size(value) for value in old_names) + count
    max_matches = sum(len(value) + 1 for value in old_names)
    # One pass measures exact output; a second pass builds it only after the
    # shared work and 1 MB output limits have both been charged.
    _charge(
        translator,
        2 * program_size * max(1, scan_measure)
        + 2 * max_matches * max(1, len(tokens)),
        name + " replacement scans",
    )
    output_chars = 0
    output_bytes = 0
    for text in old_names:
        cursor = 0
        for match in _matches(compiled, text, all_matches):
            start, end = match.span(0)
            output_chars += start - cursor
            output_bytes += _utf8_range_size(text, cursor, start)
            chars, byte_count = _replacement_size(text, match, tokens)
            output_chars += chars
            output_bytes += byte_count
            cursor = end
        output_chars += len(text) - cursor
        output_bytes += _utf8_range_size(text, cursor, len(text))
        if output_bytes > MAX_REGEX_TEXT_BYTES:
            fail(f"{name} output exceeds the 1 MB UTF-8 limit")
    charge_output(translator, output_chars + count, output_bytes, name)

    _charge(translator, count, name + " collision check")
    new_names = []
    for text in old_names:
        matches = list(_matches(compiled, text, all_matches))
        if not matches:
            new_names.append(text)
            continue
        chunks = []
        cursor = 0
        for match in matches:
            start, end = match.span(0)
            chunks.extend((text[cursor:start], _expand_replacement(match, tokens)))
            cursor = end
        chunks.append(text[cursor:])
        new_names.append("".join(chunks))

    if len(set(new_names)) != len(new_names):
        fail(f"{name} produces duplicate band names")
    return replace(image, bands=[(new, pixel) for new, (_, pixel) in zip(new_names, image.bands)])


def _slice(translator, arguments):
    name = "Image.slice"
    _required(translator, name, arguments, {"image", "start"}, {"end"})
    image = arguments["image"]
    if not isinstance(image, Image):
        fail(f"{name} requires an Image")
    start = integer(arguments["start"], name + " start")
    end_value = arguments.get("end")
    end = None if end_value is None else integer(end_value, name + " end")
    count = len(image.bands)
    if count > _MAX_BANDS:
        fail(f"{name} input exceeds 10000 bands")
    # Python's bounded list-slice normalization matches the documented
    # inclusive start, exclusive end and negative-from-end positions; its
    # out-of-range clamping is a local policy because Google does not document it.
    start_index, stop_index, step = slice(start, end).indices(count)
    output_count = len(range(start_index, stop_index, step))
    _charge(translator, count + output_count + 1, name + " band selection")
    return replace(image, bands=image.bands[start:end])


def _input_band_count(value):
    if isinstance(value, Image):
        return len(value.bands)
    if type(value) in (int, float, bool):
        return 1
    if type(value) is list:
        return len(value)
    fail("Image.cat inputs must be Images or finite numeric constants")


def _validate_cat_constant(value):
    values = value if type(value) is list else (value,)
    for item in values:
        if type(item) not in (int, float, bool):
            fail("Image.cat inputs must be Images or finite numeric constants")
        if type(item) is float and not math.isfinite(item):
            fail("Image.cat inputs must be finite numeric constants")


def _cat(translator, arguments):
    name = "Image.cat"
    _required(translator, name, arguments, {"images"})
    images = arguments["images"]
    if type(images) is not list or not images:
        fail("Image.cat requires at least one input image")
    if len(images) > _MAX_BANDS:
        fail("Image.cat supports at most 10000 input images")
    # Count list entries before reading them, then reserve the complete band
    # scan before coercing constants or allocating the result band list.
    _charge(translator, len(images), name + " input scan")
    total_bands = 0
    for value in images:
        total_bands += _input_band_count(value)
        if total_bands > _MAX_BANDS:
            fail("Image.cat exceeds 10000 output bands")
    _charge(translator, total_bands + len(images), name + " band preparation")
    for value in images:
        if not isinstance(value, Image):
            _validate_cat_constant(value)
    normalized = [as_image(value) for value in images]

    result = normalized[0]
    for source in normalized[1:]:
        # Use the existing addBands contract for constant binding and suffixes.
        result = translator.invoke("Image.addBands", {"dstImg": result, "srcImg": source})
    return result


def invoke_image_band_preparation(translator, name, arguments):
    """Implement bounded image band selection, concatenation, and casts."""
    if name == "Image.regexpRename":
        return _regexp_rename(translator, arguments)
    if name == "Image.slice":
        return _slice(translator, arguments)
    if name == "Image.cat":
        return _cat(translator, arguments)
    if name == "Image.float":
        _required(translator, name, arguments, {"value"})
        return translator.invoke("Image.toFloat", arguments)
    if name == "Image.double":
        _required(translator, name, arguments, {"value"})
        return translator.invoke("Image.toDouble", arguments)
    fail(f"Unsupported image band-preparation operation: {name}")


__all__ = [
    "BAND_PREPARATION_ARGUMENTS", "BAND_PREPARATION_FUNCTIONS",
    "invoke_image_band_preparation",
]
