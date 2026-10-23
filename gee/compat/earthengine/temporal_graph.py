"""Preserve exact local observation identity when compiling time reductions."""
from dataclasses import replace
from gee.reduction_contract import SINGLE_OBSERVATION_KERNELS
from .ir import Pixel, _substitute, fail


def reduce_time(graph, p):
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
    if not timed:
        from .constant_graph import is_spatialized_constant
        if is_spatialized_constant(p.args[0]):
            if p.args[1] in SINGLE_OBSERVATION_KERNELS:
                ref = graph.node("local_ee_reduce_bands", data=ref, reducer=p.args[1])
            elif p.args[1] not in {"mean", "median", "min", "max", "sum", "first", "last"}:
                fail("Unsupported constant temporal reducer")
            return ref, "v", False
        fail("Image has no collection time dimension")
    if graph.has_double_precision(p.args[0]):
        # Each occurrence is loaded independently above; the native boundary
        # additionally rejects multiple actual instants and duplicate keys.
        # Removing one verified time coordinate performs no numeric reduction.
        ref = graph.node("local_ee_drop_single_time", data=ref)
        if p.args[1] in SINGLE_OBSERVATION_KERNELS:
            ref = graph.node("local_ee_reduce_bands", data=ref, reducer=p.args[1])
        elif p.args[1] not in {"mean", "median", "min", "max", "sum", "first", "last"}:
            fail("Unsupported Float64 temporal reducer")
        return ref, "v", False
    reducer = graph.callback(p.args[1], {"data": {"from_parameter": "data"}, **({} if p.args[1] == "count" else {"ignore_nodata": True})})
    ref = graph.node("reduce_dimension", data=ref, dimension="t", reducer=reducer)
    if p.args[1] == "count":
        ref = graph.node("apply", data=ref, process={"process_graph": {
            "valid": {"process_id": "gt", "arguments": {"x": {"from_parameter": "x"}, "y": 0}},
            "result": {"process_id": "if", "arguments": {"value": {"from_node": "valid"}, "accept": {"from_parameter": "x"}, "reject": None}, "result": True}}})
    return ref, label, False
