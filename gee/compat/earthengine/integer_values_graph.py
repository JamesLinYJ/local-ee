"""Compile typed numeric Pixels and exact predicates to the bounded native SPI."""
from __future__ import annotations

from gee.float64_values_contract import FLOAT64_ARITIES, FLOAT64_BOOLEAN

from .ir import Image, Pixel, fail


_COMPARISONS = frozenset({"eq", "neq", "lt", "lte", "gt", "gte"})


def _validate_spec(spec, operands):
    from gee.integer_values_spec import decode_integer_values_spec

    if type(spec) is not str:
        fail("Integer Image Pixel requires a canonical specification")
    try:
        decoded = decode_integer_values_spec(spec)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        fail(f"Integer Image Pixel has an invalid specification: {error}")
    if (type(decoded) is not dict or set(decoded) != {"dtype", "op", "operands", "v"}
            or decoded.get("v") != 1 or type(decoded.get("operands")) is not list):
        fail("Integer Image Pixel has an unsupported specification")
    band_indexes = sorted({item["band"] for item in decoded["operands"]
                           if type(item) is dict and set(item) == {"band"}})
    maximum = 3 if decoded["op"] in {"select", "where_select"} else 2
    if band_indexes != list(range(len(operands))) or not 1 <= len(operands) <= maximum:
        fail("Integer Image Pixel specification does not match its ordered input bands")
    return decoded


def _comparison_pixel(graph, pixel):
    from .image_integer import _pixel

    try:
        return _pixel(
            graph.t, "Image." + pixel.op, pixel.op, pixel.args,
            known_boolean_literals=True,
        )
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        fail(f"Float64 Image comparison is unsupported: {error}")


def _float64_pixel(graph, pixel):
    from .image_integer import _float64_pixel

    try:
        return _float64_pixel(graph.t, "Image." + pixel.op, pixel.op, pixel.args)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        fail(f"Float64 Image operation is unsupported: {error}")


def compile_numeric_values_pixel(graph, pixel):
    """Lower typed integer/Double Pixels to one Float64 NaN-NoData band."""
    if not isinstance(pixel, Pixel):
        fail("Internal integer Image compiler received an invalid Pixel")
    if pixel.op == "integer_values" and len(pixel.args) == 2:
        operands, spec = pixel.args
    elif pixel.op in _COMPARISONS and len(pixel.args) == 2:
        # Existing Image.eq/neq/lt/lte/gt/gte IR stays on its old Float32 path
        # unless a real Double operand requires exact predicate evaluation.
        if not any(graph.has_double_precision(value) for value in pixel.args):
            fail("Internal Float64 comparison path received only Float32 operands")
        pixel = _comparison_pixel(graph, pixel)
        if pixel.op == "constant":
            # Typed source-free operands can still compare entirely at
            # compile time. They need a real image grid later if rendered.
            return graph.expression(pixel)
        if pixel.op != "integer_values" or len(pixel.args) != 2:
            fail("Float64 Image comparison did not produce a supported scalar result")
        operands, spec = pixel.args
    elif pixel.op in FLOAT64_ARITIES:
        if len(pixel.args) != FLOAT64_ARITIES[pixel.op]:
            fail("Float64 Image operation has an invalid operand count")
        if not any(graph.has_double_precision(value) for value in pixel.args):
            fail("Internal Float64 operation path received only Float32 operands")
        pixel = _float64_pixel(graph, pixel)
        if pixel.op != "integer_values":
            if pixel.op not in {"constant", "to_double"}:
                fail("Float64 Image operation folded to an unsupported value")
            # Preserve pure source-free static folding; a typed Double wrapper
            # remains visible to later source binding and precision checks.
            return graph.expression(pixel)
        if len(pixel.args) != 2:
            fail("Float64 Image operation did not produce a supported scalar result")
        operands, spec = pixel.args
    else:
        fail("Internal integer Image compiler received an unsupported Pixel")

    if (type(operands) is not tuple or not 1 <= len(operands) <= 3
            or any(not isinstance(value, Pixel) for value in operands)):
        fail("Integer Image Pixel has an invalid number of scalar raster operands")
    decoded = _validate_spec(spec, operands)

    # A finite source/grid proof must finish before input expressions can
    # allocate merge_cubes or any other source nodes.
    from .pixel_math_graph import _PixelFactsWalker

    facts = _PixelFactsWalker(graph.t)
    for operand in operands:
        if not facts.inspect(operand).sources:
            fail("Integer Image operations require at least one finite bound raster operand")
    if len(operands) > 1:
        from .numeric_reducer_grid import require_common_grid

        require_common_grid(
            graph.t, operands, label="Integer Image operations",
            check_single_item_assets=decoded["op"] in {"select", "where_select"},
        )

    # Account for copies, spec traversal, possible Double casts and the final
    # native node before materializing either input or merging their cubes.
    from .scalar_work_ledger import reserve_scalar_input_work

    input_pixels = tuple(
        operand if graph.has_double_precision(operand) else Pixel("to_double", (operand,))
        for operand in operands
    )
    input_image = Image([(f"operand{index}", value)
                         for index, value in enumerate(input_pixels)], {})
    reserve_scalar_input_work(graph, input_image, spec)

    refs = []
    timed = None
    for index, operand in enumerate(input_pixels):
        ref, label, has_time = graph.expression(operand)
        if label is None or ref is None:
            fail("Integer Image operations require bound raster operands")
        if timed is not None and timed != has_time:
            fail("Integer Image operands need matching spatial/temporal dimensions")
        timed = bool(has_time)
        refs.append(graph.rename_band(ref, f"band{index}"))

    data = refs[0]
    for reference in refs[1:]:
        data = graph.node("merge_cubes", cube1=data, cube2=reference)
    # The native process returns physical Float64 0/1 predicates or exact
    # integer-valued doubles and preserves masks as NaN NoData.
    operation = decoded.get("op")
    boolean_operations = _COMPARISONS | FLOAT64_BOOLEAN
    if operation in boolean_operations and not pixel.boolean:
        fail("Float64 Image predicate must retain its Boolean marker")
    if operation not in boolean_operations and pixel.boolean:
        fail("Float64 Image numeric operation cannot carry a Boolean marker")
    result = graph.node("local_ee_integer_values", data=data, spec=spec)
    return result, "v", bool(timed)


# Keep the previous private name for compiler callers and focused tests.
compile_integer_values_pixel = compile_numeric_values_pixel
