"""Lower scalar remap pixels to the trusted native cube process."""
from __future__ import annotations

from ...remap_spec import decode_remap_spec
from .ir import Image, Pixel, UnsupportedEEError, fail


MAX_TRANSLATOR_WORK = 50_000
MAX_GRAPH_NODES = 500


def compile_remap_pixel(graph, pixel):
    """Compile one input pixel and preserve the native Float64 result."""
    if not isinstance(pixel, Pixel) or pixel.op != "remap" or len(pixel.args) != 2:
        fail("Internal Image.remap Pixel is malformed")
    input_pixel, spec = pixel.args
    if not isinstance(input_pixel, Pixel) or type(spec) is not str:
        fail("Internal Image.remap Pixel requires one scalar input and a canonical specification")

    try:
        from .sampled_training import image_node_estimate, image_work_estimate

        single_band = Image([("input", input_pixel)], {})
        spec_chars = len(spec)
        work = 2 * spec_chars + image_work_estimate(single_band) + 4
        node_bound = image_node_estimate(single_band, graph.t.options) + 2
    except (TypeError, ValueError, OverflowError, RecursionError):
        fail("Image.remap exceeds the 50000-step compilation work budget")
    if work < 0 or graph.t.steps + work > MAX_TRANSLATOR_WORK:
        fail("Image.remap exceeds the 50000-step compilation work budget")
    graph.t.steps += work
    if type(node_bound) is not int or node_bound < 0:
        fail("Internal Image.remap graph estimate is malformed")
    graph.reserve_nodes(node_bound, "Image.remap")

    try:
        if not spec.isascii():
            fail("Image.remap specification must use canonical numeric JSON")
        decode_remap_spec(spec)
    except UnsupportedEEError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Image.remap specification is unsupported: {exc}")

    data, label, timed = graph.expression(input_pixel)
    if label is None or data is None:
        fail("Image.remap requires one bound scalar input band; constants and arrays are unsupported")
    result = graph.node("local_ee_remap", data=data, spec=spec)
    return result, "v", bool(timed)
