"""Bounded iteration over finite ImageCollections and explicit ImageSequences."""
from __future__ import annotations

from dataclasses import replace

from ...dem_contract import COLLECTION_ID as DEM_COLLECTION_ID
from .ir import Collection, Function, Image, ImageSequence, Pixel, Source, fail, rebind


_MAX_FRAMES = 1000
_MAX_WORK = 50_000


def _charge(translator, amount, label):
    if (type(amount) is not int or amount < 0
            or type(translator.steps) is not int or translator.steps < 0
            or translator.steps + amount > _MAX_WORK):
        fail(f"ImageCollection.iterate {label} exceeds the shared 50000-step work budget")
    translator.steps += amount


def _callback(translator, value):
    if not isinstance(value, Function):
        fail("ImageCollection.iterate needs a two-argument serialized function")
    if (type(value.names) is not list or len(value.names) != 2
            or any(type(name) is not str or not name for name in value.names)
            or value.names[0] == value.names[1]):
        fail("ImageCollection.iterate needs two distinct serialized argument names")
    if type(value.env) is not dict:
        fail("ImageCollection.iterate callback environment is malformed")
    _charge(translator, len(value.names) + len(value.env), "callback environment validation")
    for name in value.names:
        _charge(translator, len(name) + 1, "callback argument validation")
    for key in value.env:
        if type(key) is not str:
            fail("ImageCollection.iterate callback environment is malformed")
        _charge(translator, len(key) + 1, "callback environment validation")
    return value


def _charge_callback_copies(translator, function, frame_count):
    per_copy = len(function.env) + 2
    for key in function.env:
        _charge(translator, len(key) + 1, "callback environment copy sizing")
        per_copy += len(key)
    for name in function.names:
        _charge(translator, len(name) + 1, "callback argument copy sizing")
        per_copy += len(name)
    _charge(
        translator, frame_count * per_copy,
        "callback environment copies",
    )


def _sequence_frames(translator, collection):
    images = collection.images
    if type(images) is not list or len(images) > _MAX_FRAMES:
        fail("ImageCollection.iterate supports at most 1000 finite Images")
    _charge(translator, len(images), "ImageSequence frame scan")
    if any(not isinstance(image, Image) for image in images):
        fail("ImageCollection.iterate requires concrete Images in an ImageSequence")
    return images


def _catalog_item_map(translator, collection):
    ids = collection.source.ids
    if type(ids) is not tuple or len(ids) > _MAX_FRAMES:
        fail("ImageCollection.iterate supports at most 1000 catalog Images")
    if not ids:
        return {}

    wanted = set()
    for item_id in ids:
        if type(item_id) is not str:
            fail("ImageCollection.iterate catalog IDs must be strings")
        _charge(translator, len(item_id) + 1, "catalog ID indexing")
        wanted.add(item_id)

    catalog_items = translator.items.get(collection.source.cid)
    if type(catalog_items) is not list:
        fail("ImageCollection.iterate catalog items are unavailable")
    # Reserve the entire one-pass scan before reading any item. A per-ID
    # member() lookup would rescan the catalogue once for every frame.
    _charge(translator, len(catalog_items), "complete catalog scan")
    by_id = {}
    for item in catalog_items:
        if type(item) is not dict:
            fail("ImageCollection.iterate catalog item is malformed")
        item_id = item.get("id")
        if type(item_id) is not str:
            fail("ImageCollection.iterate catalog item IDs must be strings")
        _charge(translator, len(item_id) + 1, "catalog item ID scan")
        if item_id in wanted and item_id not in by_id:
            by_id[item_id] = item
    _charge(translator, len(ids), "catalog ID result verification")
    if any(item_id not in by_id for item_id in ids):
        fail("ImageCollection.iterate catalog source item is unavailable")
    return by_id


def _rebind_work(translator, bands):
    """Charge rebind work and check every path through a shared Pixel DAG."""
    active = set()
    heights = {}
    work = [0]

    def reserve(amount, label):
        _charge(translator, amount, label)
        work[0] += amount

    def walk(value, depth):
        if depth > 96:
            fail("ImageCollection.iterate band expression exceeds depth 96")
        reserve(1, "band rebind preflight")
        height = 0
        if isinstance(value, Pixel):
            identity = id(value)
            if identity in active:
                fail("ImageCollection.iterate band expression contains a cycle")
            known_height = heights.get(identity)
            if known_height is not None:
                if depth + known_height > 96:
                    fail("ImageCollection.iterate band expression exceeds depth 96")
                return known_height
            if type(value.op) is not str or type(value.args) is not tuple:
                fail("ImageCollection.iterate band expression has a malformed Pixel")
            reserve(len(value.op) + len(value.args), "Pixel rebind allocation")
            active.add(identity)
            try:
                for child in value.args:
                    height = max(height, 1 + walk(child, depth + 1))
            finally:
                active.remove(identity)
            heights[identity] = height
        elif type(value) is tuple:
            identity = id(value)
            if identity in active:
                fail("ImageCollection.iterate band expression contains a cycle")
            reserve(len(value), "tuple rebind allocation")
            active.add(identity)
            try:
                for child in value:
                    height = max(height, 1 + walk(child, depth + 1))
            finally:
                active.remove(identity)
        elif isinstance(value, Source):
            if (type(value.cid) is not str or not value.cid
                    or type(value.ids) is not tuple or type(value.names) is not tuple
                    or type(value.alias) is not bool):
                fail("ImageCollection.iterate band source is malformed")
            if len(value.ids) > _MAX_FRAMES or len(value.names) > 10_000:
                fail("ImageCollection.iterate band source exceeds finite metadata limits")
            reserve(1 + len(value.cid) + len(value.ids) + len(value.names),
                    "Source rebind comparison")
            for item_id in value.ids:
                if type(item_id) is not str:
                    fail("ImageCollection.iterate band source IDs must be strings")
                reserve(len(item_id), "Source ID comparison")
            for name in value.names:
                if type(name) is not str:
                    fail("ImageCollection.iterate band source names must be strings")
                reserve(len(name), "Source band comparison")
        return height

    if type(bands) is not list or len(bands) > 10_000:
        fail("ImageCollection.iterate catalog Image bands are malformed")
    _charge(translator, len(bands), "band list preflight")
    reserve(len(bands), "band list rebind allocation")
    for band in bands:
        if (type(band) is not tuple or len(band) != 2
                or type(band[0]) is not str or not isinstance(band[1], Pixel)):
            fail("ImageCollection.iterate catalog Image has malformed bands")
        reserve(len(band[0]) + 1, "band name preflight")
        # The callback sees Collection.first(), which wraps each band in one
        # reduce_t node at depth zero. Leave that node's depth in the budget.
        walk(band[1], 1)
    return work[0]


