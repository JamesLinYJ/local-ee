"""Bounded canonical JSON preflight for runtime RF explanation specs."""
from __future__ import annotations

from .array_core import charge_array
from .ir import fail


MAX_EXPLANATION_SPEC_BYTES = 16_384
ROOT_KEYS = ("importance", "numberOfTrees", "outOfBagErrorEstimate")
ROOT_KEY_WORK = len(ROOT_KEYS) + sum(map(len, ROOT_KEYS))


def _json_string_utf8_size(value):
    """Measure one ensure_ascii=False JSON string without encoding or copying it."""
    size = 2  # opening and closing quotes
    for character in value:
        code = ord(character)
        if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
            size += 2
        elif code < 0x20:
            size += 6  # canonical \\u00xx escape
        elif 0xD800 <= code <= 0xDFFF:
            raise ValueError("RF explanation names must be valid UTF-8")
        elif code <= 0x7F:
            size += 1
        elif code <= 0x7FF:
            size += 2
        elif code <= 0xFFFF:
            size += 3
        else:
            size += 4
    return size


def explanation_spec_utf8_size(schema, trees, view, keys):
    """Measure the exact compact, sorted-key JSON emitted by encode_spec."""
    schema_size = 2 + max(0, len(schema) - 1)
    for name in schema:
        schema_size += _json_string_utf8_size(name)
    if keys is None:
        keys_size = None
    else:
        keys_size = 2 + max(0, len(keys) - 1)
        for key in keys:
            keys_size += _json_string_utf8_size(key)

    # The shared encoder sorts field names. Their order affects no byte count;
    # these ASCII field labels and separators have fixed compact encodings.
    members = [
        ("schema", schema_size),
        ("trees", 1 if trees < 10 else 2 if trees < 100 else 3),
        ("version", 1),
        ("view", _json_string_utf8_size(view)),
    ]
    if keys_size is not None:
        members.append(("keys", keys_size))
    size = 2 + max(0, len(members) - 1)  # braces and commas
    for name, value_size in members:
        size += len(name) + 2 + 1 + value_size  # quoted field, colon, value
    return size


def precharge_explanation_spec(translator, schema, trees, view, keys):
    """Charge preflight and encoder work before the shared helper copies data."""
    scan_work = 32 + sum(map(len, schema)) + len(view)
    if keys is not None:
        scan_work += sum(map(len, keys))
    charge_array(translator, scan_work)
    try:
        spec_bytes = explanation_spec_utf8_size(schema, trees, view, keys)
    except ValueError as exc:
        fail(str(exc))
    if spec_bytes > MAX_EXPLANATION_SPEC_BYTES:
        fail("RF explanation specification exceeds16384 UTF-8 bytes")

    copy_work = (
        128 + ROOT_KEY_WORK + 257 * len(schema)
        + (len(keys) if keys else 0) + len(view)
        # prepare_explanation_spec serializes once, checks UTF-8 size, then
        # decodes and canonicalizes again. Reserve a conservative eight full
        # wire passes for those bounded helper copies/scans before entry.
        + 8 * spec_bytes
    )
    charge_array(translator, copy_work)
    return spec_bytes
