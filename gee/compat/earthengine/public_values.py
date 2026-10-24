"""Bounded JSON materialization of computed values and nested image metadata."""
from __future__ import annotations

import math
import json

from .array_values import StaticArray
from .ir import Image, fail


def public_value(value):
    """Describe nested images without exposing executable IR or physical paths.

    Join matches remain actual Image values inside the compiler so they can be
    selected and combined. Only at the public boundary are they converted to
    the same metadata representation used by finite ImageCollection outputs.
    """
    remaining = [50000]
    encoded_remaining = [1_000_000]

    def charge(size):
        encoded_remaining[0] -= size
        if encoded_remaining[0] < 0:
            fail("Computed value exceeds 1 MB")

    def charge_string(text):
        # Match json.dumps' default ensure_ascii=True without allocating an
        # escaped copy. Repeated shared strings consume the budget each time.
        charge(len(text) + 2)
        for character in text:
            code = ord(character)
            if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
                charge(1)
            elif code < 32 or code >= 127:
                charge(5 if code <= 0xffff else 11)

    def convert(item, depth=0):
        from .spherical_wire import FullSphere

        if isinstance(item, FullSphere):
            fail("Full-sphere public GeoJSON encoding is unverified; use a supported predicate")
        remaining[0] -= 1
        if depth > 96 or remaining[0] < 0:
            fail("Computed metadata exceeds materialization limits")
        if isinstance(item, StaticArray):
            item = item.to_value()
        if isinstance(item, Image):
            item = {
                "type": "Image",
                "id": item.props.get("system:index"),
                "properties": item.props,
                "bands": [{"id": name} for name, _ in item.bands],
            }
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                fail("Computed dictionary keys must be strings")
            charge(2 + 2 * len(item) + 2 * max(0, len(item) - 1))
            for key in item:
                charge_string(key)
            return {key: convert(child, depth + 1) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            charge(2 + 2 * max(0, len(item) - 1))
            return [convert(child, depth + 1) for child in item]
        if item is None or isinstance(item, (str, bool)):
            if isinstance(item, str):
                charge_string(item)
            else:
                charge(4 if item is None or item is True else 5)
            return item
        if isinstance(item, (int, float)):
            try:
                finite = math.isfinite(item)
            except OverflowError:
                finite = False
            if not finite:
                fail("Computed values must be finite")
            charge(len(json.dumps(item, allow_nan=False)))
            return item
        fail("Unsupported internal value at the public JSON boundary")

    return convert(value)


def public_result(result):
    """Apply a single budget to the whole output, including joined metadata."""
    return public_value(result)
