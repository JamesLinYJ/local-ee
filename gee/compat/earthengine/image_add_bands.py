"""Bounded ordered band merging, explicit constant binding and name suffixes."""
from __future__ import annotations

from dataclasses import replace

from .array_core import charge_array
from .constant_bands import bind_source_bands
from .ir import Pixel, as_image, fail


MAX_BANDS = 10_000


def _scan(translator, image):
    if type(image.bands) is not list or len(image.bands) > MAX_BANDS:
        fail("Image.addBands supports at most10000 bands per input")
    charge_array(translator, 2 * len(image.bands) + 1)
    names = set()
    for entry in image.bands:
        if (type(entry) is not tuple or len(entry) != 2
                or type(entry[0]) is not str or not isinstance(entry[1], Pixel)):
            fail("Image.addBands requires named scalar Pixel bands")
        name = entry[0]
        charge_array(translator, 2 * len(name) + 2)
        if name in names:
            fail("Image.addBands input band names must be unique")
        names.add(name)


def _owned_result(translator, image, bands):
    if type(image.props) is not dict:
        fail("Image.addBands requires Image properties")
    charge_array(translator, len(image.props) + 1)
    return replace(image, bands=bands, props=dict(image.props))


def add_bands(translator, arguments):
    translator.allowed(arguments, {"dstImg", "srcImg", "names", "overwrite"})
    if not {"dstImg", "srcImg"} <= arguments.keys():
        fail("Image.addBands requires dstImg and srcImg")
    overwrite = arguments.get("overwrite")
    if overwrite is None:
        overwrite = False
    elif type(overwrite) is not bool:
        fail("Image.addBands overwrite must be a boolean or null")
    image, source = as_image(arguments["dstImg"]), as_image(arguments["srcImg"])
    _scan(translator, image)
    _scan(translator, source)
    names = arguments.get("names")
    if type(names) is list and not names:
        source = replace(source, bands=[])
    elif names is not None:
        source = translator.select(source, names)
    if not source.bands:
        # A selector yielding no bands cannot contribute a hidden grid/source.
        charge_array(translator, len(image.bands) + 1)
        return _owned_result(translator, image, list(image.bands))
    if not overwrite and len(image.bands) + len(source.bands) > MAX_BANDS:
        fail("Image.addBands exceeds10000 output bands")
    if image.source is None and source.source is not None:
        charge_array(translator, 2 * len(image.bands) + len(source.bands) + 8)
        image = replace(
            image, bands=bind_source_bands(image, source, translator=translator),
            source=source.source, footprint=source.footprint,
            footprint_is_absolute=source.footprint_is_absolute,
        )
    bound = bind_source_bands(source, image, translator=translator)
    charge_array(translator, 2 * len(image.bands) + len(bound) + 2)
    output = list(image.bands)
    positions = {name: index for index, (name, _) in enumerate(output)}
    suffixes = {}
    for base, pixel in bound:
        charge_array(translator, len(base) + 4)
        if overwrite and base in positions:
            output[positions[base]] = (base, pixel)
            continue
        name = base
        if name in positions:
            suffix = suffixes.get(base, 1)
            while True:
                digits = 1 if suffix < 10 else 2 if suffix < 100 else 3 if suffix < 1000 else 5
                charge_array(translator, 2 * (len(base) + digits + 1))
                name = f"{base}_{suffix}"
                suffix += 1
                if name not in positions:
                    break
            suffixes[base] = suffix
        if len(output) >= MAX_BANDS:
            fail("Image.addBands exceeds10000 output bands")
        charge_array(translator, len(name) + 3)
        positions[name] = len(output)
        output.append((name, pixel))
    return _owned_result(translator, replace(image, source=image.source or source.source), output)
