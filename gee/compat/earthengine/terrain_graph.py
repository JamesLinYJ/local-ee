"""Lower terrain Pixel nodes to the native local_ee_terrain raster process."""
from __future__ import annotations

from .ir import Pixel, fail


_MAX_SPEC_BYTES = 1_024
_OPERATIONS = frozenset({"slope", "aspect", "hillshade"})


def compile_terrain_pixel(graph, pixel):
    if (type(pixel) is not Pixel or pixel.op != "terrain"
            or len(pixel.args) != 2):
        fail("Internal Terrain compiler received an invalid Pixel")
    operand, spec = pixel.args
    if (type(spec) is not str or len(spec) > _MAX_SPEC_BYTES
            or not spec.isascii()):
        fail("Terrain Pixel has an invalid bounded specification")
    steps = getattr(graph.t, "steps", None)
    if type(steps) is not int or steps + len(spec) > 50_000:
        fail("Terrain specification exceeds the shared 50000-step work budget")
    graph.t.steps = steps + len(spec)

    from ...terrain_spec import decode_terrain_spec

    try:
        decoded = decode_terrain_spec(spec)
    except (TypeError, ValueError, OverflowError) as error:
        fail(f"Terrain Pixel has an invalid specification: {error}")
    if type(decoded) is not dict or decoded.get("operation") not in _OPERATIONS:
        fail("Terrain Pixel uses an unsupported operation")

    # A terrain neighborhood has no useful meaning for constants or opaque
    # values. Prove the actual selected elevation expression and its source
    # grid before compiling any node that may merge source cubes.
    from .pixel_math_graph import _PixelFactsWalker

    facts = _PixelFactsWalker(graph.t).inspect(operand)
    if not facts.sources:
        fail("Terrain requires a finite bound raster source")
    from .numeric_reducer_grid import require_common_grid

    require_common_grid(graph.t, (operand,), label="Terrain")

    graph.reserve_nodes(2, "Terrain image compilation")
    # Legacy observation selection passes through Float32 callbacks. Cast the
    # source before first/last selection so the native derivative sees its
    # actual Float64 elevation values.
    input_pixel = operand if graph.has_double_precision(operand) else Pixel(
        "to_double", (operand,),
    )
    data, label, timed = graph.expression(input_pixel)
    if label is None or data is None:
        fail("Terrain requires an input bound to an image grid")
    result = graph.node("local_ee_terrain", data=data, spec=spec)
    return result, "v", timed
