"""Project direct fractional-mask carriers only at audited sample producers."""
from __future__ import annotations

from dataclasses import replace

from .image_mask_weights import mask_input_value, value_of
from .ir import Image, Pixel, fail


MAX_TRANSLATOR_WORK = 50_000


def project_sample_mask_image(image, translator):
    """Return a fresh sampling view with direct weighted bands made NoData-aware.

    A carrier is projected only when it is the top-level value of a named
    sample band. Descending through arithmetic, conditionals, clip or other
    expressions here would authorize value consumers that have no mask
    contract of their own.
    """
    if not isinstance(image, Image):
        fail("Sample mask projection requires an Earth Engine Image")
    bands = image.bands
    if type(bands) is not list or not 1 <= len(bands) <= 64:
        fail("Sample mask projection requires 1..64 named scalar pixel bands")

    weighted = []
    name_work = 0
    for entry in bands:
        if (type(entry) is not tuple or len(entry) != 2
                or type(entry[0]) is not str or not isinstance(entry[1], Pixel)):
            fail("Sample mask projection requires named scalar pixel bands")
        name_work += len(entry[0])
        if entry[1].op == "with_mask":
            weighted.append(entry[1])
    if not weighted:
        return image

    # The mask branch can itself contain real raster lineage, but that does
    # not give a source-free raw value a scientific sample grid. Inspect each
    # carrier's raw branch independently instead of trusting Image.source or
    # the union of both carrier branches.
    from .pixel_math_graph import _PixelFactsWalker

    facts = _PixelFactsWalker(translator)
    for carrier in weighted:
        if not facts.inspect(value_of(carrier)).sources:
            fail("Fractional mask sampling requires source-backed raw pixel values")

    # Account for scanning names, a new Image/band list and new band tuples,
    # plus one mask_apply Pixel for each directly weighted band, before making
    # the detached view. Pixel arguments and the original weights stay shared
    # immutable identities.
    work = 8 + 4 * len(bands) + name_work + 3 * len(weighted)
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or steps < 0
            or steps + work > MAX_TRANSLATOR_WORK):
        fail("Sample mask projection exceeds the 50000-step compilation work budget")
    translator.steps = steps + work

    weighted_ids = {id(pixel) for pixel in weighted}
    projected = []
    for name, pixel in bands:
        projected.append((
            name,
            mask_input_value(pixel) if id(pixel) in weighted_ids else pixel,
        ))
    return replace(image, bands=projected)
