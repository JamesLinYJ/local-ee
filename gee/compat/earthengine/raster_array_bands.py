"""Typed, bounded containers for multiple fixed-shape raster array bands."""
from __future__ import annotations

from dataclasses import dataclass, replace

from .array_core import charge_array
from .ir import Image, Pixel, fail
from .metadata_ops import METADATA_HANDLERS, invoke_metadata
from .raster_array_core import RasterArrayImage, check_shape, wrap_array_image


MAX_ARRAY_BANDS = 8
MAX_ARRAY_BAND_CELLS = 64
MAX_ARRAY_BAND_NAME = 256


@dataclass(frozen=True)
class RasterArrayBands:
    """An Image's named array-valued bands with shared source metadata."""

    image: Image
    arrays: tuple[RasterArrayImage, ...]


def _measure(image, arrays):
    if not isinstance(image, Image):
        fail("RasterArrayBands metadata must be an Image")
    if image.bands:
        fail("RasterArrayBands metadata Image must not contain placeholder bands")
    if not isinstance(arrays, (tuple, list)) or not 1 <= len(arrays) <= MAX_ARRAY_BANDS:
        fail("RasterArrayBands requires 1..8 array-valued bands")

    cells = 0
    dimensions = 0
    name_chars = 0
    names = []
    for array in arrays:
        if not isinstance(array, RasterArrayImage) or array.image is not image:
            fail("RasterArrayBands arrays must share the exact metadata Image")
        count = check_shape(array.shape)
        if not isinstance(array.cells, tuple) or len(array.cells) != count:
            fail("RasterArrayBands cells must match each fixed shape")
        if any(not isinstance(pixel, Pixel) for pixel in array.cells):
            fail("RasterArrayBands cells must be Pixels")
        if not isinstance(array.mask, Pixel) or not (
            array.mask.boolean
            or array.mask.op == "constant" and array.mask.args == (None,)
        ):
            fail("RasterArrayBands masks must be boolean Pixels or NoData")
        if (not isinstance(array.name, str) or not array.name
                or len(array.name) > MAX_ARRAY_BAND_NAME):
            fail("RasterArrayBands names must be nonempty strings of at most 256 characters")
        if array.name in names:
            fail("RasterArrayBands band names must be unique")
        names.append(array.name)
        cells += count
        dimensions += len(array.shape)
        name_chars += len(array.name)
        if cells > MAX_ARRAY_BAND_CELLS:
            fail("RasterArrayBands exceeds 64 total array cells")
    # Work includes wrapper/shape/name scans and every scalar-cell scan.
    return len(arrays) + dimensions + name_chars + cells


def wrap_array_bands(translator, image, arrays):
    """Validate and detach a bounded bundle after precharging its full copy."""
    work = _measure(image, arrays)
    charge_array(translator, 2 * work)
    copied = tuple(
        wrap_array_image(
            image,
            tuple(int(axis) for axis in array.shape),
            tuple(pixel for pixel in array.cells),
            array.mask,
            array.name,
        )
        for array in arrays
    )
    return RasterArrayBands(image, copied)


def _require_bundle(translator, value, label):
    if not isinstance(value, RasterArrayBands):
        fail(f"{label} requires a multi-band RasterArrayBands value")
    charge_array(translator, _measure(value.image, value.arrays))
    return value


def select_array_values(translator, arrays, selectors, new_names=None):
    """Select typed logical array bands without changing their metadata Image."""
    if not isinstance(selectors, (list, tuple)):
        selectors = [selectors]
    if not selectors or len(selectors) > len(arrays):
        fail("Image.select requires one or more known array band selectors")

    indices = []
    selector_chars = 0
    for selector in selectors:
        if isinstance(selector, str):
            selector_chars += len(selector)
            matches = [index for index, array in enumerate(arrays)
                       if array.name == selector]
            if len(matches) != 1:
                fail(f"Image.select requires an exact array band name: {selector!r}")
            index = matches[0]
        elif type(selector) is int:
            if selector < 0 or selector >= len(arrays):
                fail("Image.select array band index is out of range")
            index = selector
        else:
            fail("Image.select array selectors must be exact names or nonnegative integers")
        if index in indices:
            fail("Image.select does not allow duplicate array bands")
        indices.append(index)

    if new_names is not None:
        if (not isinstance(new_names, (list, tuple))
                or len(new_names) != len(indices)
                or any(not isinstance(name, str) or not name
                       or len(name) > MAX_ARRAY_BAND_NAME for name in new_names)
                or len(set(new_names)) != len(new_names)):
            fail("Image.select newNames must be unique nonempty names matching the selection")
        names = tuple(new_names)
    else:
        names = tuple(arrays[index].name for index in indices)

    charge_array(translator, len(indices) + selector_chars + sum(map(len, names)))
    return tuple(replace(arrays[index], name=name)
                 for index, name in zip(indices, names))


