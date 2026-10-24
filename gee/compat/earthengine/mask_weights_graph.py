"""Lower independent mask projections without narrowing scientific values."""
from __future__ import annotations

import math

from gee.mask_weights_spec import MASK_WEIGHT_ARITIES, mask_weights_spec
from .ir import Image, Pixel, fail


def _weight(value, *, missing=False):
    if value is None and missing:
        return 0.0
    if (type(value) not in (int, float, bool) or not math.isfinite(value)
            or not 0 <= value <= 1):
        fail("Image masks require finite weights in[0,1]")
    return float(value)


def _fold(operation, values):
    if operation == "validity":
        value = values[0]
        if value is None:
            return 0.0
        if type(value) not in (int, float, bool) or not math.isfinite(value):
            fail("Image mask validity requires finite values or NoData")
        return 1.0
    if operation == "update":
        old, new = _weight(values[0]), _weight(values[1], missing=True)
        return 0.0 if old == 0 else new
    weight = _weight(values[1])
    value = values[0]
    if value is not None and (type(value) not in (int, float, bool) or not math.isfinite(value)):
        fail("Image mask values require finite data or NoData")
    return value if weight > 0 else None


def _require_observation_keys(graph, pixels, facts):
    """Prove actual time keys before the mask operands become one merged cube.

    Spatial images may legitimately originate on different dates.  This check
    applies only to operands that still have an actual time dimension.
    """
    from .image_collection_link_grid import _time_start
    from .numeric_reducer_grid import _charge, _item_lookup

    lineages = set()
    for pixel in pixels:
        for lineage in facts.inspect(pixel).sources:
            _charge(graph.t, 1 + len(lineage[0]) + len(lineage[1]))
            lineages.add(lineage)
    if len(lineages) < 2:
        return
    lookups, expected = {}, None
    for cid, ids in lineages:
        if cid not in lookups:
            lookups[cid] = _item_lookup(graph.t, cid)
        instants = set()
        _charge(graph.t, len(ids))
        for item_id in ids:
            item = lookups[cid].get(item_id)
            if item is None:
                fail("Image mask weights require available actual observations")
            instant = _time_start(graph.t, item, cid, "Image mask weights")
            if instant in instants:
                fail("Image mask weights require distinct individual observation keys")
            instants.add(instant)
        keys = frozenset(instants)
        if expected is not None and keys != expected:
            fail("Image mask weights require matching actual observation time keys")
        expected = keys


def compile_mask_projection(graph, pixel):
    operation = pixel.op.removeprefix("mask_")
    arity = MASK_WEIGHT_ARITIES.get(operation)
    if (arity is None or type(pixel.args) is not tuple or len(pixel.args) != arity
            or any(not isinstance(value, Pixel) for value in pixel.args) or pixel.boolean):
        fail("Malformed independent mask projection")
    spec = mask_weights_spec(operation)
    from .pixel_math_graph import _PixelFactsWalker
    from .scalar_work_ledger import reserve_scalar_input_work

    facts = _PixelFactsWalker(graph.t)
    raster_inputs = tuple(value for value in pixel.args if facts.inspect(value).sources)
    if len(raster_inputs) > 1:
        from .numeric_reducer_grid import require_common_grid

        require_common_grid(graph.t, raster_inputs, label="Image mask weights", check_single_item_assets=True)
    # Make this projection's Float64 input boundary explicit before structural
    # selection. Prior explicit toFloat and arithmetic stages stay inside the
    # outer casts; this is not a claim that every old first callback narrowed.
    input_pixels = tuple(
        value if graph.has_double_precision(value) else Pixel("to_double", (value,))
        for value in pixel.args
    )
    reserve_scalar_input_work(graph, Image([
        (f"operand{index}", value) for index, value in enumerate(input_pixels)
    ], {}), spec)
    if not raster_inputs:
        results = [graph.expression(value) for value in input_pixels]
        if any(label is not None or isinstance(value, Pixel) for value, label, _time in results):
            fail("Mask projections require finite scalars or an actual local raster grid")
        return _fold(operation, [value for value, _label, _time in results]), None, True

    # Decode all scalar operands before materializing any merge.  Range checks
    # for real raster masks are repeated independently inside the tile kernel.
    results = [graph.expression(value) for value in input_pixels]
    template = next(result for result in results if result[1] is not None)
    timed = template[2]
    if timed:
        from .mask_graph import check_observations

        for operand in raster_inputs:
            check_observations(operand)
        _require_observation_keys(graph, [
            operand for operand, result in zip(pixel.args, results) if result[1] is not None and result[2]
        ], facts)
    references = []
    for index, (value, label, has_time) in enumerate(results):
        if label is None:
            if operation == "update":
                value = _weight(value, missing=index == 1)
            elif operation == "apply" and index == 1:
                value = _weight(value)
            if value is None and operation == "apply" and index == 0:
                # A masked constant has a real null value, not an invented 0.
                # Bind an all-NoData operand to the other operand's existing
                # grid; apply then preserves the mask's real keys and extent.
                from .mask_graph import constant
                from .numeric_reducer_grid import _charge

                _charge(graph.t, 12)
                graph.reserve_nodes(3, "Image mask NoData operand")
                zero = constant(graph, template[0], 0)
                invalid = constant(graph, template[0], 1)
                value = graph.node("mask", data=zero, mask=invalid)
            elif value is None or isinstance(value, Pixel):
                fail("Raster mask projections require numeric scalar operands")
            else:
                from .mask_graph import constant

                value = constant(graph, template[0], value)
        elif has_time != timed:
            fail("Image mask weights require matching spatial/temporal dimensions")
        references.append(graph.rename_band(value, f"operand{index}"))
    data = references[0]
    for reference in references[1:]:
        data = graph.node("merge_cubes", cube1=data, cube2=reference)
    return graph.node("local_ee_mask_weights", data=data, spec=spec), "v", bool(timed)
