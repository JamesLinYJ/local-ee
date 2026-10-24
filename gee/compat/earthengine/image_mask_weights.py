"""Keep a scientific pixel and its fractional mask as separate immutable IR.

The weight getter is the first audited consumer.  A weight-bearing value must
not enter a legacy NoData-only consumer: those consumers need their own mask
propagation/encoding contracts before they can be enabled.
"""
from __future__ import annotations

import math
from dataclasses import replace

from .ir import Pixel, as_image, const, fail, pairs


MASK_PROJECTION_OPS = frozenset({"mask_validity", "mask_update", "mask_apply"})
MASK_WEIGHT_ARGUMENTS = {
    "Image.updateMask": (frozenset({"image", "mask"}), frozenset()),
    "Image.mask": (frozenset({"image"}), frozenset({"mask"})),
}


def _parts(pixel):
    if (not isinstance(pixel, Pixel) or pixel.op != "with_mask"
            or type(pixel.args) is not tuple or len(pixel.args) != 2
            or any(not isinstance(value, Pixel) for value in pixel.args)):
        fail("Malformed independent image mask")
    return pixel.args


def mask_of(pixel):
    """Return numeric weights; zero is an ordinary valid weight value."""
    return _parts(pixel)[1] if pixel.op == "with_mask" else Pixel("mask_validity", (pixel,))


def value_of(pixel):
    return _parts(pixel)[0] if pixel.op == "with_mask" else pixel


def mask_input_value(pixel):
    """An update mask contributes values only where its own mask is nonzero."""
    return Pixel("mask_apply", _parts(pixel)) if pixel.op == "with_mask" else pixel


def _charge_bands(translator, *images):
    counts = [len(image.bands) for image in images]
    if any(not 1 <= count <= 10_000 for count in counts):
        fail("Image mask operations require1..10000 bands")
    amount = 12 * sum(counts) + 8
    steps = getattr(translator, "steps", None)
    if type(steps) is not int or steps < 0 or steps + amount > 50_000:
        fail("Image mask operations exceed the shared50000-step compilation work budget")
    translator.steps += amount


def _check_literal_mask(pixel):
    if pixel.op != "constant":
        return
    value = pixel.args[0]
    if (type(value) not in (int, float, bool) or not math.isfinite(value)
            or not 0 <= value <= 1):
        fail("updateMask requires finite mask values in[0,1]")


def invoke_mask_weights(translator, name, arguments):
    translator.allowed(arguments, {"image", "mask"})
    if "image" not in arguments:
        fail(f"{name} requires image")
    image = as_image(arguments["image"])
    if name == "Image.mask":
        if arguments.get("mask") is not None:
            fail("Image.mask setter is unsupported; use updateMask")
        _charge_bands(translator, image)
        return replace(image, bands=[(band, mask_of(pixel)) for band, pixel in image.bands])
    if name != "Image.updateMask" or "mask" not in arguments:
        fail("Image.updateMask requires image and mask")
    mask = as_image(arguments["mask"])
    _charge_bands(translator, image, mask)
    if len(mask.bands) not in {1, len(image.bands)}:
        fail("updateMask needs one broadcast mask band or the same number of bands as the Image")
    _, _, matched = pairs(image, mask)
    for _band, _pixel, mask_pixel in matched:
        _check_literal_mask(mask_pixel)
    binary_only = all(
        pixel.op != "with_mask" and mask_pixel.op != "with_mask"
        and (mask_pixel.boolean or mask_pixel.op == "constant" and mask_pixel.args[0] in (0, 1))
        for _band, pixel, mask_pixel in matched
    )
    if binary_only:
        # Preserve the established binary value/NoData path and its precision.
        return replace(image, bands=[
            (band, Pixel("if", (mask_pixel, pixel, const(None))))
            for band, pixel, mask_pixel in matched
        ])
    translator.warn(
        "Fractional updateMask weights are retained independently. Their numeric mask() "
        "view is supported; weighted value arithmetic, statistics, visualization and "
        "export require separate consumers. Composition follows the documented "
        "replacement at nonzero old masks; Google numerical equivalence is unverified."
    )
    return replace(image, bands=[
        (band, Pixel("with_mask", (
            value_of(pixel), Pixel("mask_update", (mask_of(pixel), mask_input_value(mask_pixel))),
        ), pixel.boolean))
        for band, pixel, mask_pixel in matched
    ])
