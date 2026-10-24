"""Lift audited unary and image-scalar math without discarding mask weights."""
from __future__ import annotations

from types import SimpleNamespace

from .image_mask_weights import _parts
from .ir import Image, Pixel, const, fail


def _charge(translator, work):
    if translator is None:
        return
    steps = getattr(translator, "steps", None)
    if type(steps) is not int or steps < 0 or steps + work > 50_000:
        fail("Masked image math exceeds the 50000-step compilation work budget")
    translator.steps = steps + work


def _guard(value):
    # Validate the original scientific input before arithmetic can turn an
    # invalid Infinity into NaN/finite output. This preserves its precision
    # declaration; it is not a new Float64 cast.
    return Pixel("mask_guard", (value,), value.boolean)


def _result(value, weight, boolean):
    value = Pixel("mask_result_value", (value,))
    # update replaces at nonzero old masks. Put result validity FIRST so an
    # invalid result gets0 and a finite result keeps the exact original weight.
    valid = Pixel("mask_validity", (value,))
    return Pixel("with_mask", (value, Pixel("mask_update", (valid, weight))), boolean)


def _scalar_value(translator, pixel):
    if pixel.op == "constant" and type(pixel.args) is tuple and len(pixel.args) == 1:
        return pixel
    # Source-free compound constants need actual folding before the typed
    # raster compiler. Reserve the complete walk/copy work even if the earlier
    # facts lookup was a cache hit; no cached lineage fact is a work discount.
    from .scalar_work_plan import plan_scalar_input_work

    plan = plan_scalar_input_work(
        Image([("constant", pixel)], {}), None,
        max_inspection_work=50_000 - translator.steps, max_cache_entries=0,
    )
    if not plan.safe:
        fail("Masked scalar math requires immutable finite constant expressions")
    _charge(translator, plan.structural_work + plan.inspection_work)
    from .constant_bands import _evaluate
    from .graph import Graph

    value = const(_evaluate(pixel))
    return (Pixel("to_double", (value,))
            if Graph(translator).has_double_precision(pixel) else value)


def unary_pixel(translator, operation, pixel, *, boolean=False):
    if pixel.op != "with_mask":
        return Pixel(operation, (pixel,), boolean)
    _charge(translator, 14)
    value, weight = _parts(pixel)
    result = Pixel(operation, (_guard(value),), boolean)
    return _result(result, weight, boolean)


def binary_pixel(translator, operation, left, right, *, boolean=False):
    weighted = [index for index, value in enumerate((left, right))
                if value.op == "with_mask"]
    if len(weighted) != 1:
        # Keep unsupported multiple fractional-mask combinations intact so
        # existing unaudited-consumer rejection still protects every sink.
        return Pixel(operation, (left, right), boolean)
    _charge(translator, 18)
    index = weighted[0]
    operands = (left, right)
    other = operands[1 - index]
    from .pixel_math_graph import _PixelFactsWalker

    context = translator if translator is not None else SimpleNamespace(steps=0)
    if _PixelFactsWalker(context).inspect(other).sources:
        return Pixel(operation, operands, boolean)
    other = _scalar_value(context, other)
    value, weight = _parts(operands[index])
    raw = (_guard(value), other) if index == 0 else (other, _guard(value))
    return _result(Pixel(operation, raw, boolean), weight, boolean)
