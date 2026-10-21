"""Precision-preserving lowering of pixel-mask operations to local SPI cubes."""
import math
from .ir import Pixel, fail


def constant(graph, data, value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or abs(value) > 2**53 or not math.isfinite(value)):
        fail("Image.unmask requires a finite Float64 constant within 2^53")
    return graph.node("local_ee_constant_on_grid", data=data, value=value)


def check_observations(pixel):
    seen = set()
    def walk(value):
        if isinstance(value, Pixel):
            if id(value) in seen: return
            seen.add(id(value))
            if value.op == "band":
                if len(value.args[0].ids) > 1:
                    fail("Image.unmask needs individual observations; use a per-image map or reduce the collection first")
            else:
                for item in value.args: walk(item)
        elif isinstance(value, tuple):
            for item in value: walk(item)
    walk(pixel)


def unmask(graph, pixel):
    data, label, timed = graph.expression(pixel.args[0])
    if label is None:
        fail("Image.unmask needs a finite local raster grid")
    if timed:
        check_observations(pixel.args[0])
    if pixel.op == "unmask_constant":
        replacement = constant(graph, data, pixel.args[1])
        same_footprint = True
    else:
        replacement, replacement_label, replacement_time = graph.expression(pixel.args[1])
        if replacement_label is None:
            # An unbound expression may fold to a scalar (e.g. constant(1).add(2)).
            # Materialize it without inheriting the input mask.
            if replacement is None:
                fail("Image.unmask replacement must be a finite numeric constant or a raster")
            replacement = constant(graph, data, replacement)
        elif replacement_time != timed:
            fail("Image.unmask needs matching spatial/temporal dimensions; broadcasting is unsupported")
        elif timed:
            check_observations(pixel.args[1])
        same_footprint = pixel.args[2]
    ref = graph.node("local_ee_unmask", data=data, value=replacement, same_footprint=same_footprint)
    return ref, label, timed
