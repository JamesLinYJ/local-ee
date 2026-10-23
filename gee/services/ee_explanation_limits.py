"""Preflight bounded RF explanation specs and JSON before API parsing."""
from __future__ import annotations

from ..rf_explanation_spec import MAX_SPEC_BYTES, decode_explanation_spec


MAX_OBJECT_WORK = 150_000
MAX_WIRE_WORK = 3_000_000
MAX_VALUE_SLOTS = 8192


def preflight_explanation(spec, payload=b""):
    """Reserve scans/copies and reject oversized structure before json.loads."""
    if type(spec) is not str or len(spec) > MAX_SPEC_BYTES:
        raise ValueError("Explanation result requires a bounded canonical specification")
    if type(payload) is not bytes or len(payload) > 1_000_000:
        raise ValueError("Explanation JSON must be bounded bytes")
    # These independent bounds reserve the spec decode, wire/string scans and
    # the largest declared projected object. A wire byte is not a copied node.
    if 2 * len(spec) + MAX_VALUE_SLOTS > MAX_OBJECT_WORK:
        raise ValueError("Explanation JSON exceeds its object-work budget")
    try:
        size = len(spec.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError("Explanation specification must be valid UTF-8") from exc
    if size > MAX_SPEC_BYTES or 2 * size + 2 * len(payload) > MAX_WIRE_WORK:
        raise ValueError("Explanation JSON exceeds its wire-work budget")
    decoded = decode_explanation_spec(spec)
    # Count structural slots outside strings without allocating a parse tree.
    # JSON grammar, duplicates, numbers and declared view are checked next by
    # the existing strict parser and the closed explanation value validator.
    quoted = escaped = False
    depth, slots = 0, 1
    for byte in payload:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (123, 91):
            depth += 1
            slots += 1
        elif byte in (125, 93):
            depth -= 1
        elif byte in (44, 58):
            slots += 1
        if slots > MAX_VALUE_SLOTS or depth > 32 or depth < 0:
            raise ValueError("Explanation JSON exceeds its bounded structure")
    return decoded
