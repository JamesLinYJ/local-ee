"""Bounded Image.unmix argument validation and component IR construction."""
from __future__ import annotations

from dataclasses import replace

from .array_core import charge_array
from .ir import Image, Pixel, fail
from gee.spectral_unmix_spec import prepare_spectral_unmix_spec


IMAGE_UNMIX_FUNCTIONS = frozenset({"Image.unmix"})
IMAGE_UNMIX_ARGUMENTS = {
    "Image.unmix": (
        frozenset({"image", "endmembers"}),
        frozenset({"sumToOne", "nonNegative"}),
    ),
}
_MAX_INPUT_BANDS = 8


def invoke_image_unmix(translator, name, arguments):
    """Lower Image.unmix to one shared native producer with ordered outputs."""
    if name not in IMAGE_UNMIX_FUNCTIONS:
        fail(f"Unsupported spectral unmix operation: {name}")
    required, optional = IMAGE_UNMIX_ARGUMENTS[name]
    translator.allowed(arguments, required | optional)
    for required_name in ("image", "endmembers"):
        if required_name not in arguments:
            fail(f"Image.unmix requires {required_name}")

    image = arguments["image"]
    if not isinstance(image, Image):
        fail("Image.unmix requires a scalar Earth Engine Image")
    if type(image.bands) is not list or not 1 <= len(image.bands) <= _MAX_INPUT_BANDS:
        fail("Image.unmix supports 1..8 ordered scalar input bands")

    endmembers = arguments["endmembers"]
    if type(endmembers) not in (list, tuple) or not 1 <= len(endmembers) <= _MAX_INPUT_BANDS:
        fail("Image.unmix requires 1..8 endmember components")
    # Reserve the bounded row-shape scan before iterating any caller matrix.
    charge_array(translator, 2 * len(endmembers) + len(image.bands) + 16)
    columns = None
    cells = 0
    for row in endmembers:
        if type(row) not in (list, tuple) or not 1 <= len(row) <= _MAX_INPUT_BANDS:
            fail("Image.unmix endmembers require 1..8 coefficients per component")
        if columns is None:
            columns = len(row)
        elif columns != len(row):
            fail("Image.unmix endmembers must form a rectangular matrix")
        cells += len(row)
    if columns != len(image.bands):
        fail("Image.unmix endmember columns must match the ordered input band count")

    sum_to_one = arguments.get("sumToOne", False)
    non_negative = arguments.get("nonNegative", False)
    if type(sum_to_one) is not bool or type(non_negative) is not bool:
        fail("Image.unmix sumToOne and nonNegative must be booleans")

    # Reserve the bounded coefficient-type scan before reading each value.
    charge_array(translator, cells + len(endmembers) + len(image.bands) + 16)
    coefficient_work = 0
    for row in endmembers:
        for value in row:
            if type(value) is int:
                coefficient_work += 1 + value.bit_length()
            elif type(value) is float:
                coefficient_work += 24
            else:
                coefficient_work += 1

    # Reserve coefficient conversion, wire encoding, input scans and every
    # component wrapper before copying the small matrix or allocating IR nodes.
    spec_bound = 256 + 18 * cells + 3 * len(endmembers)
    charge_array(
        translator,
        coefficient_work + 3 * cells + 4 * len(image.bands)
        + 3 * len(endmembers) + 2 * spec_bound + 64,
    )
    for item in image.bands:
        if (type(item) is not tuple or len(item) != 2 or type(item[0]) is not str
                or not isinstance(item[1], Pixel)):
            fail("Image.unmix requires named scalar input bands")
        charge_array(translator, len(item[0]))
    try:
        spec = prepare_spectral_unmix_spec(endmembers, sum_to_one, non_negative)
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as error:
        fail(f"Image.unmix specification is unsupported: {error}")

    inputs = tuple(pixel for _band_name, pixel in image.bands)
    outputs = [
        (f"unmix_{index}", Pixel("unmix_component", (inputs, spec, index)))
        for index in range(len(endmembers))
    ]
    return replace(image, bands=outputs)
