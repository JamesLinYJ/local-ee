"""Lower weighted neighborhood Pixel nodes to the native Float64 raster SPI."""
from __future__ import annotations

from .ir import Pixel, fail


def compile_neighborhood_pixel(graph, pixel):
    if not isinstance(pixel, Pixel) or pixel.op != "neighborhood" or len(pixel.args) != 2:
        fail("Internal neighborhood compiler received an invalid Pixel")
    operand, spec = pixel.args
    if type(spec) is not str or len(spec) > 32_768:
        fail("Neighborhood Pixel has an invalid bounded specification")
    steps = getattr(graph.t, "steps", None)
    if type(steps) is not int or steps + len(spec) > 50_000:
        fail("Neighborhood specification exceeds the shared 50000-step work budget")
    graph.t.steps = steps + len(spec)

    from ...neighborhood_spec import decode_neighborhood_spec

    try:
        decoded = decode_neighborhood_spec(spec)
    except ValueError as error:
        fail(f"Neighborhood Pixel has an invalid specification: {error}")
    if decoded["operation"] not in {
            "sum", "mean", "count", "min", "max", "variance", "stdDev",
            "sampleVariance", "sampleStdDev", "product", "median", "mode"}:
        fail("Neighborhood Pixel uses an unsupported operation")

    # The source and output queries must cover complete neighborhoods. Prove
    # each input's grid before expression() can merge any source branches.
    from .pixel_math_graph import _PixelFactsWalker

    facts = _PixelFactsWalker(graph.t).inspect(operand)
    if not facts.sources:
        fail("Neighborhood operations require a finite bound raster source")
    from .numeric_reducer_grid import require_common_grid

    require_common_grid(graph.t, (operand,), label="Image.reduceNeighborhood")

    graph.reserve_nodes(2, "Neighborhood image compilation")
    # The legacy observation selector uses Float32 callbacks. Cast the actual
    # source before first/last selection when no prior Float64 operation exists.
    input_pixel = operand if graph.has_double_precision(operand) else Pixel(
        "to_double", (operand,),
    )
    data, label, timed = graph.expression(input_pixel)
    if label is None or data is None:
        fail("Neighborhood operations require an input bound to an image grid")
    result = graph.node("local_ee_neighborhood", data=data, spec=spec)
    return result, "v", timed
