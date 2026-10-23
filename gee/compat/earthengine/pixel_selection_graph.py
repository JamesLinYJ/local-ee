"""Lower typed conditionals to native selection with selected-branch masks."""
from __future__ import annotations

from .ir import Pixel, const, fail
from .pixel_math_graph import _PixelFactsWalker


def where_float32(test, value, original):
    """Preserve the established callback lowering for Float32 where payloads."""
    condition = Pixel("if", (
        Pixel("is_nodata", (test,), True), const(False),
        Pixel("neq", (test, const(0)), True),
    ), True)
    condition = Pixel("if", (Pixel("is_nodata", (value,), True), const(False), condition), True)
    return Pixel("preserve_mask", (Pixel("if", (condition, value, original)), original))


def select_float64(graph, pixel, *, operation="select"):
    """Never route conditional payloads through Float32 callbacks or masks.

    The native ternary operation reads the merged cube's condition and selected
    payload directly. Missing condition or selected payload becomes NoData;
    missing unselected payload is irrelevant. Observed keys are joined by the
    existing merge path, with absent input bands represented by NoData.
    """
    if (operation not in {"select", "where_select"}
            or not isinstance(pixel, Pixel) or pixel.op != "if"
            or type(pixel.args) is not tuple or len(pixel.args) != 3
            or any(not isinstance(value, Pixel) for value in pixel.args)):
        fail("Float64 selection requires exactly three Pixel operands")
    steps = getattr(graph.t, "steps", None)
    if type(steps) is not int or steps < 0 or steps + 48 > 50_000:
        fail("Float64 selection exceeds the shared 50000-step work budget")
    graph.t.steps += 48
    walker = _PixelFactsWalker(graph.t)
    facts = tuple(walker.inspect(value) for value in pixel.args)
    template = next((value for value, fact in zip(pixel.args, facts) if fact.sources), None)
    if template is None:
        fail("Float64 selection requires a finite bound raster grid")

    operands = []
    for value, fact in zip(pixel.args, facts):
        if fact.sources:
            operands.append(value)
            continue
        # Fold source-free expressions with their actual nested cast stages.
        # Deferred math is not a finite scalar and cannot acquire a fake grid.
        scalar, label, _timed = graph.expression(value)
        if label is not None or type(scalar) not in (type(None), int, float, bool):
            fail("Float64 selection requires finite scalar or bound raster operands")
        if scalar is None:
            # Wire constants are finite. Represent a null operand as an actual
            # all-NoData raster on an existing operand's grid instead.
            typed_template = Pixel("to_double", (template,))
            operands.append(Pixel("if", (const(False), typed_template, const(None))))
        else:
            operands.append(const(int(scalar) if type(scalar) is bool else scalar))
    # The generic typed compiler owns fresh grid proof, temporal-dimension
    # checks, copy/spec work reservation, ordered merging and native admission.
    from .integer_values_graph import compile_numeric_values_pixel

    # A numeric Double condition with Float32 branches must also avoid losing
    # subnormal truth. The primitive always returns physical Float64 values.
    if not any(graph.has_double_precision(value) for value in operands):
        operands[1] = Pixel("to_double", (operands[1],))
    return compile_numeric_values_pixel(graph, Pixel(operation, tuple(operands)))