def _charge_property_map(translator, value, label):
    if type(value) is not dict or len(value) > _MAX_WORK:
        fail(f"ImageCollection.iterate {label} is malformed")
    _charge(translator, len(value) + 1, label + " copy preflight")
    for key in value:
        if type(key) is not str:
            fail(f"ImageCollection.iterate {label} keys must be strings")
        _charge(translator, len(key) + 1, label + " key scan")


def _catalog_frame(translator, collection, item_id, item):
    source = collection.source
    selected = rebind(collection, (item_id,))
    image = selected.image

    if source.cid == DEM_COLLECTION_ID:
        original = translator._base_properties(item, source.cid)
    else:
        original = item.get("properties", {})
        _charge_property_map(translator, original, "item properties")
    if not image.inherit_props:
        copied = image.copied_props
        if type(copied) is not tuple or len(copied) > 10_000:
            fail("ImageCollection.iterate copied property list is malformed")
        _charge(translator, len(copied), "copied property list")
        for key in copied:
            if type(key) is not str:
                fail("ImageCollection.iterate copied property names must be strings")
            _charge(translator, len(key) + 1, "copied property name")
        _charge(translator, len(copied) + 1, "copied property output")
        props = {key: original[key] for key in copied if key in original}
    else:
        _charge_property_map(translator, original, "image properties")
        _charge(translator, len(original) + 1, "image property output")
        props = dict(original)

    _charge_property_map(translator, image.props, "collection metadata")
    _charge(translator, len(image.props) + 1, "collection metadata output")
    props.update(image.props)
    from .owned_metadata_values import owned_metadata_copy

    props = owned_metadata_copy(
        translator, props, "ImageCollection.iterate frame properties",
    )
    bands = [(name, Pixel("reduce_t", (pixel, "first"))) for name, pixel in image.bands]
    return replace(image, props=props, bands=bands)


def _catalog_frames(translator, collection, function):
    ids = collection.source.ids
    if type(ids) is not tuple or len(ids) > _MAX_FRAMES:
        fail("ImageCollection.iterate supports at most 1000 catalog Images")
    if not ids:
        return []
    by_id = _catalog_item_map(translator, collection)
    rebind_work = _rebind_work(translator, collection.image.bands)
    # rebind() clones the band DAG and ImageCollection.first wraps every band
    # with a first-observation node. Reserve all per-frame construction before
    # the first rebind or Image allocation.
    per_frame = rebind_work + 2 * len(collection.image.bands) + 3
    _charge(translator, len(ids) * per_frame, "catalog frame and band construction")
    _charge_callback_copies(translator, function, len(ids))
    return [
        _catalog_frame(translator, collection, item_id, by_id[item_id])
        for item_id in ids
    ]


def _empty_callback_preflight(translator, function):
    # This walker validates every serialized operator and the signatures it
    # knows without fabricating an Image for a collection with no frames.
    from .feature_map_preflight import preflight_empty_feature_map

    preflight_empty_feature_map(translator, function)


def invoke_image_collection_iterate(translator, arguments):
    """Evaluate Collection.iterate over one bounded, ordered image axis."""
    translator.allowed(arguments, {"collection", "function", "first"})
    if "collection" not in arguments or "function" not in arguments:
        fail("ImageCollection.iterate requires collection and function")
    collection = arguments["collection"]
    function = _callback(translator, arguments["function"])

    if isinstance(collection, ImageSequence):
        images = _sequence_frames(translator, collection)
        _charge_callback_copies(translator, function, len(images))
    elif isinstance(collection, Collection):
        images = _catalog_frames(translator, collection, function)
    else:
        fail("ImageCollection.iterate requires a finite local ImageCollection")

    result = arguments.get("first")
    if not images:
        _empty_callback_preflight(translator, function)
        return result

    for image in images:
        environment = {
            **function.env,
            function.names[0]: image,
            function.names[1]: result,
        }
        result = translator.evaluate(function.body, environment)
    return result
