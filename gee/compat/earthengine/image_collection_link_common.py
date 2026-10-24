"""Shared finite-value validation for collection linking and combination."""
from __future__ import annotations

import math

from .ir import Collection, Image, ImageSequence, Pixel, fail
from .owned_metadata_values import owned_metadata_copy


COLLECTION_LINK_FUNCTIONS = frozenset({
    "Image.linkCollection", "ImageCollection.combine",
})
_MAX_IMAGES = 1000
_MAX_BANDS = 10_000
_MAX_WORK = 50_000


def charge(translator, amount: int, label: str) -> None:
    steps = getattr(translator, "steps", None)
    if (type(amount) is not int or amount < 0 or amount > _MAX_WORK
            or type(steps) is not int or steps < 0 or steps + amount > _MAX_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def arguments(translator, name, values, required, optional=()):
    if type(values) is not dict:
        fail(f"{name} arguments must be a dictionary")
    translator.allowed(values, set(required) | set(optional))
    missing = set(required) - values.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def property_key(translator, value, label):
    if type(value) is not str:
        fail(f"{label} requires a nonempty flat property key")
    charge(translator, 1 + len(value), label)
    if not value or "." in value:
        fail(f"{label} requires a nonempty flat property key")
    return value


def names(translator, value, label):
    """Accept the pinned string-or-list shape; null and [] select nothing."""
    if value is None:
        return ()
    if type(value) is str:
        values = [value]
    elif type(value) is list:
        values = value
    else:
        fail(f"{label} must be a string, a list of strings, or null")
    if len(values) > _MAX_BANDS:
        fail(f"{label} supports at most 10000 names")
    charge(translator, 1 + len(values), label)
    result = []
    seen = set()
    for item in values:
        if type(item) is not str or not item:
            fail(f"{label} names must be nonempty strings")
        charge(translator, len(item), label)
        if item in seen:
            fail(f"{label} cannot contain duplicate names")
        seen.add(item)
        result.append(item)
    return tuple(result)


def band_names(translator, image, label):
    if not isinstance(image, Image) or type(image.bands) is not list:
        fail(f"{label} must be a concrete Image with named bands")
    if len(image.bands) > _MAX_BANDS:
        fail(f"{label} exceeds 10000 bands")
    charge(translator, 1 + len(image.bands), label)
    result = []
    seen = set()
    for band in image.bands:
        if (type(band) is not tuple or len(band) != 2
                or type(band[0]) is not str or not band[0]
                or not isinstance(band[1], Pixel)):
            fail(f"{label} has a malformed band")
        charge(translator, len(band[0]), label)
        if band[0] in seen:
            fail(f"{label} has duplicate band names")
        seen.add(band[0])
        result.append(band[0])
    return tuple(result)


def validate_properties(translator, image, label):
    if type(image.props) is not dict or len(image.props) > _MAX_BANDS:
        fail(f"{label} Image properties must be a dictionary with at most 10000 entries")
    charge(translator, 1 + len(image.props), label + " property map scan")
    for key in image.props:
        if type(key) is not str:
            fail(f"{label} Image property names must be strings")
        charge(translator, len(key), label + " property map scan")


def frames(translator, value, label):
    if not isinstance(value, (Collection, ImageSequence)):
        fail(f"{label} requires a finite ImageCollection")
    from .image_collection_link_frames import frames as materialize

    return materialize(translator, value, label)


def match_value(translator, image, key, label, *, system_index=False):
    charge(translator, 1 + len(key), label)
    if key not in image.props:
        return None
    value = image.props[key]
    kind = type(value)
    if value is None:
        return None
    if kind is str:
        charge(translator, len(value), label)
        if not value:
            return None
        return ("string", value)
    if kind is bool:
        if system_index:
            fail(f"{label} system:index must be a nonempty string")
        return ("boolean", value)
    if kind is int:
        if system_index:
            fail(f"{label} system:index must be a nonempty string")
        charge(translator, max(1, value.bit_length()), label)
        return ("number", value)
    if kind is float:
        if system_index:
            fail(f"{label} system:index must be a nonempty string")
        if not math.isfinite(value):
            fail(f"{label} match property must be finite")
        return ("number", value)
    fail(f"{label} match property must be a flat scalar value")


def index(translator, images, key, label, *, system_index=False):
    charge(translator, 1 + len(images), label + " key index")
    result = {}
    for image in images:
        value = match_value(translator, image, key, label, system_index=system_index)
        if value is None:
            continue
        if value in result:
            fail(f"{label} contains duplicate match keys")
        result[value] = image
    return result


def property_updates(translator, primary, secondary, selected, label):
    if not selected:
        return primary.props
    if type(primary.props) is not dict or len(primary.props) > _MAX_BANDS:
        fail(f"{label} primary properties exceed 10000 entries")
    charge(translator, 1 + len(primary.props), label + " primary property copy")
    for key in primary.props:
        if type(key) is not str:
            fail(f"{label} primary property names must be strings")
        charge(translator, len(key), label + " primary property copy")
    updates = {}
    for key in selected:
        value = None if secondary is None else secondary.props.get(key)
        updates[key] = owned_metadata_copy(
            translator, value, label + " linked property " + key,
        )
    result = dict(primary.props)
    result.update(updates)
    return result
