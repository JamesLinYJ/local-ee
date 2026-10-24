"""Bounded Graph-local work admission for immutable scalar raster IR."""
from __future__ import annotations

from .ir import Image, Pixel, Source, fail
from .sampled_training import image_node_estimate, image_work_estimate
from .scalar_work_plan import (
    MAX_SCALAR_IR_DEPTH,
    ScalarWorkPlan,
    plan_scalar_input_work,
)


MAX_SCALAR_WORK = 50_000
MAX_SCALAR_WORK_LEDGER_ENTRIES = 4_096

# Work units for ledger lookup, capacity checking, and committed entries.
_LEDGER_CAPACITY_CHECK_WORK = 1
_LEDGER_INSERT_WORK = 1


class ScalarWorkLedger:
    """Append-only strong-identity Pixel and value-keyed Source admissions.

    A Pixel entry records the height of its complete, deeply immutable
    descendant closure. Entry values hold strong references, so an ``id`` can
    never be reused while the entry remains live. At capacity the ledger
    stops admitting new plans; existing entries remain usable.
    """

    def __init__(self, max_entries: int = MAX_SCALAR_WORK_LEDGER_ENTRIES):
        if (type(max_entries) is not int
                or not 1 <= max_entries <= MAX_SCALAR_WORK_LEDGER_ENTRIES):
            raise ValueError(
                "Scalar work ledger limit must be an integer from 1 through 4096"
            )
        self.max_entries = max_entries
        self._pixels: dict[int, tuple[Pixel, int]] = {}
        self._sources: set[Source] = set()

    def pixel_height(self, value: Pixel) -> int | None:
        entry = self._pixels.get(id(value))
        if entry is not None and entry[0] is value:
            return entry[1]
        return None

    def source_hit(self, value: Source) -> bool:
        return value in self._sources

    @property
    def entries(self) -> int:
        return len(self._pixels) + len(self._sources)

    @property
    def available_entries(self) -> int:
        return self.max_entries - self.entries

    def admit(self, pixels: tuple[tuple[Pixel, int], ...],
              sources: tuple[Source, ...]) -> None:
        """Commit a fully paid, fully validated plan."""
        for pixel, height in pixels:
            self._pixels[id(pixel)] = (pixel, height)
        self._sources.update(sources)


def _failed_work_budget() -> None:
    fail("Integer Image graph exceeds the shared 50000-step work budget")


def _call_work(spec: str, input_image: Image) -> int:
    """Preserve the per-call, specification, and Image-band wrapper charge."""
    return (
        2 * len(spec) + 8 + 3 * len(input_image.bands)
        + sum(len(name) for name, _pixel in input_image.bands)
    )


def _reserve_budget(translator, amount: int) -> None:
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or steps < 0 or amount < 0
            or steps + amount > MAX_SCALAR_WORK):
        _failed_work_budget()
    translator.steps = steps + amount


def _plan_work(plan: ScalarWorkPlan, call_work: int,
               ledger: ScalarWorkLedger | None) -> tuple[int, bool]:
    if not plan.safe:
        # The original estimator retains all special classifier, remap,
        # Source, and malformed-IR terms. The planner's scan is additive.
        return (
            call_work + plan.inspection_work, False,
        )

    work = call_work + plan.structural_work + plan.inspection_work
    if plan.pending_entries:
        available = (
            MAX_SCALAR_WORK_LEDGER_ENTRIES if ledger is None
            else ledger.available_entries
        )
        work += _LEDGER_CAPACITY_CHECK_WORK
        should_admit = plan.pending_entries <= available
        if should_admit:
            work += (
                len(plan.pixels) * _LEDGER_INSERT_WORK
                + plan.source_insert_work
            )
        return work, should_admit
    return work, False


def reserve_scalar_input_work(graph, input_image: Image, spec: str) -> None:
    """Preflight nodes and charge this numeric operation's bounded input work.

    The source/catalog/grid proof remains the caller's responsibility. Every
    call still pays its full specification and band-wrapper allowance and
    performs the original node preflight. Only fully immutable Pixel closures
    can receive graph-local credit; other values use the original estimator.
    """
    try:
        node_bound = image_node_estimate(input_image, graph.t.options)
    except (TypeError, ValueError, OverflowError, RecursionError):
        _failed_work_budget()
    if type(node_bound) is not int or node_bound < 0:
        _failed_work_budget()
    graph.reserve_nodes(node_bound, "Integer Image operation")

    if type(spec) is not str:
        _failed_work_budget()

    ledger = getattr(graph, "_scalar_work_ledger", None)
    if ledger is not None and not isinstance(ledger, ScalarWorkLedger):
        _failed_work_budget()

    try:
        call_work = _call_work(spec, input_image)
        steps = getattr(graph.t, "steps", None)
        if type(steps) is not int or steps < 0:
            _failed_work_budget()
        if call_work > MAX_SCALAR_WORK - steps:
            _failed_work_budget()

        available_for_scan = MAX_SCALAR_WORK - steps - call_work
        plan = plan_scalar_input_work(
            input_image,
            ledger,
            max_inspection_work=available_for_scan,
            max_cache_entries=(
                MAX_SCALAR_WORK_LEDGER_ENTRIES if ledger is None
                else ledger.available_entries
            ),
        )
        if plan.safe:
            work, should_admit = _plan_work(plan, call_work, ledger)
        else:
            # Planner-only inspection has already happened. Preserve the
            # unchanged full estimator for unsafe or mutable descendants.
            fallback_work = image_work_estimate(input_image)
            work = call_work + fallback_work + plan.inspection_work
            should_admit = False
    except (TypeError, ValueError, OverflowError, RecursionError):
        _failed_work_budget()

    # All new structural, scan, and insertion work is paid before the ledger
    # is changed. Failed near-budget admissions therefore leave no cache hit
    # behind for a later operation.
    if type(steps) is not int or steps < 0 or steps + work > MAX_SCALAR_WORK:
        _failed_work_budget()
    _reserve_budget(graph.t, work)
    if should_admit:
        if ledger is None:
            ledger = ScalarWorkLedger()
            graph._scalar_work_ledger = ledger
        ledger.admit(plan.pixels, plan.sources)


__all__ = [
    "MAX_SCALAR_IR_DEPTH",
    "MAX_SCALAR_WORK",
    "MAX_SCALAR_WORK_LEDGER_ENTRIES",
    "ScalarWorkLedger",
    "reserve_scalar_input_work",
]
