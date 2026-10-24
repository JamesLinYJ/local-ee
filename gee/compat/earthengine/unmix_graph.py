"""Compile shared Image.unmix producers and select Float64 components."""
from __future__ import annotations

from .ir import Image, Pixel, Source, fail
from .unmix_input_snapshot import snapshot_unmix_inputs


_MAX_WORK = 50_000
_MAX_NODES = 500


def _producer_cache(graph):
    cache = getattr(graph, "_unmix_producers", None)
    if cache is None:
        cache = graph._unmix_producers = {}
    if type(cache) is not dict:
        fail("Internal Image.unmix producer cache is malformed")
    return cache


def _preflight(graph, operands, spec, component_count):
    from .sampled_training import image_node_estimate, image_work_estimate

    image = Image([(f"operand{index}", pixel)
                   for index, pixel in enumerate(operands)], {})
    try:
        copy_work = image_work_estimate(image)
        node_bound = image_node_estimate(image, graph.t.options)
    except (TypeError, ValueError, OverflowError, RecursionError):
        fail("Image.unmix operands exceed the shared compiler budget")
    work = 2 * len(spec) + copy_work + 4 * len(operands) + 3 * component_count + 16
    steps = getattr(graph.t, "steps", None)
    if type(steps) is not int or steps < 0 or steps + work > _MAX_WORK:
        fail("Image.unmix graph exceeds the shared 50000-step work budget")
    graph.t.steps = steps + work
    graph.reserve_nodes(
        node_bound + max(0, len(operands) - 1) + 1 + 3 * component_count,
        "Image.unmix graph",
    )


def _validate_source_grid(graph, operands):
    """Revalidate current source lineage and grid evidence for every output."""
    from .pixel_math_graph import _PixelFactsWalker

    facts = _PixelFactsWalker(graph.t)
    for operand in operands:
        if not facts.inspect(operand).sources:
            fail("Image.unmix requires finite bound raster inputs; source-free constants cannot fold")
    from .numeric_reducer_grid import require_common_grid

    require_common_grid(
        graph.t, operands, label="Image.unmix", check_single_item_assets=True,
    )


def _compile_producer(graph, operands, spec, snapshot, retained, component_count):
    cache = _producer_cache(graph)
    key = (id(operands), spec)
    cached = cache.get(key)
    if cached is not None:
        if cached[0] is not operands:
            fail("Internal Image.unmix producer identity collision")
        if cached[1] != snapshot:
            fail("Image.unmix input changed between component compilations")

    # A cached producer reuses only its output node. Recheck source/grid facts
    # against the current IR and catalogue every time a component is compiled.
    _validate_source_grid(graph, operands)
    if cached is not None:
        return cached[3], cached[4]

    _preflight(graph, operands, spec, component_count)

    refs = []
    timed = None
    for index, operand in enumerate(operands):
        ref, label, has_time = graph.expression(operand)
        if ref is None or label is None:
            fail("Image.unmix requires actual bound raster inputs")
        if timed is not None and timed != has_time:
            fail("Image.unmix input bands need matching spatial/temporal dimensions")
        timed = bool(has_time)
        refs.append(graph.rename_band(ref, f"band{index}"))

    data = refs[0]
    for reference in refs[1:]:
        data = graph.node("merge_cubes", cube1=data, cube2=reference)
    result = graph.node("local_ee_unmix", data=data, spec=spec)
    if len(cache) >= _MAX_NODES:
        fail("Image.unmix producer cache exceeds the 500-node graph budget")
    cache[key] = (operands, snapshot, retained, result, bool(timed))
    return result, bool(timed)


def compile_unmix_component(graph, pixel):
    """Compile one component of one strongly shared bounded unmix operation."""
    if (not isinstance(pixel, Pixel) or pixel.op != "unmix_component"
            or type(pixel.args) is not tuple or len(pixel.args) != 3):
        fail("Internal Image.unmix compiler received an invalid component")
    operands, spec, index = pixel.args
    if (type(operands) is not tuple or not 1 <= len(operands) <= 8
            or any(not isinstance(value, Pixel) for value in operands)):
        fail("Internal Image.unmix producer requires ordered dynamic Pixel operands")
    if type(spec) is not str or len(spec) > 8_192 or not spec.isascii():
        fail("Internal Image.unmix producer has an invalid bounded specification")
    if type(index) is not int or index < 0:
        fail("Internal Image.unmix component index must be nonnegative")

    from gee.spectral_unmix_spec import (
        decode_spectral_unmix_spec,
        spectral_unmix_component_count,
        spectral_unmix_input_count,
    )
    from .array_core import charge_array

    charge_array(graph.t, len(spec) + 2 * len(operands) + 8)
    try:
        decoded = decode_spectral_unmix_spec(spec)
        input_count = spectral_unmix_input_count(decoded)
        component_count = spectral_unmix_component_count(decoded)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        fail(f"Internal Image.unmix producer has an invalid specification: {error}")
    if input_count != len(operands):
        fail("Image.unmix specification does not match its ordered input bands")
    if index >= component_count:
        fail("Internal Image.unmix component index is outside the output shape")

    snapshot, retained = snapshot_unmix_inputs(graph, operands)
    result, timed = _compile_producer(
        graph, operands, spec, snapshot, retained, component_count,
    )
    selected = graph.node(
        "filter_bands", data=result, bands=[f"unmix{index}"],
    )
    output_name = f"unmix_{index}"
    return graph.rename_band(selected, output_name), output_name, timed
