"""Bounded weak attestations for validated classified-table provenance."""
from __future__ import annotations

from collections import OrderedDict
import threading
import weakref

from .ee_json_result import PendingRuntimeTable, RuntimeFeatureTable


MAX_VERIFIED_ORIGIN_CACHE = 64
CACHE_LOOKUP_WORK = 8
CACHE_ATTESTATION_WORK = 32
_VERIFIED_ORIGINS = OrderedDict()
_VERIFIED_ORIGINS_LOCK = threading.RLock()


def table_columns(table):
    return (getattr(table, "columns", None) if type(table) is PendingRuntimeTable
            else getattr(table, "_columns", None))


def remember_verified_origin(table, work=None, *, precharged=False):
    """Cache only schema identity and bounded budget snapshots, never data."""
    if type(table) not in (RuntimeFeatureTable, PendingRuntimeTable):
        raise ValueError("Only exact runtime tables can carry verified origin state")
    if work is not None and not precharged:
        work.charge(CACHE_ATTESTATION_WORK)
    key = id(table)
    state = (
        table.classification_origin_spec, table.runtime_operations, table_columns(table),
        table.prior_sample_operation_count, table.prior_sample_operation_work,
        table.runtime_operation_work,
    )
    with _VERIFIED_ORIGINS_LOCK:
        def discard(reference):
            with _VERIFIED_ORIGINS_LOCK:
                current = _VERIFIED_ORIGINS.get(key)
                if current is not None and current[0] is reference:
                    _VERIFIED_ORIGINS.pop(key, None)

        reference = weakref.ref(table, discard)
        _VERIFIED_ORIGINS[key] = (reference, state)
        _VERIFIED_ORIGINS.move_to_end(key)
        while len(_VERIFIED_ORIGINS) > MAX_VERIFIED_ORIGIN_CACHE:
            _VERIFIED_ORIGINS.popitem(last=False)


def cached_verified_columns(
    table, declared, origin_spec, operations, prior_count, prior_work,
    operation_work, work,
):
    """Return previously verified headers only while every identity still matches."""
    work.charge(CACHE_LOOKUP_WORK)
    key = id(table)
    with _VERIFIED_ORIGINS_LOCK:
        entry = _VERIFIED_ORIGINS.get(key)
        cached = entry[1] if entry is not None and entry[0]() is table else None
        if entry is not None and cached is not None:
            _VERIFIED_ORIGINS.move_to_end(key)
        elif entry is not None:
            _VERIFIED_ORIGINS.pop(key, None)
    if cached is None:
        return None
    if (origin_spec is not cached[0] or operations is not cached[1]
            or declared is not cached[2] or prior_count != cached[3]
            or prior_work != cached[4] or operation_work != cached[5]):
        raise ValueError("Runtime table verified provenance/header/work metadata changed")
    return cached[2]


def cache_entry_count():
    with _VERIFIED_ORIGINS_LOCK:
        return len(_VERIFIED_ORIGINS)


def is_cached(table):
    with _VERIFIED_ORIGINS_LOCK:
        entry = _VERIFIED_ORIGINS.get(id(table))
        return entry is not None and entry[0]() is table


def clear_cache():
    """Clear process-local attestations for isolated tests and runtime reset."""
    with _VERIFIED_ORIGINS_LOCK:
        _VERIFIED_ORIGINS.clear()
