"""Image ID and typed metadata-to-raster access.

Local policy: an image ID must come from one concrete loaded item. Metadata
values must be present numeric properties and are materialized with the
property key as the default band name on that item's finite raster footprint.
"""
from __future__ import annotations

import math

from .constant_bands import bind_source_bands, destination_template
from .ir import Image, Source, Pixel, fail
from .regex_values import measure_utf8


IMAGE_METADATA_RASTER_FUNCTIONS = frozenset({"Image.id", "Image.metadata"})
IMAGE_METADATA_RASTER_ARGUMENTS = {
    "Image.id": (frozenset({"element"}), frozenset()),
    "Image.metadata": (frozenset({"image", "property"}), frozenset({"name"})),
}
_MAX_WORK = 50_000
_MAX_BANDS = 10_000
_MAX_EXACT_CONSTANT = 2**53


def _charge(translator, amount, label):
    if (type(amount) is not int or amount < 0
            or type(translator.steps) is not int or translator.steps < 0
            or translator.steps + amount > _MAX_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps += amount


def _required(translator, name, arguments, required, optional=()):
    translator.allowed(arguments, set(required) | set(optional))
    missing = set(required) - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def _image(value, name):
    if not isinstance(value, Image):
        fail(f"{name} requires an Image")
    if len(value.bands) > _MAX_BANDS:
        fail(f"{name} input exceeds 10000 bands")
    return value


def _image_id(translator, arguments):
    name = "Image.id"
    _required(translator, name, arguments, {"element"})
    image = _image(arguments["element"], name)
    source = image.source
    if not isinstance(source, Source) or len(source.ids) != 1:
        fail("Image.id requires one actual local source item identity")
    item_id = source.ids[0]
    if type(item_id) is not str or not item_id:
        fail("Image.id requires a nonempty actual local source item identity")
    measure_utf8(translator, item_id, name + " result")
    return item_id


def _numeric_property(image, property_name):
    if property_name not in image.props:
        fail(f"Image.metadata property is unavailable: {property_name}")
    value = image.props[property_name]
    if type(value) not in (int, float):
        fail("Image.metadata requires an actual numeric metadata property")
    if type(value) is int and abs(value) > _MAX_EXACT_CONSTANT:
        fail("Image.metadata property exceeds the local exact Float64 constant range")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        fail("Image.metadata property must be representable as a finite Float64 constant")
    if not math.isfinite(value):
        fail("Image.metadata property must be finite")
    # The existing local constant-on-grid process guarantees exact scalar
    # identity only through 2^53; keep that boundary instead of silently
    # changing a metadata value before creating a raster.
    if abs(value) > _MAX_EXACT_CONSTANT:
        fail("Image.metadata property exceeds the local exact Float64 constant range")
    return value


def _metadata(translator, arguments):
    name = "Image.metadata"
    _required(translator, name, arguments, {"image", "property"}, {"name"})
    image = _image(arguments["image"], name)
    property_name = arguments["property"]
    if type(property_name) is not str:
        fail("Image.metadata property must be a string")
    measure_utf8(translator, property_name, name + " property")
    band_name = arguments.get("name")
    if band_name is None:
        band_name = property_name
    elif type(band_name) is not str:
        fail("Image.metadata name must be a string or null")
    if band_name != property_name:
        measure_utf8(translator, band_name, name + " band name")
    value = _numeric_property(image, property_name)

    if not isinstance(image.source, Source) or not image.source.ids:
        fail("Image.metadata requires a real local raster source and finite grid")
    # `Image.metadata` is a Double constant with its own valid-pixel mask. It
    # borrows only an actual input raster's finite grid/footprint; it does not
    # propagate that raster band's NoData mask or invent a default grid.
    _charge(translator, 2 * len(image.bands) + 2, name + " grid discovery")
    if destination_template(image) is None:
        fail("Image.metadata requires an actual raster band to supply its grid")

    # Keep the source-side constant free of a separate footprint so the
    # existing binder can take the real destination footprint from `image`.
    unbound = Image([(band_name, Pixel("constant", (value,)))], {})
    return Image(
        bind_source_bands(unbound, image, translator=translator), dict(image.props), image.source,
        image.mapped, image.inherit_props, image.copied_props,
        image.footprint, image.footprint_is_absolute,
    )


def invoke_image_metadata_raster(translator, name, arguments):
    """Evaluate actual source IDs and numeric properties as finite image values."""
    if name == "Image.id":
        return _image_id(translator, arguments)
    if name == "Image.metadata":
        return _metadata(translator, arguments)
    fail(f"Unsupported Image metadata raster operation: {name}")


__all__ = [
    "IMAGE_METADATA_RASTER_ARGUMENTS", "IMAGE_METADATA_RASTER_FUNCTIONS",
    "invoke_image_metadata_raster",
]
