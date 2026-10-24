"""Earth Engine collection and collection-backed image operations."""
from __future__ import annotations

import math
from dataclasses import replace

from .ir import Collection, Filter, Function, Image, Pixel, Reducer, as_image, fail, integer, rebind


COLLECTION_HANDLERS = frozenset({
    "ImageCollection.load", "Image.load", "Image.constant", "Image", "ImageCollection",
    "Collection.filter", "Collection.map", "Collection.limit", "Collection.sort",
    "Collection.size", "Collection.first", "Collection.toList",
    "AggregateFeatureCollection.array", "ImageCollection.toBands", "ImageCollection.reduce",
    "ImageCollection.mosaic",
})


def handles_collection(name):
    return name in COLLECTION_HANDLERS or name.startswith("reduce.")


def invoke_collection(translator, name, arguments):
    a = arguments
    if name == "ImageCollection.load":
        translator.allowed(a, {"id", "version"})
        if a.get("version") is not None:
            fail("Versioned collection loads are unsupported")
        return translator.load(a["id"])
    if name == "Image.load":
        translator.allowed(a, {"id", "version"})
        if a.get("version", -1) != -1:
            fail("Versioned image loads are unsupported")
        iid = a["id"]
        for cid, values in translator.items.items():
            found = [item for item in values if item["id"] == iid]
            if found:
                collection = translator.load(cid)
                collection = rebind(collection, [iid])
                return translator.first(collection)
        fail(f"Image is not locally available: {iid}")
    if name == "Image.constant":
        return as_image(a["value"])
    if name in {"Image", "ImageCollection"}:
        value = next(iter(a.values()))
        return as_image(value) if name == "Image" else value
    if name == "Collection.filter":
        translator.allowed(a, {"collection", "filter"})
        collection, filt = a["collection"], a["filter"]
        if not isinstance(collection, Collection) or not isinstance(filt, Filter):
            fail("Expected a collection and filter")
        from .filter_structure import validate_filter_structure

        validate_filter_structure(translator, filt)
        return rebind(
            collection,
            [
                item["id"]
                for item in translator.collection_items(collection)
                if translator.matches(filt, item)
            ],
        )
    if name == "Collection.map":
        translator.allowed(a, {"collection", "baseAlgorithm", "dropNulls"})
        collection, function = a["collection"], a["baseAlgorithm"]
        if not isinstance(collection, Collection) or not isinstance(function, Function) or len(function.names) != 1:
            fail("Collection.map needs a one-argument serialized function")
        from ...ee_metadata import evaluate_per_image_map, requires_item_metadata

        if requires_item_metadata(function, translator.scope) or a.get("dropNulls"):
            return evaluate_per_image_map(translator, collection, function, a.get("dropNulls", False))
        image = translator.evaluate(
            function.body,
            {**function.env, function.names[0]: replace(collection.image, mapped=True)},
        )
        if not isinstance(image, Image):
            fail("Collection.map must return an Image")
        from .pixel_math_graph import requires_per_item_pixel_math

        if (getattr(translator, "_pixel_math_seen", False)
                and requires_per_item_pixel_math(image, translator)):
            return evaluate_per_image_map(translator, collection, function)
        return replace(collection, image=replace(image, mapped=False, source=collection.source))
    if name in {"Collection.limit", "Collection.sort"}:
        translator.allowed(a, {"collection", "limit", "key", "ascending"})
        collection = a["collection"]
        ids = list(collection.source.ids)
        key = a.get("key")
        if key is not None:
            def sortkey(iid):
                props = translator.properties(collection, iid)
                if key not in props:
                    fail(f"Sort property is unavailable: {key}")
                return props[key]

            ids.sort(key=sortkey, reverse=not a.get("ascending", True))
        if a.get("limit") is not None:
            limit = a["limit"]
            if isinstance(limit, bool) or not isinstance(limit, (int, float)) or limit < 0 or int(limit) != limit:
                fail("Collection limit must be a nonnegative integer")
            ids = ids[:int(limit)]
        return rebind(collection, ids)
    if name == "Collection.size":
        return len(a["collection"].source.ids)
    if name == "Collection.first":
        return translator.first(a["collection"])
    if name == "Collection.toList":
        translator.allowed(a, {"collection", "count", "offset"})
        collection = a["collection"]
        count = integer(a["count"], "Collection count", 0)
        offset = integer(a.get("offset", 0), "Collection offset", 0)
        if count > 1000:
            fail("Collection.toList supports at most 1000 images")
        return [
            translator.first(rebind(collection, [iid]))
            for iid in collection.source.ids[offset:offset + count]
        ]
    if name == "AggregateFeatureCollection.array":
        translator.allowed(a, {"collection", "property"})
        collection, key = a["collection"], a["property"]
        if not isinstance(collection, Collection):
            fail("aggregate_array currently requires an ImageCollection")
        result = []
        for iid in collection.source.ids:
            props = translator.properties(collection, iid)
            if key not in props:
                fail(f"Item metadata property is unavailable: {key}")
            result.append(props[key])
        return result
    if name == "ImageCollection.toBands":
        translator.allowed(a, {"collection"})
        collection = a["collection"]
        bands = []
        if len(collection.source.ids) * len(collection.image.bands) > 100:
            fail("Local toBands is limited to 100 output bands")
        for iid in collection.source.ids:
            image = translator.first(rebind(collection, [iid]))
            prefix = image.props.get("system:index")
            if not isinstance(prefix, str):
                fail("toBands requires system:index on each image")
            bands.extend((prefix + "_" + name, pixel) for name, pixel in image.bands)
        if len({name for name, _ in bands}) != len(bands):
            fail("toBands produced duplicate band names")
        return Image(bands, {}, collection.source, inherit_props=False, footprint=collection.image.footprint)
    if name == "ImageCollection.reduce":
        translator.allowed(a, {"collection", "reducer", "parallelScale"})
        parallel = a.get("parallelScale", 1)
        if isinstance(parallel, bool) or not isinstance(parallel, (int, float)) or not math.isfinite(parallel) or parallel < 1:
            fail("parallelScale must be finite and >= 1")
        collection, reducer = a["collection"], a["reducer"]
        if not isinstance(reducer, Reducer):
            fail("Collection.reduce requires a supported single-output reducer")
        suffix = "stdDev" if reducer.name == "sd" else reducer.name
        return Image(
            [(name + "_" + suffix, Pixel("reduce_t", (pixel, reducer.name))) for name, pixel in collection.image.bands],
            {}, collection.source, inherit_props=False, footprint=collection.image.footprint,
        )
    if name.startswith("reduce."):
        translator.allowed(a, {"collection"})
        reducer = name.split(".", 1)[1]
        if reducer not in {"median", "mean", "min", "max", "sum", "count"}:
            fail(f"Unsupported collection reducer: {reducer}")
        collection = a["collection"]
        return Image(
            [(band, Pixel("reduce_t", (pixel, reducer))) for band, pixel in collection.image.bands],
            {}, collection.source, inherit_props=False, footprint=collection.image.footprint,
        )
    if name == "ImageCollection.mosaic":
        translator.allowed(a, {"collection"})
        collection = a["collection"]
        return Image(
            [(band, Pixel("reduce_t", (pixel, "last", "collection_order"))) for band, pixel in collection.image.bands],
            {}, collection.source, inherit_props=False, footprint=collection.image.footprint,
        )
    fail(f"Unsupported Earth Engine algorithm: {name}")
