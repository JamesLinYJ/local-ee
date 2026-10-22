"""Compile exact raster classifier Pixel nodes into the native process protocol."""
from __future__ import annotations

from .classifier_model import model_validation_work, validate_model
from .ir import Pixel, fail


MAX_TRANSLATOR_WORK = 50_000
MAX_GRAPH_NODES = 500


def classify_pixel(graph, pixel):
    """Return a native minimum-distance process reference, band and time flag."""
    if not isinstance(pixel, Pixel) or pixel.op != "classify" or len(pixel.args) != 2:
        fail("Internal raster classifier Pixel is malformed")
    inputs, model = pixel.args
    if type(inputs) is not tuple or not 1 <= len(inputs) <= 8:
        fail("Raster classifier Pixel requires 1..8 schema-ordered inputs")

    work = model_validation_work(model)
    translator = graph.t
    if translator.steps + work > MAX_TRANSLATOR_WORK:
        fail("Image.classify model validation exceeds the 50000-step work budget")
    translator.steps += work
    model = validate_model(model)
    if len(inputs) != len(model["schema"]):
        fail("Raster classifier Pixel input count does not match its model schema")

    # Each input may need one label rename; the selected bands need n-1 merges,
    # then the native result and Image.classify's final output label are nodes.
    # Reserve this deterministic portion before compiling any input expression.
    required_nodes = (2 * len(inputs) + 1
                      + int(translator.options.get("scale") is not None
                            or translator.options.get("crs") is not None)
                      + int(translator.options.get("region") is not None))
    if len(graph.graph) + required_nodes > MAX_GRAPH_NODES:
        fail("Image.classify exceeds the 500-node process graph budget")

    data = None
    timed = None
    for band_name, input_pixel in zip(model["schema"], inputs):
        if not isinstance(input_pixel, Pixel):
            fail("Raster classifier Pixel inputs must be scalar pixel expressions")
        reference, label, has_time = graph.expression(input_pixel)
        if label is None or reference is None:
            fail("Image.classify requires bound raster input bands")
        if timed is not None and timed != has_time:
            fail("Image.classify schema bands have incompatible time dimensions")
        timed = has_time
        reference = graph.rename_band(reference, band_name)
        data = reference if data is None else graph.node(
            "merge_cubes", cube1=data, cube2=reference,
        )

    result = graph.node("local_ee_minimum_distance", data=data, model=model)
    return result, "v", bool(timed)
