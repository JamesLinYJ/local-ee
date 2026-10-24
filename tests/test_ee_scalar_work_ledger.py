"""Bounded scalar-work admissions preserve full validation and graph limits."""
from __future__ import annotations

import gc
import weakref

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.ir import (
    DynamicMinimumDistance,
    Image,
    Pixel,
    SampledFeatures,
    Source,
)
from gee.compat.earthengine.sampled_training import image_work_estimate
from gee.compat.earthengine.scalar_work_ledger import (
    MAX_SCALAR_WORK,
    MAX_SCALAR_WORK_LEDGER_ENTRIES,
    ScalarWorkLedger,
    reserve_scalar_input_work,
)
from gee.compat.earthengine.scalar_work_plan import plan_scalar_input_work
from gee.ee_translate import UnsupportedEEError


def _graph(steps: int = 0) -> Graph:
    graph = Graph(Translator([], {}, {}))
    graph.t.steps = steps
    return graph


def _image(pixel: Pixel, name: str = "value") -> Image:
    return Image([(name, pixel)], {})


def _band_pixel(source: Source | None = None) -> Pixel:
    source = source or Source("local", ("scene",), ("value",))
    return Pixel("to_double", (Pixel("band", (source, "value")),))


def _charge(graph: Graph, image: Image, spec: str = "spec") -> int:
    before = graph.t.steps
    reserve_scalar_input_work(graph, image, spec)
    return graph.t.steps - before


def test_reuses_only_admitted_pixel_identity_and_is_graph_local():
    pixel = _band_pixel()
    image = _image(pixel)
    first_graph = _graph()

    first = _charge(first_graph, image)
    repeated = _charge(first_graph, image)
    assert first_graph._scalar_work_ledger.pixel_height(pixel) is not None
    assert repeated < first

    equal_but_distinct = Pixel(pixel.op, pixel.args)
    assert equal_but_distinct == pixel
    assert equal_but_distinct is not pixel
    distinct_cost = _charge(first_graph, _image(equal_but_distinct))
    assert distinct_cost > repeated

    other_graph = _graph()
    assert _charge(other_graph, image) == first
    assert other_graph._scalar_work_ledger is not first_graph._scalar_work_ledger


def test_source_accounting_is_value_keyed_for_equal_distinct_sources():
    source_a = Source("local", ("scene",), ("value",))
    source_b = Source("local", ("scene",), ("value",))
    assert source_a == source_b and source_a is not source_b

    graph = _graph()
    first = Pixel("band", (source_a, "value"))
    second = Pixel("band", (source_b, "value"))
    _charge(graph, _image(first))
    pending = plan_scalar_input_work(
        _image(second),
        graph._scalar_work_ledger,
        max_inspection_work=MAX_SCALAR_WORK,
        max_cache_entries=graph._scalar_work_ledger.available_entries,
    )
    # The Pixel and band label are new, while the equal Source's original
    # first-seen estimator term is already admitted by value.
    assert pending.structural_work == 1 + len("band") + len("value")
    warm_cost = _charge(graph, _image(second))

    assert graph._scalar_work_ledger.source_hit(source_b)
    assert graph._scalar_work_ledger.entries == 3  # two Pixels, one Source value
    assert warm_cost > 0


def test_mutable_descendant_uses_full_estimator_without_admission():
    image = _image(Pixel("add", ([Pixel("constant", (3,))], 1)))
    graph = _graph()
    overhead = 2 * len("spec") + 8 + 3 + len("value")

    first = _charge(graph, image)
    assert first > overhead + image_work_estimate(image)
    assert not hasattr(graph, "_scalar_work_ledger")
    second = _charge(graph, image)
    assert second == first
    assert not hasattr(graph, "_scalar_work_ledger")


