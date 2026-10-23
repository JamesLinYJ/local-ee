"""Compile one shared per-pixel matrix producer and select its output cells."""
from __future__ import annotations

from .ir import Pixel, Source, fail


_MAX_WORK = 50_000
_MAX_NODES = 500
_MAX_IR_VISITS = 50_000
_MAX_IR_DEPTH = 96
_CASTS = frozenset({"to_float", "to_double"})


def _immutable_ir(translator, root):
    """Iteratively bound and verify the producer's immutable Pixel subtree."""
    from .array_core import charge_array

    active = set()
    complete = set()
    stack = [(root, False, 0)]
    visits = 0
    while stack:
        value, leaving, depth = stack.pop()
        charge_array(translator, 1)
        visits += 1
        if visits > _MAX_IR_VISITS:
            fail("Internal matrix producer exceeds the immutable Pixel work limit")
        if depth > _MAX_IR_DEPTH:
            fail("Internal matrix producer exceeds the immutable Pixel depth limit")
        if type(value) in (type(None), bool, int, float, str, bytes):
            continue
        identity = id(value)
        if leaving:
            active.remove(identity)
            complete.add(identity)
            continue
        if identity in active:
            fail("Internal matrix producer contains cyclic Pixel operands")
        if identity in complete:
            continue
        if isinstance(value, tuple):
            children = value
        elif isinstance(value, frozenset):
            children = tuple(value)
        elif isinstance(value, Pixel):
            if (type(value.args) is not tuple or type(value.op) is not str
                    or type(value.boolean) is not bool):
                fail("Internal matrix producer contains malformed Pixel operands")
            children = value.args
        elif isinstance(value, Source):
            children = (value.cid, value.ids, value.names, value.alias)
        else:
            fail("Internal matrix producer must contain immutable acyclic Pixel operands")
        if len(children) > _MAX_IR_VISITS - visits:
            fail("Internal matrix producer exceeds the immutable Pixel work limit")
        active.add(identity)
        stack.append((value, True, depth))
        stack.extend((child, False, depth + 1) for child in reversed(children))
    return True


def _spec_for_producer(graph, producer):
    from gee.matrix_values_spec import (
        decode_matrix_values_spec,
        matrix_input_bands,
        matrix_output_shape,
    )

    if (not isinstance(producer, Pixel) or producer.op != "matrix_values"
            or type(producer.args) is not tuple or len(producer.args) != 2):
        fail("Internal matrix element has an invalid shared producer")
    operands, spec = producer.args
    if (type(operands) is not tuple or not 1 <= len(operands) <= 64
            or any(not isinstance(value, Pixel) for value in operands)):
        fail("Internal matrix producer requires ordered dynamic Pixel operands")
    if type(spec) is not str or len(spec) > 8192 or not spec.isascii():
        fail("Internal matrix producer has an invalid bounded specification")
    from .array_core import charge_array

    # Every component independently revalidates its producer. Charge the
    # canonical wire parsing on cache hits too, so output fan-out cannot
    # multiply unaccounted JSON/spec work.
    charge_array(graph.t, len(spec) + 2 * len(operands) + 8)
    try:
        decoded = decode_matrix_values_spec(spec)
        input_bands = matrix_input_bands(decoded)
        output_shape = matrix_output_shape(decoded)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        fail(f"Internal matrix producer has an invalid specification: {error}")
    if input_bands != len(operands):
        fail("Matrix specification does not match its ordered dynamic operands")
    charge_array(
        graph.t,
        2 * len(decoded["operands"]) + 2 * output_shape[0] * output_shape[1] + 8,
    )
    _immutable_ir(graph.t, producer)
    return operands, spec, decoded, output_shape


def _validate_operand_casts(graph, operands, decoded):
    """Recheck explicit uniform casts for each array represented by the wire."""
    from .array_core import charge_array

    rows, cols, rhs_cols = decoded["rows"], decoded["cols"], decoded["rhs_cols"]
    split = rows * cols
    groups = [decoded["operands"][:split]]
    if decoded["op"] == "solve":
        groups.append(decoded["operands"][split:])
    for group in groups:
        dtype = None
        for descriptor in group:
            charge_array(graph.t, 1)
            if "constant" in descriptor:
                continue
            pixel = operands[descriptor["band"]]
            if (pixel.op not in _CASTS or type(pixel.args) is not tuple
                    or len(pixel.args) != 1 or pixel.boolean):
                fail("Matrix native operands require explicit top-level toFloat/toDouble cells")
            if dtype is not None and dtype != pixel.op:
                fail("Matrix native operands require uniform top-level casts per input array")
            dtype = pixel.op
    if decoded["op"] == "solve" and len(groups[1]) != rows * rhs_cols:
        fail("Matrix solve specification has an inconsistent right-hand-side shape")


