"""Precharged indexed materialization of finite ImageCollection frames."""
from __future__ import annotations

from dataclasses import replace

from .image_collection_link_common import band_names, charge, validate_properties
from .ir import Collection, Image, ImageSequence, Pixel, Source, fail, rebind


_MAX_IMAGES = 1000
_MAX_PROPERTIES = 10_000


def _source_scan(translator, source, label):
    if (not isinstance(source, Source) or type(source.cid) is not str
            or not source.cid or type(source.ids) is not tuple
            or type(source.names) is not tuple or type(source.alias) is not bool
            or len(source.ids) > _MAX_IMAGES or len(source.names) > _MAX_PROPERTIES):
        fail(f"{label} requires a valid finite ImageCollection lineage")
    charge(translator, 1 + len(source.cid) + len(source.ids) + len(source.names), label)
    ids = set()
    for item_id in source.ids:
        if type(item_id) is not str or not item_id:
            fail(f"{label} requires nonempty string image IDs")
        charge(translator, len(item_id), label)
        if item_id in ids:
            fail(f"{label} contains duplicate source image IDs")
        ids.add(item_id)
    names = set()
    for name in source.names:
        if type(name) is not str or not name:
            fail(f"{label} requires nonempty string source band names")
        charge(translator, len(name), label)
        if name in names:
            fail(f"{label} contains duplicate source band names")
        names.add(name)
    return source


def _pixel_rebind_work(translator, image, label):
    """Charge a conservative rebind walk before cloning a collection frame."""
    charge(translator, 1 + len(image.bands), label + " rebind scan")
    stack = [(pixel, False) for _, pixel in image.bands]
    active = set()
    seen_pixels = set()
    start = translator.steps
    while stack:
        value, leaving = stack.pop()
        if isinstance(value, (Pixel, tuple)):
            identity = id(value)
            if leaving:
                active.remove(identity)
                continue
            if identity in active:
                fail(f"{label} contains a cyclic band expression")
            if isinstance(value, Pixel) and identity in seen_pixels:
                continue
            if isinstance(value, Pixel):
                seen_pixels.add(identity)
                if type(value.args) is not tuple or type(value.op) is not str:
                    fail(f"{label} has a malformed pixel expression")
                charge(translator, 1 + len(value.args), label + " rebind scan")
                children = value.args
            else:
                charge(translator, 1 + len(value), label + " rebind scan")
                children = value
            active.add(identity)
            stack.append((value, True))
            stack.extend((child, False) for child in children)
        elif isinstance(value, Source):
            _source_scan(translator, value, label + " rebind source")
        elif isinstance(value, list):
            # rebind deliberately does not recursively rewrite list payloads.
            continue
    return translator.steps - start


def _preflight_properties(
    translator, item, image, cid, image_key_chars, copied_property_chars, label,
):
    properties = item.get("properties", {})
    if type(properties) is not dict or len(properties) > _MAX_PROPERTIES:
        fail(f"{label} source properties are malformed or exceed 10000 entries")
    charge(translator, 1 + len(properties), label + " source property scan")
    chars = 0
    for key, value in properties.items():
        if type(key) is not str:
            fail(f"{label} source property names must be strings")
        chars += len(key)
        charge(translator, len(key), label + " source property scan")
        # CatalogOperations._base_properties performs this same shallow value
        # check for DEM metadata. Reserve it before its first property copy.
        charge(
            translator, len(value) + 1 if type(value) is str else 1,
            label + " source property value scan",
        )

    if image.inherit_props:
        # Reserve the set construction before allocating it. This lets us
        # check the merged map size before any per-frame properties() work.
        charge(
            translator, 1 + len(properties) + chars,
            label + " retained property index",
        )
        retained = set(properties)
    else:
        charge(
            translator,
            1 + len(image.copied_props) + copied_property_chars,
            label + " retained property index",
        )
        retained = set()
        for key in image.copied_props:
            if key in properties:
                retained.add(key)
    # DEM normalization adds these reserved properties if missing. It is a
    # finite known expansion; general collection metadata is copied verbatim.
    if cid == "cop-dem-glo-30":
        charge(
            translator,
            1 + len("system:index") + len("system:time_start"),
            label + " retained DEM properties",
        )
        retained.update(("system:index", "system:time_start"))
    charge(
        translator, 1 + len(image.props) + image_key_chars,
        label + " output property shape",
    )
    retained.update(image.props)
    if len(retained) > _MAX_PROPERTIES:
        fail(f"{label} merged properties exceed 10000 entries")
    # _base_properties, properties(), then the image property overlay each
    # make a shallow map. Reserve these copies before invoking either path.
    unit = 1 + len(properties) + chars
    charge(
        translator,
        3 * unit + 2 * (1 + len(image.props) + image_key_chars),
        label + " frame property copies",
    )


