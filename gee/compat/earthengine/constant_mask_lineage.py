"""Bounded source-lineage preflight for weighted Image bands."""
from __future__ import annotations

from dataclasses import dataclass

from .ir import Pixel, Source, fail
from .scalar_work_plan import MAX_SCALAR_IR_DEPTH


_MAX_WORK = 50_000
_MAX_DEPTH = MAX_SCALAR_IR_DEPTH
_SCIENCE_INPUTS = frozenset({
    "mask_guard", "mask_set_value", "mask_apply", "mask_result_value",
})
_IMMUTABLE_ERROR = "Constant mask binding requires an immutable finite pixel expression"


@dataclass(frozen=True)
class MaskLineage:
    any_raster: bool
    science_raster: bool
    first_science_source: Source | None
    work: int


def scan_mask_lineage(pixel: Pixel, translator) -> MaskLineage:
    """Preflight all Pixel/tuple paths while treating geometry literals as leaves.

    This is only a lineage probe. Actual raster carriers remain unchanged and
    keep their normal downstream geometry, clipping, and source validation.
    Closed constant carriers still go through the stricter scalar planner.
    """
    steps = getattr(translator, "steps", None)
    if type(steps) is not int or steps < 0 or steps > _MAX_WORK:
        fail("Constant mask binding requires the shared50000-step work budget")

    work = 0
    remaining = _MAX_WORK - steps

    def charge(amount: int) -> None:
        nonlocal work
        if amount < 0 or work + amount > remaining:
            fail("Constant mask binding exceeds the shared50000-step compilation work budget")
        work += amount

    active: set[int] = set()
    memo: dict[int, tuple[object, bool, bool, Source | None, int]] = {}

    def visit(value, depth: int) -> tuple[bool, bool, Source | None, int]:
        if depth > _MAX_DEPTH:
            fail("Constant mask binding exceeds the depth 96 limit")

        if type(value) is Pixel:
            key = id(value)
            cached = memo.get(key)
            if cached is not None and cached[0] is value:
                charge(1)
                _check_occurrence_depth(depth, cached[4])
                return cached[1], cached[2], cached[3], cached[4]
            if key in active:
                fail("Cyclic constant mask expression is unsupported")
            if (type(value.op) is not str or type(value.args) is not tuple
                    or type(value.boolean) is not bool):
                fail(_IMMUTABLE_ERROR)
            charge(1 + len(value.op) + len(value.args))
            if value.op == "band" and (
                    len(value.args) != 2 or type(value.args[0]) is not Source
                    or type(value.args[1]) is not str):
                fail(_IMMUTABLE_ERROR)

            active.add(key)
            any_raster = value.op == "band"
            science_raster = value.op == "band"
            first_science_source = value.args[0] if value.op == "band" else None
            height = 1
            science_indices = (0,) if value.op == "with_mask" or value.op in _SCIENCE_INPUTS else None
            for index, child in enumerate(value.args):
                child_any, child_science, child_source, child_height = visit(child, depth + 1)
                any_raster = any_raster or child_any
                if science_indices is None or index in science_indices:
                    science_raster = science_raster or child_science
                    if first_science_source is None:
                        first_science_source = child_source
                height = max(height, 1 + child_height)
            active.remove(key)
            memo[key] = (value, any_raster, science_raster, first_science_source, height)
            return any_raster, science_raster, first_science_source, height

        if type(value) in (tuple, list):
            key = id(value)
            cached = memo.get(key)
            if cached is not None and cached[0] is value:
                charge(1)
                _check_occurrence_depth(depth, cached[4])
                return cached[1], cached[2], cached[3], cached[4]
            if key in active:
                fail("Cyclic constant mask expression is unsupported")
            charge(1 + len(value))
            active.add(key)
            any_raster = False
            science_raster = False
            first_science_source = None
            height = 1
            for child in value:
                child_any, child_science, child_source, child_height = visit(child, depth + 1)
                any_raster = any_raster or child_any
                science_raster = science_raster or child_science
                if first_science_source is None:
                    first_science_source = child_source
                height = max(height, 1 + child_height)
            active.remove(key)
            memo[key] = (value, any_raster, science_raster, first_science_source, height)
            return any_raster, science_raster, first_science_source, height

        # Source records are immutable leaves but their members still count
        # toward the shared work budget. Geometry dictionaries are opaque here:
        # their authoritative validation belongs to the downstream clip path.
        charge(1 + len(value) if type(value) in (str, bytes) else 1)
        if type(value) is Source:
            from .scalar_work_plan import _source_is_immutable, _validate_source_members

            if not _source_is_immutable(value):
                fail(_IMMUTABLE_ERROR)
            valid, _ = _validate_source_members(value, charge)
            if not valid:
                fail(_IMMUTABLE_ERROR)
        # Leaves occupy their own depth slot. Including that slot in cached
        # subtree heights makes a memo hit equivalent to traversing its scalar
        # or Source child at every occurrence.
        return False, False, None, 1

    any_raster, science_raster, first_science_source, _height = visit(pixel, 1)
    # Charge the successful full scan before the caller returns or begins any
    # later validation/materialization. The scanner itself is capped as it runs.
    translator.steps = steps + work
    return MaskLineage(any_raster, science_raster, first_science_source, work)


def _check_occurrence_depth(depth: int, height: int) -> None:
    if depth + height - 1 > _MAX_DEPTH:
        fail("Constant mask binding exceeds the depth 96 limit")
