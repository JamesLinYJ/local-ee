"""Image RGB/HSV conversion using the existing closed Float64 scalar IR."""
from __future__ import annotations

from .image_color_ir import (
    choose,
    logical,
    lookup_rgb_to_hsv_domain,
    mask_invalid,
    number,
    predicate,
    remember_rgb_to_hsv_domain,
    replace_bands,
    require_image,
    scalar,
)
from .ir import Pixel, fail


IMAGE_COLOR_FUNCTIONS = frozenset({"Image.rgbToHsv", "Image.hsvToRgb"})
IMAGE_COLOR_REQUIRED_ARGUMENTS = {
    "Image.rgbToHsv": frozenset({"image"}),
    "Image.hsvToRgb": frozenset({"image"}),
}
IMAGE_COLOR_OPTIONAL_ARGUMENTS = {
    "Image.rgbToHsv": frozenset(),
    "Image.hsvToRgb": frozenset(),
}
_RGB_NAMES = ("red", "green", "blue")
_HSV_NAMES = ("hue", "saturation", "value")


def _in_unit_interval(translator, minimum: Pixel, maximum: Pixel) -> Pixel:
    lower = predicate(translator, "gte", minimum, scalar(0.0))
    upper = predicate(translator, "lte", maximum, scalar(1.0))
    return logical(translator, "and", lower, upper)


def _rgb_to_hsv(translator, pixels: tuple[Pixel, Pixel, Pixel]):
    red, green, blue = pixels
    value = number(
        translator, "max2",
        number(translator, "max2", red, green), blue,
    )
    minimum = number(
        translator, "min2",
        number(translator, "min2", red, green), blue,
    )
    chroma = number(translator, "subtract", value, minimum)

    # Max ties use red, then green, then blue precedence. A zero-chroma pixel
    # has hue 0; at value 0 saturation is 0. These conventions make black,
    # grayscale and exact channel ties finite and deterministic.
    red_is_max = predicate(translator, "eq", value, red)
    green_is_max = predicate(translator, "eq", value, green)
    numerator = choose(
        translator, red_is_max,
        number(translator, "subtract", green, blue),
        choose(
            translator, green_is_max,
            number(translator, "subtract", blue, red),
            number(translator, "subtract", red, green),
        ),
    )
    offset = choose(
        translator, red_is_max, scalar(6.0),
        choose(translator, green_is_max, scalar(2.0), scalar(4.0)),
    )
    sector = number(
        translator, "mod",
        number(
            translator, "add",
            number(translator, "divide", numerator, chroma), offset,
        ),
        scalar(6.0),
    )
    hue = choose(
        translator, predicate(translator, "eq", chroma, scalar(0.0)),
        scalar(0.0), number(translator, "divide", sector, scalar(6.0)),
    )
    saturation = choose(
        translator, predicate(translator, "eq", value, scalar(0.0)),
        scalar(0.0), number(translator, "divide", chroma, value),
    )
    return hue, saturation, value, minimum, value


def _hsv_to_rgb(translator, pixels: tuple[Pixel, Pixel, Pixel]):
    hue, saturation, value = pixels
    # Hue is circular; adding a channel offset before a positive modulo makes
    # the documented endpoint 1 identical to 0 without a separate branch.
    scaled = number(translator, "multiply", hue, scalar(6.0))
    chroma = number(translator, "multiply", value, saturation)

    def channel(offset):
        # The standard six-sector triangle can be written with one positive
        # remainder and a clipped tent function. This keeps nested HSV→RGB
        # expressions shallow enough for the shared 50000-step compiler cap.
        if offset == 5:
            # On [0, 6], the red phase's wrapped [5, 6] interval always clips
            # to zero. A direct h6 - 1 keeps the same triangle without mod.
            phase = number(translator, "subtract", scaled, scalar(1.0))
        else:
            phase = number(
                translator, "mod",
                number(translator, "add", scaled, scalar(float(offset))),
                scalar(6.0),
            )
        opposite = number(translator, "subtract", scalar(4.0), phase)
        tent = number(
            translator, "max2", scalar(0.0),
            number(
                translator, "min2", phase,
                number(translator, "min2", opposite, scalar(1.0)),
            ),
        )
        return number(
            translator, "subtract", value,
            number(translator, "multiply", chroma, tent),
        )

    return channel(5), channel(3), channel(1)


def invoke_image_color(translator, name: str, arguments: dict):
    """Build a named 3-band conversion without changing its source lineage."""
    if name not in IMAGE_COLOR_FUNCTIONS:
        fail(f"Unsupported Image color conversion: {name}")
    image = require_image(
        translator, name, arguments,
        set(IMAGE_COLOR_REQUIRED_ARGUMENTS[name]),
        set(IMAGE_COLOR_OPTIONAL_ARGUMENTS[name]), min_bands=3, max_bands=3,
    )
    pixels = tuple(pixel for _band_name, pixel in image.bands)
    if name == "Image.rgbToHsv":
        result = _rgb_to_hsv(translator, pixels)
        output, minimum, maximum = result[:3], result[3], result[4]
        # Official docs require RGB channels in [0, 1]. Out-of-range valid
        # samples become NoData locally; there is no implicit clamp.
        valid = _in_unit_interval(translator, minimum, maximum)
        names = _HSV_NAMES
        inherited_domain = False
    else:
        # The same documented [0, 1] input-domain policy applies to HSV.
        result = _hsv_to_rgb(translator, pixels)
        output = result
        valid = lookup_rgb_to_hsv_domain(translator, pixels)
        inherited_domain = valid is not None
        if not inherited_domain:
            minimum = number(
                translator, "min2", number(translator, "min2", pixels[0], pixels[1]),
                pixels[2],
            )
            maximum = number(
                translator, "max2", number(translator, "max2", pixels[0], pixels[1]),
                pixels[2],
            )
            valid = _in_unit_interval(translator, minimum, maximum)
        names = _RGB_NAMES
    if name == "Image.hsvToRgb" and inherited_domain:
        # Every output channel depends on hue, saturation and value, whose
        # shared upstream NoData mask already carries this exact domain proof.
        # An additional per-output where/mask would be graph duplication.
        bands = list(zip(names, output))
    else:
        bands = [
            (band_name, mask_invalid(valid, value))
            for band_name, value in zip(names, output)
        ]
    if name == "Image.rgbToHsv":
        remember_rgb_to_hsv_domain(
            translator, tuple(value for _band_name, value in bands), valid,
        )
    return replace_bands(
        image,
        bands,
    )
