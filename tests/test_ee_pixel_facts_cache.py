from __future__ import annotations

import gc
import weakref
from types import SimpleNamespace

import pytest

from gee.compat.earthengine.ir import Pixel, Source, UnsupportedEEError
from gee.compat.earthengine.pixel_facts_cache import (
    PixelFactsCache,
    translator_pixel_facts_cache,
)
from gee.compat.earthengine.pixel_math_graph import _PixelFactsWalker


def _source(name: str) -> Source:
    return Source(name, (f"{name}-item",), ("band",))


def _translator(cache: PixelFactsCache | None = None):
    translator = SimpleNamespace(steps=0)
    if cache is not None:
        translator._pixel_facts_cache = cache
    return translator


def test_repeated_immutable_dag_uses_shared_cache_and_charges_hits():
    source = _source("a")
    band = Pixel("band", (source, "x"))
    shared = Pixel("scale", (band, 2))
    root = Pixel("add", (shared, shared))
    translator = _translator()

    first_facts = _PixelFactsWalker(translator).inspect(root)
    first_work = translator.steps
    cache = translator_pixel_facts_cache(translator)
    assert cache is not None and cache.contains_identity(root)

    before_hit = translator.steps
    second_facts = _PixelFactsWalker(translator).inspect(root)
    hit_work = translator.steps - before_hit

    assert second_facts == first_facts
    assert 0 < hit_work < first_work


def test_mutable_descendant_prevents_ancestor_cache_and_refreshes_facts():
    source_a = _source("a")
    source_b = _source("b")
    band_a = Pixel("band", (source_a, "x"))
    band_b = Pixel("band", (source_b, "x"))
    children = [band_a]
    root = Pixel("container", (children,))
    translator = _translator()

    first = _PixelFactsWalker(translator).inspect(root)
    cache = translator_pixel_facts_cache(translator)
    assert first.sources == ((source_a.cid, source_a.ids),)
    assert cache is not None and not cache.contains_identity(root)

    children[:] = [band_b]
    second = _PixelFactsWalker(translator).inspect(root)
    assert second.sources == ((source_b.cid, source_b.ids),)
    assert not cache.contains_identity(root)


def test_mutable_pixel_args_list_refreshes_facts_across_walkers():
    source_a = _source("a")
    source_b = _source("b")
    args = [Pixel("band", (source_a, "x"))]
    root = Pixel("container", args)
    translator = _translator()

    first = _PixelFactsWalker(translator).inspect(root)
    cache = translator_pixel_facts_cache(translator)
    assert first.sources == ((source_a.cid, source_a.ids),)
    assert cache is not None and not cache.contains_identity(root)

    args[:] = [Pixel("band", (source_b, "x"))]
    second = _PixelFactsWalker(translator).inspect(root)
    assert second.sources == ((source_b.cid, source_b.ids),)
    assert not cache.contains_identity(root)


@pytest.mark.parametrize("mutable_or_unknown", [[], {}, object()])
def test_nested_mutable_or_unknown_value_prevents_tuple_and_pixel_cache(
    mutable_or_unknown,
):
    nested = (mutable_or_unknown,)
    root = Pixel("container", (nested,))
    translator = _translator()

    _PixelFactsWalker(translator).inspect(root)
    cache = translator_pixel_facts_cache(translator)

    assert cache is not None
    assert not cache.contains_identity(nested)
    assert not cache.contains_identity(root)


def test_cycle_after_cached_sibling_is_rejected_before_cache_reuse():
    sibling = Pixel("scale", (Pixel("band", (_source("a"), "x")), 2))
    translator = _translator()
    _PixelFactsWalker(translator).inspect(sibling)
    cache = translator_pixel_facts_cache(translator)
    assert cache is not None and cache.contains_identity(sibling)

    root = Pixel("add", (sibling,))
    object.__setattr__(root, "args", (sibling, root))
    with pytest.raises(UnsupportedEEError, match="Cyclic pixel expression"):
        _PixelFactsWalker(translator).inspect(root)


def test_cached_facts_preserve_first_seen_source_order():
    source_a = _source("a")
    source_b = _source("b")
    root = Pixel("combine", (
        Pixel("band", (source_a, "x")),
        Pixel("band", (source_b, "x")),
    ))
    translator = _translator()
    first = _PixelFactsWalker(translator).inspect(root)
    second = _PixelFactsWalker(translator).inspect(root)

    assert first.sources == ((source_a.cid, source_a.ids), (source_b.cid, source_b.ids))
    assert second.sources == first.sources


def test_cache_is_translator_scoped():
    root = Pixel("scale", (Pixel("band", (_source("a"), "x")), 2))
    first_translator = _translator()
    second_translator = _translator()

    _PixelFactsWalker(first_translator).inspect(root)
    first_work = first_translator.steps
    _PixelFactsWalker(second_translator).inspect(root)
    second_work = second_translator.steps

    first_cache = translator_pixel_facts_cache(first_translator)
    second_cache = translator_pixel_facts_cache(second_translator)
    assert first_cache is not second_cache
    assert second_work == first_work


def test_bounded_cache_evicts_lru_and_holds_strong_references():
    cache = PixelFactsCache(max_entries=2)
    translator = _translator(cache)
    first = Pixel("scalar", (1,))
    second = Pixel("scalar", (2,))
    third = Pixel("scalar", (3,))
    first_ref = weakref.ref(first)
    second_ref = weakref.ref(second)

    walker = _PixelFactsWalker(translator)
    walker.inspect(first)
    walker.inspect(second)
    del walker
    _PixelFactsWalker(translator).inspect(first)  # promote first above second
    _PixelFactsWalker(translator).inspect(third)  # evict second

    assert cache.contains_identity(first)
    assert not cache.contains_identity(second)
    assert cache.contains_identity(third)
    del first, second
    gc.collect()
    assert first_ref() is not None  # cache retains the unevicted object
    assert second_ref() is None  # eviction releases its only strong reference


def test_cached_hit_charges_work_and_rejects_past_exact_limit():
    root = Pixel("scalar", (1,))
    translator = _translator()
    _PixelFactsWalker(translator).inspect(root)

    translator.steps = 49_998
    _PixelFactsWalker(translator).inspect(root)
    assert translator.steps == 50_000

    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        _PixelFactsWalker(translator).inspect(root)
    assert translator.steps == 49_999


@pytest.mark.parametrize("limit", [True, -1, 0, 4097])
def test_cache_constructor_cannot_exceed_the_fixed_entry_cap(limit):
    with pytest.raises(ValueError, match="4096"):
        PixelFactsCache(max_entries=limit)
