"""Find a proven science-grid context for binding source-free Image values."""
from __future__ import annotations

from dataclasses import replace

from .array_core import charge_array
from .ir import Image, Pixel, Source, fail


def binding_context(translator, destination: Image) -> Image:
    """Return a temporary Image whose grid source matches its science template.

    Image.source remains the public first-image identity on the returned Image.
    This context is used only while binding constants and is rebuilt from the
    current immutable Pixel lineage on each binding call.
    """
    if destination.source is None:
        return destination
    if type(destination.bands) is not list or len(destination.bands) > 10_000:
        fail("Constant band binding requires at most 10000 destination bands")

    # The common single-band case already proves its grid directly. Avoid a
    # lineage walk when the existing metadata source is the actual first band.
    if destination.bands:
        first = destination.bands[0]
        if (type(first) is tuple and len(first) == 2
                and isinstance(first[1], Pixel)
                and first[1].op == "band"
                and len(first[1].args) == 2
                and first[1].args[0] == destination.source):
            return destination

    charge_array(translator, 2 * len(destination.bands) + 1)
    from .constant_mask_lineage import scan_mask_lineage

    template_index = None
    grid_source = None
    for index, entry in enumerate(destination.bands):
        if (type(entry) is not tuple or len(entry) != 2
                or type(entry[0]) is not str or not isinstance(entry[1], Pixel)):
            fail("Constant band binding requires named Pixel destination bands")
        lineage = scan_mask_lineage(entry[1], translator)
        if not lineage.science_raster:
            continue
        if type(lineage.first_science_source) is not Source:
            fail("Constant band binding cannot prove its science grid source")
        if not lineage.first_science_source.ids:
            fail("Constant band binding requires a finite science grid source")
        template_index = index
        grid_source = lineage.first_science_source
        break

    if template_index is None:
        charge_array(translator, 1)
        return replace(destination, bands=[])
    if template_index == 0 and grid_source == destination.source:
        return destination

    # Keep the complete destination closure for downstream preflight while
    # placing the proven science template first for both plain and weighted
    # constant binders. Do not copy or rewrite any Pixel graph.
    charge_array(translator, len(destination.bands) + 1)
    bands = [destination.bands[template_index]]
    bands.extend(destination.bands[:template_index])
    bands.extend(destination.bands[template_index + 1:])
    return replace(destination, bands=bands, source=grid_source)
