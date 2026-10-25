"""Successful literal Feature metadata preflights, scoped to measure readers."""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct

from .geometry_values import GeometryValue
from .ir import fail
from .owned_metadata_values import (
    MAX_METADATA_DEPTH, MAX_METADATA_ENTRIES, _clone, charge_metadata,
    preflight_owned_metadata_value,
)

MAX_ENTRIES = 64
MAX_BUCKET_ENTRIES = 4
MAX_RETAINED_BYTES = 1_000_000
_READERS = frozenset({"Feature.id", "Feature.area", "Feature.length",
                      "Feature.perimeter", "Feature.centroid"})


@dataclass(frozen=True)
class Entry:
    key: tuple
    retained_bytes: int
    copy_cost: int


@dataclass
class Cache:
    buckets: dict
    entries: int = 0
    retained_bytes: int = 0


def _tokens(translator, value, retained):
    """Combine fresh bounds/cycle/finite scanning and immutable token creation.

    Geometry sidecars are metadata here, with their existing eight-field
    structural contract. This is not a geometry or topology validation proof.
    """
    active = set()
    def emit(token, text_work=0, size=64):
        # String lengths reserve the actual content comparison as well as the
        # existing bounded-literal admission rule. No full key is hashed.
        charge_metadata(translator, 1 + text_work, "Feature literal snapshot")
        retained[0] += size
        yield token

    def visit(raw, depth=0):
        if depth > MAX_METADATA_DEPTH:
            fail("Element metadata exceeds the depth limit")
        kind = type(raw)
        if raw is None:
            yield from emit(b"n")
        elif kind is bool:
            yield from emit(b"t" if raw else b"f")
        elif kind is str:
            yield from emit(raw, len(raw), 64 + 4 * len(raw))
        elif kind is float:
            if not math.isfinite(raw):
                fail("Element metadata numbers must be finite")
            charge_metadata(translator, 1, "Feature literal numeric snapshot")
            yield from emit(b"f" + struct.pack(">d", raw))
        elif kind is int:
            # Large or nonfinite conversion cases keep the original public
            # formatter's domain and errors instead of constructing huge keys.
            if raw.bit_length() > 1024:
                raise TypeError("Large integer uses the ordinary preflight")
            size = max(1, (raw.bit_length() + 8) // 8)
            charge_metadata(translator, size, "Feature literal integer snapshot")
            yield from emit(b"i" + raw.to_bytes(size, "big", signed=True),
                            max(0, size - 1), 64 + size)
        elif kind in (dict, list, GeometryValue):
            if len(raw) > MAX_METADATA_ENTRIES:
                fail("Element metadata containers support at most 10000 entries")
            identity = id(raw)
            if identity in active:
                fail("Element metadata cannot contain cycles")
            active.add(identity)
            try:
                yield from emit(("geometry" if kind is GeometryValue else kind.__name__, len(raw)))
                if kind is list:
                    for child in raw:
                        yield from visit(child, depth + 1)
                else:
                    for key, child in raw.items():
                        if type(key) is not str:
                            fail("Element metadata dictionaries require string keys")
                        yield from emit(key, len(key), 64 + 4 * len(key))
                        yield from visit(child, depth + 1)
                if kind is GeometryValue:
                    metadata = raw.geometry_metadata
                    if type(metadata) is not dict or len(metadata) > 8:
                        fail("Geometry constructor metadata is malformed")
                    yield from visit(metadata, depth + 1)
            finally:
                active.remove(identity)
        else:
            raise TypeError("Typed metadata keeps the ordinary preflight")

    yield from visit(value)


def _locator(translator, value):
    """Choose candidates cheaply; this index never establishes a cache hit."""
    properties = value["properties"]
    parts = []
    for container, key in ((value, "id"), (properties, "system:index")):
        present = key in container
        item = container.get(key)
        if present and type(item) is not str:
            return None
        charge_metadata(translator, 2 + (len(item) if present else 0),
                        "Feature preflight candidate index")
        parts.append((present, item))
    return tuple(parts)


def _matches(translator, value, key):
    count = 0
    for index, token in enumerate(_tokens(translator, value, [0])):
        charge_metadata(translator, 1, "Feature literal token comparison")
        if index >= len(key) or token != key[index]:
            return False
        count += 1
    return count == len(key)


def _capacity(translator, cache, size):
    geometry = getattr(translator, "_geometry_measure_cache", None)
    entries = cache.entries + (geometry.entries if geometry else 0)
    retained = cache.retained_bytes + (geometry.retained_bytes if geometry else 0)
    return entries < MAX_ENTRIES and retained + size <= MAX_RETAINED_BYTES


def preflight(translator, value, label, *, reserve_copy=True):
    """Reuse only successful complete literal checks; copy work stays fresh."""
    if label not in _READERS:
        return preflight_owned_metadata_value(
            translator, value, label, reserve_copy=reserve_copy,
        )
    locator = _locator(translator, value)
    if locator is None:
        return preflight_owned_metadata_value(
            translator, value, label, reserve_copy=reserve_copy,
        )
    cache = getattr(translator, "_feature_preflight_cache", None)
    if cache is None:
        cache = Cache({})
        translator._feature_preflight_cache = cache
    try:
        for entry in cache.buckets.get(locator, ()):
            if _matches(translator, value, entry.key):
                if reserve_copy:
                    charge_metadata(translator, entry.copy_cost, label + " JSON preflight")
                return entry.copy_cost
        if len(cache.buckets.get(locator, ())) >= MAX_BUCKET_ENTRIES:
            return preflight_owned_metadata_value(
                translator, value, label, reserve_copy=reserve_copy,
            )
        retained = [0]
        key = tuple(_tokens(translator, value, retained))
    except TypeError:
        return preflight_owned_metadata_value(
            translator, value, label, reserve_copy=reserve_copy,
        )
    retained_bytes = retained[0]
    # Insertion work is prepaid before the original preflight can complete.
    # Failed public-size/finite/copy validation never creates an entry.
    admit = _capacity(translator, cache, retained_bytes) and translator.steps + 2 <= 50_000
    if admit:
        charge_metadata(translator, 2, "Feature literal preflight store reservation")
    copy_cost = preflight_owned_metadata_value(
        translator, value, label, reserve_copy=reserve_copy,
    )
    if admit:
        cache.buckets.setdefault(locator, []).append(
            Entry(key, retained_bytes, copy_cost),
        )
        cache.entries += 1
        cache.retained_bytes += retained_bytes
    return copy_cost


def owned_feature_copy(translator, value, label):
    copy_cost = preflight(translator, value, label, reserve_copy=False)
    charge_metadata(translator, copy_cost, label + " source Feature copy")
    return _clone(value, {})
