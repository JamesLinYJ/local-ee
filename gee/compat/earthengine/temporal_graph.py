"""Preserve exact local observation identity when compiling time reductions."""
from dataclasses import replace
from .ir import Pixel, _substitute, fail


def reduce_time(graph, p):
    if graph.has_double_precision(p.args[0]): fail("Float64 temporal reductions are not verified; cast after reduction or explicitly toFloat() first")
    sources = set()
    seen = set()
    def find_sources(value):
        if isinstance(value, Pixel):
            if id(value) in seen: return
            seen.add(id(value))
            if value.op == "band": sources.add(value.args[0])
            else:
                for operand in value.args: find_sources(operand)
        elif isinstance(value, tuple):
            for operand in value: find_sources(operand)
    find_sources(p.args[0])
    if len(sources) > 1: fail("Temporal reduction across distinct collection sources requires explicit alignment")
    if sources:
        source = next(iter(sources))
        if len(source.ids) > 1:
            # Upstream STAC loading truncates scene timestamps to UTC
            # days. Load each immutable item separately, then reduce an
            # explicit ordered band axis. No invented dates or lost
            # same-day observations; all runs still share one batch.
            ids = source.ids
            scenes = []
            for iid in ids:
                singleton = replace(source,ids=(iid,))
                graph.required_bands.setdefault(singleton,set()).update(graph.required_bands.get(source,source.names))
                scenes.append(Pixel("reduce_t", (_substitute(p.args[0],source,singleton), "first")))
            scenes = tuple(scenes)
            return graph.expression(Pixel("reduce_bands", (scenes,p.args[1])))
    ref, label, timed = graph.expression(p.args[0])
    if label is None: fail("Reducing an unbound constant image is unsupported")
    if not timed: fail("Image has no collection time dimension")
    reducer = graph.callback(p.args[1], {"data": {"from_parameter": "data"}, **({} if p.args[1] == "count" else {"ignore_nodata": True})})
    ref = graph.node("reduce_dimension", data=ref, dimension="t", reducer=reducer)
    if p.args[1] == "count":
        ref = graph.node("apply", data=ref, process={"process_graph": {
            "valid": {"process_id": "gt", "arguments": {"x": {"from_parameter": "x"}, "y": 0}},
            "result": {"process_id": "if", "arguments": {"value": {"from_node": "valid"}, "accept": {"from_parameter": "x"}, "reject": None}, "result": True}}})
    return ref, label, False