def test_opaque_classifier_keeps_special_estimator_lineage_costs():
    source = Source("local", ("scene",), ("value",))
    target = Pixel("band", (source, "value"))
    samples = SampledFeatures(_image(target), "sample-spec", ("limit",))
    model = DynamicMinimumDistance(samples, "euclidean", ("value",), "class")
    image = _image(Pixel("trained_classify", (target, model)))
    graph = _graph()
    overhead = 2 * len("spec") + 8 + 3 + len("value")

    charged = _charge(graph, image)
    assert charged > overhead + image_work_estimate(image)
    assert not hasattr(graph, "_scalar_work_ledger")


def test_cached_subtree_height_cannot_bypass_depth_limit():
    inner = _band_pixel()
    for _ in range(20):
        inner = Pixel("to_float", (inner,))
    graph = _graph()
    _charge(graph, _image(inner))
    ledger = graph._scalar_work_ledger
    before_steps, before_entries = graph.t.steps, ledger.entries

    outer = inner
    for _ in range(76):
        outer = Pixel("to_float", (outer,))
    outer_image = _image(outer)
    with pytest.raises(UnsupportedEEError, match="depth 96"):
        plan_scalar_input_work(
            outer_image,
            ledger,
            max_inspection_work=MAX_SCALAR_WORK,
            max_cache_entries=ledger.available_entries,
        )
    with pytest.raises(UnsupportedEEError):
        reserve_scalar_input_work(graph, outer_image, "spec")
    assert graph.t.steps == before_steps
    assert ledger.entries == before_entries


def test_cycles_and_near_budget_fail_without_admitting_new_pixels():
    cyclic = object.__new__(Pixel)
    object.__setattr__(cyclic, "op", "to_float")
    object.__setattr__(cyclic, "args", (cyclic,))
    object.__setattr__(cyclic, "boolean", False)
    graph = _graph()
    with pytest.raises(UnsupportedEEError):
        reserve_scalar_input_work(graph, _image(cyclic), "spec")
    assert graph.t.steps == 0
    assert not hasattr(graph, "_scalar_work_ledger")

    image = _image(_band_pixel())
    measured = _charge(_graph(), image)
    almost = _graph(MAX_SCALAR_WORK - measured + 1)
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        reserve_scalar_input_work(almost, image, "spec")
    assert almost.t.steps == MAX_SCALAR_WORK - measured + 1
    assert not hasattr(almost, "_scalar_work_ledger")

    exact = _graph(MAX_SCALAR_WORK - measured)
    assert _charge(exact, image) == measured
    assert exact.t.steps == MAX_SCALAR_WORK


def test_node_preflight_is_repeated_even_when_pixel_is_warm():
    class CountingGraph(Graph):
        def __init__(self):
            super().__init__(Translator([], {}, {}))
            self.reservations = []

        def reserve_nodes(self, count, label="Compiled process graph"):
            self.reservations.append((count, label))
            return super().reserve_nodes(count, label)

    graph = CountingGraph()
    image = _image(_band_pixel())
    _charge(graph, image)
    _charge(graph, image)
    assert graph.reservations == [
        (7, "Integer Image operation"),
        (7, "Integer Image operation"),
    ]

    graph.graph = {f"n{index}": {} for index in range(496)}
    before = graph.t.steps
    with pytest.raises(UnsupportedEEError, match="500-node"):
        reserve_scalar_input_work(graph, image, "spec")
    assert graph.t.steps == before
    assert len(graph.reservations) == 3


def test_ledger_holds_strong_references_and_stops_at_configured_cap():
    ledger = ScalarWorkLedger(max_entries=1)
    graph = _graph()
    graph._scalar_work_ledger = ledger
    pixel = Pixel("constant", (4,))
    ref = weakref.ref(pixel)
    _charge(graph, _image(pixel))
    del pixel
    gc.collect()
    assert ref() is not None
    assert ledger.entries == 1

    second = Pixel("constant", (5,))
    _charge(graph, _image(second))
    assert ledger.entries == 1
    assert ledger.pixel_height(second) is None

    with pytest.raises(ValueError):
        ScalarWorkLedger(max_entries=0)
    with pytest.raises(ValueError):
        ScalarWorkLedger(max_entries=MAX_SCALAR_WORK_LEDGER_ENTRIES + 1)
