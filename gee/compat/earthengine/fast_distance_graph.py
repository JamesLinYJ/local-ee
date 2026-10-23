"""Lower fast-distance Pixel nodes to the bounded native raster process."""
from __future__ import annotations

from .ir import Pixel, fail


_MAX_SPEC_BYTES = 1024


def compile_fast_distance_pixel(graph, pixel):
    if (type(pixel) is not Pixel or pixel.op != "fast_distance"
            or len(pixel.args) != 2):
        fail("Internal Image.fastDistanceTransform compiler received an invalid Pixel")
    operand, spec = pixel.args
    if (not isinstance(operand, Pixel) or type(spec) is not str
            or len(spec) > _MAX_SPEC_BYTES or not spec.isascii()):
        fail("Image.fastDistanceTransform Pixel has an invalid bounded specification")
    steps = getattr(graph.t, "steps", None)
    if type(steps) is not int or steps < 0 or steps + len(spec) > 50_000:
        fail("Image.fastDistanceTransform specification exceeds the shared 50000-step work budget")
    graph.t.steps = steps + len(spec)

    from ...fast_distance_spec import decode_fast_distance_spec

    try:
        decoded = decode_fast_distance_spec(spec)
    except (TypeError, ValueError, OverflowError) as error:
        fail(f"Image.fastDistanceTransform Pixel has an invalid specification: {error}")
    if (type(decoded) is not dict
            or set(decoded) != {"metric", "neighborhood", "v"}
            or decoded.get("metric") not in {
                "squared_euclidean", "manhattan", "chebyshev",
            }
            or type(decoded.get("neighborhood")) is not int
            or not 1 <= decoded["neighborhood"] <= 4096
            or decoded.get("v") != 1):
        fail("Image.fastDistanceTransform Pixel uses an unsupported specification")

    # Prove finite source support and source-grid identity before expression()
    # can materialize merge_cubes for a multi-source input.
    from .pixel_math_graph import _PixelFactsWalker

    facts = _PixelFactsWalker(graph.t).inspect(operand)
    if not facts.sources:
        fail("Image.fastDistanceTransform requires a finite bound raster source")
    from .numeric_reducer_grid import require_common_grid

    require_common_grid(graph.t, (operand,), label="Image.fastDistanceTransform")

    # The native transform guarantees one result node. Required input casts and
    # source nodes are checked by Graph.node as they are materialized.
    graph.reserve_nodes(1, "Image.fastDistanceTransform compilation")
    input_pixel = operand if graph.has_double_precision(operand) else Pixel(
        "to_double", (operand,),
    )
    data, label, timed = graph.expression(input_pixel)
    if label is None or data is None:
        fail("Image.fastDistanceTransform requires an input bound to an image grid")
    result = graph.node(
        "local_ee_fast_distance_transform", data=data, spec=spec,
    )
    return result, "v", timed
