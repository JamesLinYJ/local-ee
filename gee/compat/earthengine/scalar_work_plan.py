"""Iterative, budget-bounded planning for immutable scalar Pixel closures."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from .ir import Image, Pixel, Source, fail


MAX_SCALAR_IR_DEPTH = 96
MAX_SCALAR_WORK_LEDGER_ENTRIES = 4_096

_PIXEL_LOOKUP_WORK = 1
_LOCAL_REVISIT_WORK = 1
_VALUE_LOOKUP_WORK = 1
_CONTAINER_SCAN_WORK = 1
_SOURCE_LOOKUP_WORK = 1


@dataclass(frozen=True)
class ScalarWorkPlan:
    safe: bool
    structural_work: int = 0
    inspection_work: int = 0
    pixels: tuple[tuple[Pixel, int], ...] = ()
    sources: tuple[Source, ...] = ()
    pending_entries: int = 0
    source_insert_work: int = 0


@dataclass
class _Frame:
    value: object
    depth: int
    children: Iterator | None = None
    identity: int | None = None
    max_child_height: int = 0
    cache_pixel: Pixel | None = None


def _source_is_immutable(value: object) -> bool:
    """Check field containers without walking a potentially large tuple."""
    return (
        type(value) is Source
        and type(value.cid) is str
        and type(value.ids) is tuple
        and type(value.names) is tuple
        and type(value.alias) is bool
    )


def _validate_source_members(source: Source, inspect) -> tuple[bool, int]:
    """Validate and charge one traversal of Source's immutable value fields."""
    hash_work = _SOURCE_LOOKUP_WORK + len(source.cid) + len(source.ids)
    inspect(_SOURCE_LOOKUP_WORK + len(source.cid) + len(source.ids))
    for item_id in source.ids:
        if type(item_id) is not str:
            return False, hash_work
        inspect(1 + len(item_id))
        hash_work += 1 + len(item_id)

    hash_work += len(source.names) + 1
    inspect(len(source.names) + 1)
    for name in source.names:
        if type(name) is not str:
            return False, hash_work
        inspect(len(name))
        hash_work += len(name)
    return True, hash_work


def _depth_check(depth: int, height: int) -> None:
    if depth + height - 1 > MAX_SCALAR_IR_DEPTH:
        fail(f"Scalar Image expression exceeds depth {MAX_SCALAR_IR_DEPTH}")


