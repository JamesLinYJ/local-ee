"""Materialize deferred constants on a request's finite local evaluation grid."""
import math

from .ir import Image, Pixel, fail


def is_spatialized_constant(pixel):
    while pixel.op in {"to_float", "to_double"}:
        pixel = pixel.args[0]
    return pixel.op == "on_grid" and len(pixel.args[2].ids) == 1


def materialize_constant(graph, pixel):
    value_pixel, template_pixel, source, footprint, absolute = pixel.args
    value, scalar_label, _ = graph.expression(value_pixel)
    if (scalar_label is not None or isinstance(value, bool)
            or not isinstance(value, (int, float)) or not math.isfinite(value)
            or abs(value) > 2**53):
        fail("Constant bands require a finite exact Float64 scalar within 2^53")
    data, label, timed = graph.expression(template_pixel)
    if label is None or source is None or not source.ids:
        fail("Constant bands require a finite local raster template")
    if timed and len(source.ids) != 1:
        fail("Constant bands require individual observations; select/reduce the collection first")
    if timed:
        # One immutable item supplies the footprint/grid even if every source
        # cell is NoData. Remove its time axis before materializing constants:
        # no observed time key needs to be guessed from an empty temporal RDD.
        data, label, timed = graph.expression(Pixel("reduce_t", (template_pixel, "first")))
    ref = graph.node("local_ee_constant_on_grid", data=data, value=value)
    context = Image([], {}, source, footprint=footprint, footprint_is_absolute=absolute)
    geometry = graph.t.footprint(context)
    ref = graph.node("mask_polygon", data=ref, mask=geometry)
    graph.t.warn(
        "Added constant bands are evaluated on the destination's finite local grid with "
        "an independent valid-pixel mask and destination footprint. Their logical EE "
        "default WGS84/1-degree projection is not exposed or changed by this adapter; "
        "projection queries and exact Google boundary-grid equivalence remain unsupported."
    )
    return ref, "v", timed
