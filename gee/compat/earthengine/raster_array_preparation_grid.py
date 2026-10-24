"""Bind finite array-pad values to a proven local raster grid."""
from __future__ import annotations

from .array_core import charge_array
from .ir import Pixel, Source, fail


def _source_for_pixel(translator, pixel):
    pending = [pixel]
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        charge_array(translator, 1 + len(current.args))
        if current.op == "band" and len(current.args) == 2:
            source = current.args[0]
            if isinstance(source, Source):
                return source
        if current.op == "on_grid" and len(current.args) >= 3:
            source = current.args[2]
            if isinstance(source, Source):
                return source
        children = []
        for argument in current.args:
            if isinstance(argument, Pixel):
                children.append(argument)
            elif isinstance(argument, (tuple, list)):
                charge_array(translator, len(argument) + 1)
                children.extend(
                    child for child in argument if isinstance(child, Pixel)
                )
        charge_array(translator, len(children))
        pending.extend(reversed(children))
    return None


def bind_pad_value_to_grid(translator, array, pad, name):
    """Give a real pad cell the array's finite source grid and mask boundary."""
    source = None
    template = None
    lineages = set()
    from .pixel_math_graph import _PixelFactsWalker

    walker = _PixelFactsWalker(translator)
    charge_array(translator, len(array.cells) + 1)
    for pixel in (*array.cells, array.mask):
        facts = walker.inspect(pixel)
        if facts.sources:
            charge_array(translator, len(facts.sources))
            lineages.update(facts.sources)
            if template is None:
                template = pixel
                source = _source_for_pixel(translator, pixel)
    if len(lineages) != 1 or source is None or not source.ids:
        fail(f"{name} requires one concrete raster source to place padded cells")
    if len(source.ids) != 1:
        fail(f"{name} cannot place pad values on a multi-scene temporal grid")

    bound = Pixel(
        "on_grid",
        (pad.args[0], template, source, array.image.footprint,
         array.image.footprint_is_absolute),
    )
    return Pixel(pad.op, (bound,))