def plan_scalar_input_work(
    image: Image,
    ledger,
    *,
    max_inspection_work: int,
    max_cache_entries: int,
) -> ScalarWorkPlan:
    """Measure one input without mutating its Graph-local admission ledger.

    The traversal uses explicit frames, stops at admitted Pixel closures, and
    stages no more than the remaining cache capacity plus one entry. The extra
    entry is enough to decide that an all-or-none plan cannot be admitted.
    Mutable and opaque descendants make the plan unsafe; callers retain the
    unchanged complete estimator and receive no cache credit.
    """
    if (type(image) is not Image or type(image.bands) is not list
            or type(max_inspection_work) is not int or max_inspection_work < 0
            or type(max_cache_entries) is not int or max_cache_entries < 0):
        return ScalarWorkPlan(False)

    pending_stage_limit = min(
        max_cache_entries + 1, MAX_SCALAR_WORK_LEDGER_ENTRIES + 1,
    )
    pending_pixels: list[tuple[Pixel, int]] = []
    pending_sources: list[Source] = []
    pending_entries = 0
    staged_entries = 0
    source_insert_work = 0
    stage_overflow = False
    local_sources: set[Source] = set()
    validated_source_ids: set[int] = set()
    active: set[int] = set()
    heights: dict[int, int] = {}
    structural_work = 0
    inspection_work = 0
    safe = True

    def inspect(amount: int) -> None:
        nonlocal inspection_work
        if (amount < 0
                or structural_work + inspection_work + amount > max_inspection_work):
            fail("Integer Image graph exceeds the shared 50000-step work budget")
        inspection_work += amount

    def add_structural(amount: int) -> None:
        nonlocal structural_work
        if (amount < 0
                or structural_work + inspection_work + amount > max_inspection_work):
            fail("Integer Image graph exceeds the shared 50000-step work budget")
        structural_work += amount

    def stage_pixel(pixel: Pixel, height: int) -> None:
        nonlocal pending_entries, staged_entries, stage_overflow
        pending_entries += 1
        if staged_entries < pending_stage_limit:
            pending_pixels.append((pixel, height))
            staged_entries += 1
        else:
            stage_overflow = True

    def stage_source(source: Source, hash_work: int) -> None:
        nonlocal pending_entries, staged_entries, stage_overflow
        nonlocal source_insert_work
        pending_entries += 1
        source_insert_work += 1 + hash_work
        if staged_entries < pending_stage_limit:
            pending_sources.append(source)
            staged_entries += 1
        else:
            stage_overflow = True

    def finish(stack: list[_Frame], height: int) -> None:
        frame = stack.pop()
        if frame.identity is not None:
            active.remove(frame.identity)
            heights[frame.identity] = height
            if frame.cache_pixel is not None:
                stage_pixel(frame.cache_pixel, height)
        if stack:
            stack[-1].max_child_height = max(
                stack[-1].max_child_height, height,
            )

    def scan(root: object) -> None:
        nonlocal safe, structural_work
        stack = [_Frame(root, 1)]
        while stack:
            frame = stack[-1]
            if frame.children is not None:
                try:
                    child = next(frame.children)
                except StopIteration:
                    finish(stack, 1 + frame.max_child_height)
                    continue
                stack.append(_Frame(child, frame.depth + 1))
                continue

            value = frame.value
            if frame.depth > MAX_SCALAR_IR_DEPTH:
                fail(f"Scalar Image expression exceeds depth {MAX_SCALAR_IR_DEPTH}")

            if type(value) in (type(None), bool, int, float, str, bytes):
                inspect(_VALUE_LOOKUP_WORK)
                finish(stack, 0)
                continue

            if _source_is_immutable(value):
                inspect(_VALUE_LOOKUP_WORK)
                if id(value) not in validated_source_ids:
                    valid_source, _hash_work = _validate_source_members(value, inspect)
                    if valid_source:
                        validated_source_ids.add(id(value))
                    else:
                        safe = False
                finish(stack, 0)
                continue

            if isinstance(value, Source):
                safe = False
                inspect(_VALUE_LOOKUP_WORK)
                finish(stack, 0)
                continue

            if isinstance(value, Pixel):
                identity = id(value)
                if identity in active:
                    fail("Cyclic scalar Image expression is unsupported")

                cached_height = (
                    ledger.pixel_height(value)
                    if ledger is not None and type(value) is Pixel else None
                )
                if cached_height is not None:
                    inspect(_PIXEL_LOOKUP_WORK)
                    _depth_check(frame.depth, cached_height)
                    finish(stack, cached_height)
                    continue

                known_height = heights.get(identity)
                if known_height is not None:
                    inspect(_LOCAL_REVISIT_WORK)
                    _depth_check(frame.depth, known_height)
                    finish(stack, known_height)
                    continue

                inspect(_PIXEL_LOOKUP_WORK)
                exact_pixel = type(value) is Pixel
                valid_pixel = (
                    exact_pixel and type(value.op) is str
                    and type(value.args) is tuple
                    and type(value.boolean) is bool
                )
                if not valid_pixel:
                    safe = False

                args = value.args
                if valid_pixel:
                    add_structural(1 + len(value.op))
                    if value.op == "band":
                        if (len(args) != 2 or not _source_is_immutable(args[0])
                                or type(args[1]) is not str):
                            safe = False
                        else:
                            source, band_name = args
                            valid_source, source_hash_work = _validate_source_members(
                                source, inspect,
                            )
                            if not valid_source:
                                safe = False
                            else:
                                validated_source_ids.add(id(source))
                            add_structural(len(band_name))
                            if valid_source and source not in local_sources:
                                # The first member scan pays the local-set
                                # membership hash; charge each subsequent
                                # insertion/global lookup before doing it.
                                inspect(source_hash_work)
                                local_sources.add(source)
                                is_in_ledger = False
                                if ledger is not None:
                                    inspect(source_hash_work)
                                    is_in_ledger = ledger.source_hit(source)
                                if not is_in_ledger:
                                    add_structural(
                                        1 + len(source.cid)
                                        + sum(map(len, source.ids))
                                    )
                                    stage_source(source, source_hash_work)
                    if (value.op == "remap" and len(args) == 2
                            and type(args[1]) is str):
                        add_structural(6 * len(args[1]) + 1)

                if isinstance(args, (tuple, list)):
                    if type(args) is not tuple:
                        safe = False
                    inspect(_CONTAINER_SCAN_WORK + len(args))
                    active.add(identity)
                    frame.identity = identity
                    frame.cache_pixel = value if valid_pixel else None
                    frame.children = iter(args)
                    continue

                # The full estimator remains authoritative for malformed or
                # opaque Pixel arguments and will reject non-iterable values.
                finish(stack, 1)
                continue

            if isinstance(value, (tuple, list)):
                identity = id(value)
                if identity in active:
                    fail("Cyclic scalar Image expression is unsupported")
                known_height = heights.get(identity)
                if known_height is not None:
                    inspect(_LOCAL_REVISIT_WORK)
                    _depth_check(frame.depth, known_height)
                    finish(stack, known_height)
                    continue

                if type(value) is not tuple:
                    safe = False
                inspect(_CONTAINER_SCAN_WORK + len(value))
                active.add(identity)
                frame.identity = identity
                frame.children = iter(value)
                continue

            # Models, Images, dicts, SDK objects, and all other values retain
            # the full-estimator path. In particular this leaves classifier
            # lineage accounting and special model terms unchanged.
            safe = False
            inspect(_VALUE_LOOKUP_WORK)
            finish(stack, 0)

    try:
        for band in image.bands:
            if type(band) is not tuple or len(band) != 2 or type(band[0]) is not str:
                return ScalarWorkPlan(
                    False, inspection_work=inspection_work,
                )
            scan(band[1])
    except (TypeError, ValueError, OverflowError):
        raise

    if not safe:
        return ScalarWorkPlan(
            False, inspection_work=inspection_work,
        )

    # If the full plan cannot fit, stage no partial ancestor closure. The
    # count is exact; temporary candidate storage is capped at remaining+1.
    if pending_entries > max_cache_entries or stage_overflow:
        pending_pixels.clear()
        pending_sources.clear()
    return ScalarWorkPlan(
        True,
        structural_work,
        inspection_work,
        tuple(pending_pixels),
        tuple(pending_sources),
        pending_entries,
        source_insert_work,
    )


__all__ = [
    "MAX_SCALAR_IR_DEPTH",
    "ScalarWorkPlan",
    "plan_scalar_input_work",
]
