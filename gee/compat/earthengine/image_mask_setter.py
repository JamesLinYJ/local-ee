"""Replace masks and zero-fill newly valid science on the existing input grid."""
from __future__ import annotations

from dataclasses import replace

from .ir import Pixel, const, fail


def fold_set_value(raw, old_weight):
    """The same finite science/weight contract as apply, followed by zero fill."""
    from .mask_weights_graph import _fold

    visible = _fold("apply", (raw, old_weight))
    return 0.0 if visible is None else visible


def replace_mask(translator, image, mask):
    from .image_mask_weights import (
        _charge_bands, _check_literal_mask, mask_input_value, mask_of, value_of,
    )
    from .ir import pairs

    _charge_bands(translator, image, mask)
    if len(mask.bands) not in {1, len(image.bands)}:
        fail("Image.mask needs one broadcast mask band or the same number of input bands")
    _, _, matched = pairs(image, mask)
    for _name, _raw, weight in matched:
        _check_literal_mask(weight)
    # Reserve fill, validity, replacement and carrier nodes before allocation.
    work = 12 * len(matched)
    if translator.steps + work > 50_000:
        fail("Image.mask exceeds the shared50000-step compilation work budget")
    translator.steps += work
    bands = []
    for name, pixel, mask_pixel in matched:
        filled = Pixel("mask_set_value", (value_of(pixel), mask_of(pixel)), pixel.boolean)
        # Filled science is valid throughout the actual original input support.
        # Its validity anchors replacement weights to that grid/observation;
        # the OLD mask must not gate the new mask, because setter can restore0.
        weight = Pixel("mask_update", (
            Pixel("mask_validity", (filled,)), mask_input_value(mask_pixel),
        ))
        bands.append((name, Pixel("with_mask", (filled, weight), pixel.boolean)))
    translator.warn(
        "Image.mask replaces weights and fills newly valid input pixels with zero. "
        "Finite[0,1] weights and masked new-mask pixels becoming zero are local "
        "validation policies. Only proven aligned grids and audited weighted "
        "consumers are supported; global constant grids and Google parity are unverified."
    )
    return replace(image, bands=bands)


def compile_set_value(graph, pixel):
    """Compose existing strict mask apply and native unmask; no new tile kernel."""
    if (type(pixel.args) is not tuple or len(pixel.args) != 2
            or any(not isinstance(value, Pixel) for value in pixel.args)):
        fail("Malformed mask replacement science")
    from .mask_weights_graph import compile_mask_projection

    data, label, timed = compile_mask_projection(graph, Pixel("mask_apply", pixel.args))
    if label is None:
        return 0.0 if data is None else data, None, timed
    from .numeric_reducer_grid import _charge
    from .mask_graph import constant

    _charge(graph.t, 12)
    graph.reserve_nodes(2, "Image.mask zero fill")
    zero = constant(graph, data, 0)
    return graph.node("local_ee_unmask", data=data, value=zero, same_footprint=True), label, timed
