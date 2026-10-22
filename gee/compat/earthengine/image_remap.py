"""Bounded scalar Image.remap construction for the Earth Engine IR."""
from __future__ import annotations

from dataclasses import replace

from ...remap_spec import prepare_remap_spec
from .ir import Image, Pixel, UnsupportedEEError, fail


MAX_TRANSLATOR_WORK = 50_000
_ARGUMENTS = {"image", "from", "to", "defaultValue", "bandName"}


def _measure_wire_value(value, remaining):
    """Conservatively price spec serialization without validating its values."""
    work = 0
    pending = [value]
    while pending:
        current = pending.pop()
        if type(current) is str:
            cost = 1 + 6 * len(current)
        elif type(current) is bool or current is None:
            cost = 1
        elif type(current) is int:
            cost = 1 + (current.bit_length() * 302 // 1000) + 2
        elif type(current) is float:
            cost = 24
        elif type(current) is list:
            cost = 1 + len(current)
            pending.extend(current)
        elif type(current) is dict:
            cost = 1 + len(current)
            for key, child in current.items():
                cost += 6 * len(key) if type(key) is str else 1
                pending.append(child)
        else:
            # The shared remap spec validator will reject arrays and other
            # objects; do not walk their private representations here.
            cost = 1
        work += cost
        if work > remaining:
            return work
    return work


def _pixel_is_bound(pixel):
    seen = set()

    def visit(value):
        if isinstance(value, Pixel):
            if id(value) in seen:
                return False
            seen.add(id(value))
            if value.op == "band" and len(value.args) == 2 and value.args[0] is not None:
                return True
            return any(visit(argument) for argument in value.args)
        if isinstance(value, (tuple, list)):
            return any(visit(argument) for argument in value)
        return False

    return visit(pixel)


def _charge(translator, work):
    if work < 0 or translator.steps + work > MAX_TRANSLATOR_WORK:
        fail("Image.remap exceeds the 50000-step compilation work budget")
    translator.steps += work


def invoke_image_remap(translator, arguments):
    """Select one bound scalar band and attach the canonical remap wire."""
    translator.allowed(arguments, _ARGUMENTS)
    for required in ("image", "from", "to"):
        if required not in arguments:
            fail(f"Image.remap requires {required}")

    image = arguments["image"]
    from_values, to_values = arguments["from"], arguments["to"]
    default = arguments.get("defaultValue")
    band_name = arguments.get("bandName")
    if not isinstance(image, Image):
        from .raster_array_core import RasterArrayImage

        if isinstance(image, RasterArrayImage):
            fail("Image.remap does not support array images")
        fail("Image.remap image must be a bound Earth Engine Image")
    if type(image.bands) is not list or not image.bands:
        fail("Image.remap requires at least one named scalar input band")

    # Charge the band lookup before scanning it; the supported compiler domain
    # is bounded by shared work rather than a new remap-only band limit.
    band_work = len(image.bands) + 1
    for item in image.bands:
        if type(item) is tuple and len(item) == 2 and type(item[0]) is str:
            band_work += len(item[0])
    _charge(translator, band_work)
    if any(type(item) is not tuple or len(item) != 2 or type(item[0]) is not str
           or not isinstance(item[1], Pixel) for item in image.bands):
        fail("Image.remap requires named scalar pixel bands")
    if band_name is None:
        selected_name, selected_pixel = image.bands[0]
    else:
        if type(band_name) is not str:
            fail("Image.remap bandName must be a static string")
        matches = [item for item in image.bands if item[0] == band_name]
        if len(matches) != 1:
            fail("Image.remap bandName must select exactly one input band")
        selected_name, selected_pixel = matches[0]

    try:
        from_work = _measure_wire_value(from_values, MAX_TRANSLATOR_WORK - translator.steps)
        to_work = _measure_wire_value(to_values, MAX_TRANSLATOR_WORK - translator.steps - from_work)
        default_work = _measure_wire_value(
            default, MAX_TRANSLATOR_WORK - translator.steps - from_work - to_work,
        )
        from .sampled_training import image_work_estimate

        pixel_work = image_work_estimate(Image([(selected_name, selected_pixel)], {}))
    except (TypeError, ValueError, OverflowError, RecursionError):
        fail("Image.remap specification or input exceeds the 50000-step compilation work budget")
    # Include fixed JSON field/punctuation overhead and charge serialization
    # before the canonical helper validates and constructs the wire string.
    spec_work = from_work + to_work + default_work + 64
    _charge(translator, 2 * spec_work + pixel_work + 4)
    if not _pixel_is_bound(selected_pixel):
        fail("Image.remap requires one bound scalar input band; constants and arrays are unsupported")

    try:
        spec = prepare_remap_spec(from_values, to_values, default)
    except UnsupportedEEError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Image.remap specification is unsupported: {exc}")
    return replace(image, bands=[("remapped", Pixel("remap", (selected_pixel, spec)))])
