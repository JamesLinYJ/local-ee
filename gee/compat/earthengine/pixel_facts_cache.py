"""Bounded translator-local cache for immutable Pixel lineage facts."""
from __future__ import annotations

from collections import OrderedDict


MAX_PIXEL_FACTS_CACHE_ENTRIES = 4096


class PixelFactsCache:
    """Keep strong object references beside facts so identity keys cannot alias."""

    def __init__(self, max_entries: int = MAX_PIXEL_FACTS_CACHE_ENTRIES):
        if (type(max_entries) is not int
                or not 1 <= max_entries <= MAX_PIXEL_FACTS_CACHE_ENTRIES):
            raise ValueError("Pixel facts cache limit must be an integer from1 through4096")
        self.max_entries = max_entries
        self._entries: OrderedDict[int, tuple[object, object]] = OrderedDict()

    def lookup(self, value: object):
        """Return facts for this exact object, promoting an LRU hit."""
        key = id(value)
        entry = self._entries.get(key)
        if entry is None or entry[0] is not value:
            return None
        self._entries.move_to_end(key)
        return entry[1]

    def store(self, value: object, facts: object, charge) -> None:
        """Precharge insertion and any eviction before changing the cache."""
        key = id(value)
        current = self._entries.get(key)
        if current is not None and current[0] is value:
            charge(1)
            self._entries.move_to_end(key)
            return

        eviction_work = int(len(self._entries) >= self.max_entries)
        charge(1 + eviction_work)
        if eviction_work:
            self._entries.popitem(last=False)
        self._entries[key] = (value, facts)

    def contains_identity(self, value: object) -> bool:
        """Report membership without changing LRU order (primarily diagnostics)."""
        entry = self._entries.get(id(value))
        return entry is not None and entry[0] is value

    def __len__(self) -> int:
        return len(self._entries)


def translator_pixel_facts_cache(translator) -> PixelFactsCache | None:
    """Return the cache owned by one translator, creating it lazily."""
    if translator is None:
        return None
    cache = getattr(translator, "_pixel_facts_cache", None)
    if cache is None:
        cache = PixelFactsCache()
        setattr(translator, "_pixel_facts_cache", cache)
    if not isinstance(cache, PixelFactsCache):
        raise TypeError("Translator has an invalid pixel facts cache")
    return cache
