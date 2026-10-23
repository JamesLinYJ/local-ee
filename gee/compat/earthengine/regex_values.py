"""Bounded UTF-8 validation and actual RE2 compilation for static EE regexes.

Patterns and subjects are never passed to Python's backtracking ``re`` engine.
The pinned ``google-re2`` binding is configured with a per-program memory cap;
its small process-global LRU is purged after compilation so submitted patterns
are not retained between evaluations.
"""
from __future__ import annotations

import re2

from .ir import fail
from .string_values import MAX_STATIC_STRING_WORK


MAX_REGEX_PATTERN_BYTES = 4_096
MAX_REGEX_TEXTS = 10_000
MAX_REGEX_TEXT_BYTES = 1_000_000
MAX_REGEX_OUTPUT_BYTES = 1_000_000
MAX_REGEX_OUTPUT_ITEMS = 10_000
MAX_REGEX_PROGRAM_MEMORY = 1 << 20


def _charge(translator, amount, label):
    if (amount < 0 or translator.steps + amount > MAX_STATIC_STRING_WORK):
        fail(f"{label} exceeds the shared string work budget")
    translator.steps += amount


def _utf8_length(value, label):
    """Measure strict UTF-8 bytes without allocating an encoded copy."""
    size = 0
    for character in value:
        code = ord(character)
        if 0xD800 <= code <= 0xDFFF:
            fail(f"{label} must contain valid Unicode scalar values (UTF-8)")
        size += (1 if code < 0x80 else 2 if code < 0x800 else
                 4 if code > 0xFFFF else 3)
    return size


def _has_byte_escape(pattern):
    """Reject RE2's byte-oriented escape, which can bisect UTF-8 scalars."""
    escaped = False
    for character in pattern:
        if escaped:
            if character == "C":
                return True
            escaped = False
        elif character == "\\":
            escaped = True
    return False


def measure_utf8(translator, value, label):
    """Validate and byte-measure one string before downstream allocation."""
    if type(value) is not str:
        fail(f"{label} must be a string")
    _charge(translator, len(value), label + " UTF-8 preflight")
    size = _utf8_length(value, label)
    if size > MAX_REGEX_TEXT_BYTES:
        fail(f"{label} exceeds the 1 MB UTF-8 limit")
    return size


def compile_pattern(translator, pattern, texts, ignore_case=False):
    """Compile an actual bounded RE2 pattern for finite string subjects.

    ``texts`` must be a bounded list/tuple of strings. Pattern/subject Unicode
    validation, compilation cost, and the RE2 program-size-times-subject-size
    scan reservation are charged to the translator before callers match.
    The returned pattern retains only the pattern, never any supplied subject.
    """
    if type(pattern) is not str:
        fail("Regular expression pattern must be a string")
    if type(texts) not in (list, tuple) or len(texts) > MAX_REGEX_TEXTS:
        fail("Regular expression subjects must be a list or tuple of at most 10000 strings")
    if type(ignore_case) is not bool:
        fail("Regular expression ignore_case must be a boolean")

    _charge(translator, len(texts), "Regular expression subject count")
    subject_chars = 0
    for text in texts:
        if type(text) is not str:
            fail("Regular expression subjects must contain only strings")
        subject_chars += len(text)
    if subject_chars > MAX_STATIC_STRING_WORK:
        fail("Regular expression subjects exceed the shared string work budget")

    pattern_chars = len(pattern)
    # Reserve all code-point walks before checking any individual Unicode
    # scalar or constructing per-subject accounting state.
    _charge(translator, pattern_chars + subject_chars + len(texts),
            "Regular expression input preflight")
    pattern_bytes = _utf8_length(pattern, "Regular expression pattern")
    if pattern_bytes > MAX_REGEX_PATTERN_BYTES:
        fail("Regular expression pattern exceeds the 4096-byte limit")
    if _has_byte_escape(pattern):
        fail("Regular expression is invalid or uses syntax unsupported by RE2 or the local UTF-8 policy")
    text_bytes = []
    total_bytes = 0
    for text in texts:
        size = _utf8_length(text, "Regular expression subject")
        total_bytes += size
        if total_bytes > MAX_REGEX_TEXT_BYTES:
            fail("Regular expression subjects exceed the 1 MB UTF-8 limit")
        text_bytes.append(size)

    # RE2 compilation is linear in input size for the accepted syntax; its
    # 1 MiB program-memory cap also bounds expanded counted repetitions.
    _charge(translator, max(1, pattern_chars + pattern_bytes),
            "Regular expression compilation")
    options = re2.Options()
    options.max_mem = MAX_REGEX_PROGRAM_MEMORY
    options.log_errors = False
    options.case_sensitive = not ignore_case
    options.perl_classes = True
    options.word_boundary = True
    try:
        compiled = re2.compile(pattern, options=options)
    except (re2.error, UnicodeError, ValueError, TypeError):
        fail("Regular expression is invalid or uses syntax unsupported by RE2")
    finally:
        # google-re2's wrapper has a 128-entry LRU for compiled patterns.
        # Drop those references after this request obtains its own object.
        re2.purge()

    program_size = max(1, compiled.programsize) + max(1, compiled.reverseprogramsize)
    _charge(translator, program_size, "Regular expression program compilation")
    # Empty subjects still require one RE2 program walk apiece (notably for
    # Dictionary selector lists), so count subjects independently of length.
    scan_measure = total_bytes + subject_chars + len(texts)
    _charge(translator, program_size * scan_measure,
            "Regular expression matching")
    return compiled


def charge_output(translator, work, byte_size, label):
    """Reserve bounded output work and UTF-8 bytes before materialization."""
    if byte_size < 0 or byte_size > MAX_REGEX_OUTPUT_BYTES:
        fail(f"{label} exceeds the 1 MB UTF-8 output limit")
    _charge(translator, work, label + " output")

