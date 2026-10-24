"""Bounded Image pixel-math IR construction for the pinned EE SDK."""
from __future__ import annotations

import math
from dataclasses import replace

from gee.pixel_math_contract import PIXEL_MATH_ARITIES, pixel_math_arity

from .ir import Image, Pixel, UnsupportedEEError, as_image, fail, pairs


IMAGE_PIXEL_MATH_FUNCTIONS = frozenset(
    "Image." + operation for operation in PIXEL_MATH_ARITIES
)
_MAX_TRANSLATOR_WORK = 50_000
_MAX_IMAGE_BANDS = 10_000
_MAX_EXACT_SCALAR = 2**53


def _shape(value, name):
    """Count a supported operand without materializing its band list."""
    if isinstance(value, Image):
        amount, scan = len(value.bands), 0
    elif type(value) is list:
        amount, scan = len(value), len(value)
    elif type(value) in (int, float, bool):
        amount, scan = 1, 0
    else:
        fail(f"{name} requires Image or scalar operands")
    if not amount:
        fail(f"{name} requires at least one band per operand")
    if amount > _MAX_IMAGE_BANDS:
        fail(f"{name} operand exceeds {_MAX_IMAGE_BANDS} bands")
    return amount, scan


def _validate_operand(value, name):
    """Reject malformed SDK literal bands before IR list construction."""
    if isinstance(value, Image):
        if type(value.bands) is not list:
            fail(f"{name} requires named Image bands")
        for item in value.bands:
            if (type(item) is not tuple or len(item) != 2
                    or type(item[0]) is not str or not isinstance(item[1], Pixel)):
                fail(f"{name} requires named scalar Image bands")
        return
    values = value if type(value) is list else (value,)
    for item in values:
        if type(item) is bool:
            continue
        if type(item) is int:
            if abs(item) > _MAX_EXACT_SCALAR:
                fail(f"{name} integer literals above 2^53 are unsupported")
        elif type(item) is float:
            if not math.isfinite(item) or abs(item) > _MAX_EXACT_SCALAR:
                fail(f"{name} requires finite exact numeric literals within 2^53")
        else:
            fail(f"{name} requires finite numeric Image or scalar operands")


def _charge(translator, work, name):
    if work < 0 or translator.steps + work > _MAX_TRANSLATOR_WORK:
        fail(f"{name} exceeds the 50000-step compilation work budget")
    translator.steps += work


def _unary(translator, operation, value):
    image = as_image(value)
    from .image_mask_math import unary_pixel

    return replace(
        image,
        bands=[(name, unary_pixel(translator, "math_" + operation, pixel))
               for name, pixel in image.bands],
    )


def _binary(translator, operation, image1, image2):
    from .image_mask_math import binary_pixel

    left = as_image(image1)
    right = as_image(image2)
    left, right, matched = pairs(left, right)
    return Image(
        [(name, binary_pixel(translator, "math_" + operation, x, y))
         for name, x, y in matched],
        dict(left.props),
        left.source or right.source,
        left.mapped or right.mapped,
        left.inherit_props,
        left.copied_props,
        left.footprint,
        left.footprint_is_absolute,
    )


def invoke_image_pixel_math(translator, name, arguments):
    """Create a one-pixel-operation-per-band expression with SDK ordering."""
    if name not in IMAGE_PIXEL_MATH_FUNCTIONS:
        fail(f"Unsupported Image pixel math: {name}")
    translator._pixel_math_seen = True
    operation = name.split(".", 1)[1]
    arity = pixel_math_arity(operation)
    parameters = ("value",) if arity == 1 else ("image1", "image2")
    translator.allowed(arguments, set(parameters))
    missing = [parameter for parameter in parameters if parameter not in arguments]
    if missing:
        fail(f"{name} requires {', '.join(missing)}")

    shapes = [_shape(arguments[parameter], name) for parameter in parameters]
    counts = [amount for amount, _ in shapes]
    if arity == 2 and counts[0] != 1 and counts[1] != 1 and counts[0] != counts[1]:
        fail("Image operands need equal band counts or a single broadcast band")
    output_count = max(counts)
    # Charge list scans, the bounded input walk and output Pixel/band allocation
    # before as_image() or pairs() creates any per-band objects.
    work = 2 * sum(scan for _, scan in shapes) + sum(counts) + 2 * output_count
    _charge(translator, work, name)
    for parameter in parameters:
        _validate_operand(arguments[parameter], name)

    try:
        if arity == 1:
            return _unary(translator, operation, arguments["value"])
        return _binary(
            translator, operation, arguments["image1"], arguments["image2"],
        )
    except OverflowError:
        raise UnsupportedEEError(f"{name} operands must be finite numeric values") from None
