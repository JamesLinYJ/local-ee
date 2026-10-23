"""Lower distance Pixel nodes to the native local_ee_distance raster process."""
from __future__ import annotations

from .ir import Pixel, fail


_MAX_SPEC_BYTES = 1_024


def compile_distance_pixel(graph, pixel):
    if (type(pixel) is not Pixel or pixel.op != "distance"
            or len(pixel.args) != 2):
        fail("Internal Image.distance compiler received an invalid Pixel")
    operand, spec = pixel.args
    if (type(spec) is not str or len(spec) > _MAX_SPEC_BYTES
            or not spec.isascii()):
        fail("Image.distance Pixel has an invalid bounded specification")
    steps = getattr(graph.t, "steps", None)
    if type(steps) is not int or steps + len(spec) > 50_000:
        fail("Image.distance specification exceeds the shared 50000-step work budget")
    graph.t.steps = steps + len(spec)

    from ...distance_spec import decode_distance_spec

    try:
        decoded = decode_distance_spec(spec)
    except (TypeError, ValueError, OverflowError) as error:
        fail(f"Image.distance Pixel has an invalid specification: {error}")
    if (type(decoded) is not dict
            or set(decoded) != {"metric", "radius", "skip_masked", "v"}
            or decoded.get("metric") not in {"euclidean", "manhattan", "chebyshev"}
            or decoded.get("v") != 1
            or type(decoded.get("skip_masked")) is not bool):
        fail("Image.distance Pixel uses an unsupported specification")

    # Prove source support and grid identity before expression() can materialize
    # any merge_cubes nodes for a multi-source operand.
    from .pixel_math_graph import _PixelFactsWalker

    facts = _PixelFactsWalker(graph.t).inspect(operand)
    if not facts.sources:
        fail("Image.distance requires a finite bound raster source")
    from .numeric_reducer_grid import require_common_grid

    require_common_grid(graph.t, (operand,), label="Image.distance")

    # The distance process itself is the one guaranteed new node. Any required
    # cast or input nodes are checked as they are materialized, so reserving
    # them here would reject a cached operand near the graph limit.
    graph.reserve_nodes(1, "Image.distance compilation")
    # Legacy time selection and raster callbacks can narrow through Float32.
    # Widen first and hand the native metric process actual Float64 cells.
    input_pixel = operand if graph.has_double_precision(operand) else Pixel(
        "to_double", (operand,),
    )
    data, label, timed = graph.expression(input_pixel)
    if label is None or data is None:
        fail("Image.distance requires an input bound to an image grid")
    result = graph.node("local_ee_distance", data=data, spec=spec)
    return result, "v", timed
