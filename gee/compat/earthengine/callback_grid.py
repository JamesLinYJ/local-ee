"""Validate explicit asset evidence when an actual source load is created."""
from __future__ import annotations

from .ir import fail
from .numeric_reducer_grid import _charge, _item_lookup


class _AssetWork:
    """Read this child catalogue while charging the owning request ledger."""
    def __init__(self, graph):
        self.items = graph.t.items
        self.owner = graph.work_owner

    @property
    def steps(self):
        return self.owner.steps

    @steps.setter
    def steps(self, value):
        self.owner.steps = value


def validate_source_assets(graph, source):
    from .selection_grid import validate_item_assets

    names = graph.required_bands.get(source, source.names)
    _charge(graph.work_owner, 1 + len(source.ids) * (1 + len(names)))
    context = _AssetWork(graph)
    lookup = _item_lookup(context, source.cid)
    for item_id in source.ids:
        item = lookup.get(item_id)
        if item is None:
            fail("Source item is unavailable for asset grid validation")
        key = (source.cid, item_id)
        previous = graph.source_asset_bands.get(key, set())
        _charge(context, len(previous) + len(names) + 1)
        combined = previous | set(names)
        # Aliases may produce different immutable Source records for the same
        # actual item. Store selector history, never a cached grid approval;
        # each new load checks the fresh combined item evidence.
        validate_item_assets(context, item, combined)
        graph.source_asset_bands[key] = combined
    # Per-item consistency does not prove cross-observation reprojection.
