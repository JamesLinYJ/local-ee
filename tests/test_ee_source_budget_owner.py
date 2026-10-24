"""New source/callback validation work cannot escape through a child graph."""
from __future__ import annotations

from types import SimpleNamespace
import pytest

from gee.compat.earthengine.callback_masks import preserve_callback_masks
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.ir import Source, UnsupportedEEError


def child_graph(count, *, owner_steps=0):
    items = [{"id": f"scene-{index}", "bbox": [0, 0, 1, 1], "properties": {}}
             for index in range(count)]
    child = Translator([], {"sentinel-2-l2a": items}, {})
    owner = SimpleNamespace(steps=owner_steps)
    graph = Graph(child, work_owner=owner)
    source = Source("sentinel-2-l2a", ("scene-0",), ("red",))
    return graph, child, owner, source


def test_source_reads_child_catalogue_but_debits_owner():
    graph, child, owner, source = child_graph(1000)
    assert graph.source(source) == {"from_node": "n0"}
    assert owner.steps > 9000
    assert child.steps == 0
    assert graph.graph["n0"]["arguments"]["_gee_item_ids"] == ["scene-0"]


def test_large_catalogue_cannot_use_an_independent_child_work_allowance():
    graph, child, owner, source = child_graph(1000, owner_steps=49_125)
    with pytest.raises(UnsupportedEEError, match="50000"):
        graph.source(source)
    assert owner.steps <= 50_000
    assert child.steps == 0
    assert graph.sources == {} and graph.graph == {}


def test_callback_guard_uses_owner_remaining_work_before_allocating():
    graph, child, owner, _source = child_graph(1, owner_steps=49_999)
    callback = {}
    with pytest.raises(UnsupportedEEError, match="50000"):
        preserve_callback_masks(graph, "gt", callback, [1, 0],
                                [(0, (None, "red", False))], "gt", {"x": 1, "y": 0})
    assert callback == {}
    assert owner.steps == 49_999 and child.steps == 0
