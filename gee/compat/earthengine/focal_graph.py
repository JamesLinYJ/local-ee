"""Lower bounded focal Pixel nodes to the dedicated native raster SPI."""
from __future__ import annotations

from .ir import Pixel, fail


def compile_focal_pixel(graph, pixel):
    if not isinstance(pixel, Pixel) or pixel.op != "focal" or len(pixel.args) != 2:
        fail("Internal focal compiler received an invalid Pixel")
    operand, spec = pixel.args
    if type(spec) is not str or len(spec) > 32_768:
        fail("Focal Pixel has an invalid bounded specification")
    steps = getattr(graph.t, "steps", None)
    if type(steps) is not int or steps + len(spec) > 50_000:
        fail("Focal specification exceeds the shared 50000-step work budget")
    graph.t.steps = steps + len(spec)

    from ...focal_spec import decode_focal_spec

    try:
        decoded = decode_focal_spec(spec)
    except ValueError as error:
        fail(f"Focal Pixel has an invalid specification: {error}")
    if decoded["operation"] not in {"mean", "min", "max", "median", "mode"}:
        fail("Focal Pixel uses an unsupported operation")

    # The input may itself combine source bands. Prove their existing grids
    # before graph.expression can materialize any merge_cubes nodes.
    from .pixel_math_graph import _PixelFactsWalker

    facts = _PixelFactsWalker(graph.t).inspect(operand)
    if not facts.sources:
        fail("Focal operations require a finite bound raster source")
    from .numeric_reducer_grid import require_common_grid

    require_common_grid(graph.t, (operand,), label="Focal neighborhood")

    # Allow one node for the native operation and one initial Float64 cast.
    graph.reserve_nodes(2, "Focal image compilation")
    # The legacy time-selection callback otherwise narrows source cells to
    # Float32. Cast before reducing time, while passing already-Double focal
    # results through without an unnecessary conversion.
    input_pixel = operand if graph.has_double_precision(operand) else Pixel(
        "to_double", (operand,),
    )
    data, label, timed = graph.expression(input_pixel)
    if label is None or data is None:
        fail("Focal operations require an input bound to an image grid")
    result = graph.node("local_ee_focal", data=data, spec=spec)
    # The native process already returns a singleton band dimension named v.
    return result, "v", timed
