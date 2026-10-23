"""Precharged detached-copy checks for List.reduce first/last outputs."""
from __future__ import annotations

import math
import numpy as np

from .ir import fail


def _charge(translator, work):
    if work < 0 or translator.steps + work > 50_000:
        fail("List.reduce output exceeds the shared 50000-step compilation work budget")
    translator.steps += work


def _owned_value(translator, value):
    """Validate and charge a first/last result before returning an owned copy."""
    from .array_values import StaticArray

    remaining = [1_000_000]
    active = set()

    def charge(work, wire):
        # Reserve a second traversal's work for the owned deepcopy while the
        # first bounded scan is still in progress.
        _charge(translator, work * 2)
        remaining[0] -= wire
        if remaining[0] < 0:
            fail("List.reduce output exceeds the 1 MB JSON size limit")

    def scan(item, depth=0):
        if depth > 96:
            fail("List.reduce output exceeds the depth 96 limit")
        kind = type(item)
        if item is None:
            charge(1, 4)
            return
        if kind is bool:
            charge(1, 4 if item else 5)
            return
        if kind is int:
            if abs(item).bit_length() > 160_000:
                fail("List.reduce output exceeds the 1 MB JSON size limit")
            digits = max(1, math.ceil(abs(item).bit_length() * math.log10(2)))
            charge(1 + digits + (item < 0), digits + (item < 0))
            return
        if kind is float:
            if not math.isfinite(item):
                fail("List.reduce output numbers must be finite")
            size = len(repr(item))
            charge(1 + size, size)
            return
        if kind is str:
            base = len(item) + 2
            charge(base, base)
            for character in item:
                code = ord(character)
                if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
                    extra = 1
                elif code < 32 or code >= 127:
                    extra = 5 if code <= 0xffff else 11
                else:
                    extra = 0
                if extra:
                    charge(extra, extra)
            return
        if kind is StaticArray:
            data = item.data
            if data.size > 10_000 or data.ndim > 8:
                fail("List.reduce Array output exceeds finite static limits")
            cell_count = int(data.size)
            wire = 32 * cell_count + 2 + 2 * max(0, cell_count - 1) + 2 * data.ndim
            charge(1 + cell_count, wire)
            if not np.isfinite(data).all():
                fail("List.reduce Array output exceeds finite static limits")
            return
        if kind not in (dict, list):
            fail("List.reduce first/last output supports finite static JSON or Array values")
        identity = id(item)
        if identity in active:
            fail("List.reduce first/last values cannot contain cycles")
        if len(item) > 10_000:
            fail("List.reduce first/last containers support at most 10000 entries")
        count = len(item)
        punctuation = 2 + max(0, count - 1) + (count if kind is dict else 0)
        charge(1 + count, punctuation)
        active.add(identity)
        try:
            if kind is dict:
                for key, child in item.items():
                    if type(key) is not str:
                        fail("List.reduce first/last dictionary keys must be strings")
                    scan(key, depth + 1)
                    scan(child, depth + 1)
            else:
                for child in item:
                    scan(child, depth + 1)
        finally:
            active.remove(identity)

    scan(value)
    def clone(item):
        if type(item) is StaticArray:
            owned = item.data.copy()
            owned.flags.writeable = False
            return StaticArray(owned)
        if type(item) is dict:
            return {key: clone(child) for key, child in item.items()}
        if type(item) is list:
            return [clone(child) for child in item]
        return item

    return clone(value)