def _cache(graph):
    cache = getattr(graph, "_matrix_values_producers", None)
    if cache is None:
        cache = graph._matrix_values_producers = {}
    if type(cache) is not dict:
        fail("Internal matrix producer cache is malformed")
    return cache


def _preflight(graph, operands, spec, output_count):
    from .sampled_training import image_node_estimate, image_work_estimate

    # The shared estimators consume the ordinary Image shape but do not retain
    # or mutate it. Keep the exact dynamic operand order for both estimates.
    from .ir import Image

    image = Image([(f"operand{index}", pixel)
                   for index, pixel in enumerate(operands)], {})
    try:
        copy_work = image_work_estimate(image)
        node_bound = image_node_estimate(image, graph.t.options)
    except (TypeError, ValueError, OverflowError, RecursionError):
        fail("Matrix native operands exceed the shared compiler budget")
    work = 2 * len(spec) + copy_work + 4 * len(operands) + 3 * output_count + 16
    steps = getattr(graph.t, "steps", None)
    if type(steps) is not int or steps < 0 or steps + work > _MAX_WORK:
        fail("Matrix native graph exceeds the shared 50000-step work budget")
    graph.t.steps = steps + work
    # Each dynamic input may need one additional merge, the shared producer
    # adds one native node, and each component can need selection, cast and
    # final output-label nodes. Reserve this full bounded upper estimate before
    # asking Graph.expression to materialize any input or merge its sources.
    graph.reserve_nodes(
        node_bound + max(0, len(operands) - 1) + 1 + 3 * output_count,
        "Matrix native graph",
    )


def _compile_producer(graph, producer, operands, spec, decoded, output_shape):
    cache = _cache(graph)
    key = id(producer)
    cached = cache.get(key)
    if cached is not None:
        if cached[0] is not producer:
            fail("Internal matrix producer identity collision")
        return cached[1], cached[2]

    # Validate source lineage and actual single-item asset grids before any
    # input expressions can create source or merge_cubes nodes. This proof is
    # fresh for each Graph and is never stored as a cross-compilation fact.
    from .pixel_math_graph import _PixelFactsWalker

    facts = _PixelFactsWalker(graph.t)
    for operand in operands:
        if not facts.inspect(operand).sources:
            fail("Native matrix operations require a finite bound raster operand")
    from .numeric_reducer_grid import require_common_grid

    require_common_grid(
        graph.t, operands, label="Native matrix operation",
        check_single_item_assets=True,
    )
    output_count = output_shape[0] * output_shape[1]
    _preflight(graph, operands, spec, output_count)

    refs = []
    timed = None
    for index, operand in enumerate(operands):
        ref, label, has_time = graph.expression(operand)
        if ref is None or label is None:
            fail("Native matrix operations require actual bound raster operands")
        if timed is not None and timed != has_time:
            fail("Native matrix operands need matching spatial/temporal dimensions")
        timed = bool(has_time)
        refs.append(graph.rename_band(ref, f"band{index}"))

    data = refs[0]
    for reference in refs[1:]:
        data = graph.node("merge_cubes", cube1=data, cube2=reference)
    result = graph.node("local_ee_matrix_values", data=data, spec=spec)
    if len(cache) >= _MAX_NODES:
        fail("Matrix native producer cache exceeds the 500-node graph budget")
    cache[key] = (producer, result, bool(timed))
    return result, bool(timed)


def compile_matrix_element(graph, pixel):
    """Compile one output component of a strongly shared matrix producer."""
    if (not isinstance(pixel, Pixel) or pixel.op != "matrix_element"
            or type(pixel.args) is not tuple or len(pixel.args) != 2):
        fail("Internal matrix compiler received an invalid output component")
    producer, index = pixel.args
    if type(index) is not int or index < 0:
        fail("Internal matrix output component index must be a nonnegative integer")
    operands, spec, decoded, output_shape = _spec_for_producer(graph, producer)
    _validate_operand_casts(graph, operands, decoded)
    output_count = output_shape[0] * output_shape[1]
    if index >= output_count:
        fail("Internal matrix output component index is outside the output shape")
    result, timed = _compile_producer(
        graph, producer, operands, spec, decoded, output_shape,
    )
    selected = graph.node(
        "filter_bands", data=result, bands=[f"matrix{index}"],
    )
    return graph.rename_band(selected, "v"), "v", timed