def _collection_frames(translator, value, label):
    source = _source_scan(translator, value.source, label + " source scan")
    count = len(source.ids)
    if count > _MAX_IMAGES:
        fail(f"{label} supports at most 1000 images")
    image = value.image
    if not isinstance(image, Image):
        fail(f"{label} requires a concrete ImageCollection template")
    band_names(translator, image, label + " template")
    validate_properties(translator, image, label + " template")
    if type(image.inherit_props) is not bool:
        fail(f"{label} property inheritance flag is invalid")
    if type(image.copied_props) is not tuple or len(image.copied_props) > _MAX_PROPERTIES:
        fail(f"{label} copied property selection is malformed")
    charge(translator, 1 + len(image.copied_props), label + " copied property scan")
    copied_property_chars = 0
    for key in image.copied_props:
        if type(key) is not str or not key:
            fail(f"{label} copied property names must be strings")
        charge(translator, len(key), label + " copied property scan")
        copied_property_chars += len(key)

    # Per-frame overlays repeatedly copy these names. Charge the complete
    # character walk before recording the amount used by each frame preflight.
    charge(translator, 1 + len(image.props), label + " Image property copy scan")
    image_key_chars = 0
    for key in image.props:
        image_key_chars += len(key)
        charge(translator, len(key), label + " Image property copy scan")

    if count == 0:
        charge(translator, 1, label + " empty frame result")
        return []

    from .numeric_reducer_grid import _item_lookup

    lookup = _item_lookup(translator, source.cid)
    charge(translator, 1 + count, label + " indexed frame rows")
    item_rows = []
    for item_id in source.ids:
        item = lookup.get(item_id)
        if item is None:
            fail(f"{label} image ID is unavailable in the local catalogue")
        _preflight_properties(
            translator, item, image, source.cid, image_key_chars,
            copied_property_chars, label,
        )
        item_rows.append((item_id, item))

    per_frame_pixel_work = _pixel_rebind_work(translator, image, label)
    if count > 1:
        charge(
            translator, per_frame_pixel_work * (count - 1),
            label + " repeated frame rebinds",
        )
    charge(
        translator,
        count * (2 + 4 * len(image.bands) + len(source.cid)),
        label + " frame allocation and band copies",
    )
    charge(translator, 1 + count, label + " output frame list")

    result = []
    for item_id, item in item_rows:
        rebound = rebind(value, [item_id])
        original = translator._base_properties(item, source.cid)
        if image.inherit_props:
            properties = dict(original)
        else:
            properties = {
                key: original[key] for key in image.copied_props if key in original
            }
        properties = {**properties, **rebound.image.props}
        bands = [
            (name, Pixel("reduce_t", (pixel, "first")))
            for name, pixel in rebound.image.bands
        ]
        result.append(replace(rebound.image, props=properties, bands=bands))
    return result


def frames(translator, value, label):
    if isinstance(value, Collection):
        return _collection_frames(translator, value, label)
    if not isinstance(value, ImageSequence) or type(value.images) is not list:
        fail(f"{label} requires a finite ImageCollection")
    if len(value.images) > _MAX_IMAGES:
        fail(f"{label} supports at most 1000 images")
    charge(translator, 1 + len(value.images), label + " frame scan")
    for image in value.images:
        if not isinstance(image, Image):
            fail(f"{label} requires concrete Image frames")
        band_names(translator, image, label)
        validate_properties(translator, image, label)
    return value.images