def _selection(translator, bundle, selectors, new_names=None):
    selected = select_array_values(translator, bundle.arrays, selectors, new_names)
    if len(selected) == 1:
        return selected[0]
    return wrap_array_bands(translator, bundle.image, selected)


def _metadata(translator, name, arguments):
    translator.allowed(arguments, {
        "Element.get": {"object", "property"},
        "Image.get": {"object", "image", "property"},
        "Element.propertyNames": {"element"},
        "Element.set": {"object", "key", "value"},
        "Element.setMulti": {"object", "properties"},
        "Element.copyProperties": {"destination", "source", "properties", "exclude"},
        "Image.copyProperties": {"destination", "source", "properties", "exclude"},
    }[name])
    image_parameters = {"object", "image", "element", "destination", "source"}
    destination_key = "destination" if name.endswith("copyProperties") else "object"
    if name == "Image.get":
        destination_key = "image" if "image" in arguments else "object"
    destination = arguments.get(destination_key)
    converted = {
        key: value.image if key in image_parameters and isinstance(value, RasterArrayBands)
        else value
        for key, value in arguments.items()
    }
    result = invoke_metadata(translator, name, converted)
    if isinstance(result, Image) and isinstance(destination, RasterArrayBands):
        charge_array(translator, len(destination.arrays))
        arrays = tuple(replace(array, image=result) for array in destination.arrays)
        return wrap_array_bands(translator, result, arrays)
    return result


def handles_array_bands(name, arguments):
    """Route bundle operations before single-array and ordinary Image paths."""
    image_parameters = {
        "Image": {"input"},
        "Image.select": {"input"},
        "Image.rename": {"input"},
        "Image.bandNames": {"image"},
        "Image.cast": {"image"},
    }
    if name in image_parameters:
        return any(isinstance(arguments.get(key), RasterArrayBands)
                   for key in image_parameters[name])
    if name in METADATA_HANDLERS:
        return any(
            key in {"object", "image", "element", "destination", "source"}
            and isinstance(value, RasterArrayBands)
            for key, value in arguments.items()
        )
    return ((name == "Image" or name.startswith("Image."))
            and any(isinstance(value, RasterArrayBands) for value in arguments.values()))


def invoke_array_bands(translator, name, arguments):
    """Evaluate the supported typed-container Image and metadata operations."""
    if name == "Image":
        translator.allowed(arguments, {"input"})
        return _require_bundle(translator, arguments.get("input"), "Image")
    if name in {"Image.toFloat", "Image.toDouble"}:
        translator.allowed(arguments, {"value"})
        if "value" not in arguments:
            fail(f"{name} requires value")
        bundle = _require_bundle(translator, arguments["value"], name)
        arrays = tuple(
            translator.invoke(name, {"value": array})
            for array in bundle.arrays
        )
        return wrap_array_bands(translator, bundle.image, arrays)
    if name in METADATA_HANDLERS:
        return _metadata(translator, name, arguments)
    if name == "Image.bandNames":
        translator.allowed(arguments, {"image"})
        bundle = _require_bundle(translator, arguments.get("image"), name)
        charge_array(translator, sum(len(array.name) for array in bundle.arrays))
        return [array.name for array in bundle.arrays]
    if name == "Image.select":
        translator.allowed(arguments, {"input", "bandSelectors", "newNames"})
        if "bandSelectors" not in arguments:
            fail("Image.select requires bandSelectors")
        bundle = _require_bundle(translator, arguments.get("input"), name)
        return _selection(translator, bundle, arguments["bandSelectors"],
                          arguments.get("newNames"))
    if name == "Image.rename":
        translator.allowed(arguments, {"input", "names"})
        if "names" not in arguments:
            fail("Image.rename requires names")
        bundle = _require_bundle(translator, arguments.get("input"), name)
        names = arguments["names"]
        if (not isinstance(names, (list, tuple)) or len(names) != len(bundle.arrays)
                or any(not isinstance(item, str) or not item or len(item) > MAX_ARRAY_BAND_NAME
                       for item in names)
                or len(set(names)) != len(names)):
            fail("Image.rename names must be unique nonempty strings matching the band count")
        charge_array(translator, sum(map(len, names)) + len(names))
        renamed = tuple(replace(array, name=band_name)
                        for array, band_name in zip(bundle.arrays, names))
        return wrap_array_bands(translator, bundle.image, renamed)
    fail(f"Unsupported operation on a multi-band raster array bundle: {name}")
