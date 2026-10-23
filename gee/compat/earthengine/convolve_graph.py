"""Lower bounded convolve Pixel nodes to the dedicated native raster SPI."""
from __future__ import annotations

from .ir import Pixel, fail


def compile_convolve_pixel(graph, pixel):
    if not isinstance(pixel, Pixel) or pixel.op != "convolve" or len(pixel.args) != 2:
        fail("Internal convolution compiler received an invalid Pixel")
    operand, spec = pixel.args
    if type(spec) is not str or len(spec) > 32_768 or not spec.isascii():
        fail("Convolution Pixel has an invalid bounded specification")
    steps = getattr(graph.t, "steps", None)
    if type(steps) is not int or steps + len(spec) > 50_000:
        fail("Convolution specification exceeds the shared 50000-step work budget")
    graph.t.steps = steps + len(spec)

    from ...convolve_spec import decode_convolve_spec

    try:
        decoded = decode_convolve_spec(spec)
    except ValueError as error:
        fail(f"Convolution Pixel has an invalid specification: {error}")
    if type(decoded) is not dict or decoded.get("v") != 1:
        fail("Convolution Pixel uses an unsupported specification")

    # Validate source presence and the grid(s) consumed by this one output
    # band before graph.expression can merge any source cubes.
    from .pixel_math_graph import _PixelFactsWalker

    facts = _PixelFactsWalker(graph.t).inspect(operand)
    if not facts.sources:
        fail("Image.convolve requires a finite bound raster source")
    from .numeric_reducer_grid import require_common_grid

    require_common_grid(graph.t, (operand,), label="Image.convolve")

    graph.reserve_nodes(2, "Image.convolve compilation")
    # Existing scalar callbacks narrow source cells to Float32. Cast first so
    # native convolution sees the source's full Float64 values.
    input_pixel = operand if graph.has_double_precision(operand) else Pixel(
        "to_double", (operand,),
    )
    data, label, timed = graph.expression(input_pixel)
    if label is None or data is None:
        fail("Image.convolve requires an input bound to an image grid")
    result = graph.node("local_ee_convolve", data=data, spec=spec)
    return result, "v", timed
