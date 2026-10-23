"""Finite data-source adapter for scalar FeatureCollection aggregates."""
from __future__ import annotations

import math

from .aggregate_statistics_values import aggregate_statistics_value, charge
from .geometry_values import GEOMETRY_TYPES
from .ir import Collection, Image, ImageSequence, Source, fail


AGGREGATE_STATISTICS_NAMES = frozenset({
    "AggregateFeatureCollection.first",
    "AggregateFeatureCollection.count",
    "AggregateFeatureCollection.count_distinct",
    "AggregateFeatureCollection.min",
    "AggregateFeatureCollection.max",
    "AggregateFeatureCollection.mean",
    "AggregateFeatureCollection.product",
    "AggregateFeatureCollection.sum",
    "AggregateFeatureCollection.sample_sd",
    "AggregateFeatureCollection.sample_var",
    "AggregateFeatureCollection.total_sd",
    "AggregateFeatureCollection.total_var",
    "AggregateFeatureCollection.stats",
    "AggregateFeatureCollection.histogram",
})

_MAX_ROWS = 1_000
_MAX_CONTAINER_ITEMS = 10_000
_MAX_JSON_DEPTH = 96


def _strict_json_value(translator, value, active=None, depth=0):
    """Validate only consumed property data, excluding non-JSON compiler IR."""
    if depth > _MAX_JSON_DEPTH:
        fail("Aggregate property metadata exceeds the depth limit")
    if value is None or type(value) is bool:
        charge(translator, 1, "Aggregate property validation")
        return
    if type(value) is int:
        charge(translator, max(1, value.bit_length()), "Aggregate integer validation")
        if abs(value) > 2**53:
            fail("Aggregate integer properties must be within the exact ±2^53 range")
        return
    if type(value) is float:
        charge(translator, 1, "Aggregate property validation")
        if not math.isfinite(value):
            fail("Aggregate properties must contain finite JSON numbers")
        return
    if type(value) is str:
        charge(translator, len(value) + 1, "Aggregate property string scan")
        return
    if type(value) not in (dict, list):
        fail("Aggregate properties must contain bounded JSON values")

    if len(value) > _MAX_CONTAINER_ITEMS:
        fail("Aggregate property containers support at most 10000 entries")
    charge(translator, 1 + len(value), "Aggregate property container scan")
    active = set() if active is None else active
    identity = id(value)
    if identity in active:
        fail("Aggregate property metadata contains a cycle")
    active.add(identity)
    try:
        if type(value) is dict:
            for key, child in value.items():
                if type(key) is not str:
                    fail("Aggregate property object keys must be strings")
                charge(translator, len(key) + 1, "Aggregate property key scan")
                _strict_json_value(translator, child, active, depth + 1)
        else:
            for child in value:
                _strict_json_value(translator, child, active, depth + 1)
    finally:
        active.remove(identity)


def _string_keys(translator, value, label):
    """Precharge a bounded mapping and its keys before any keyed lookup."""
    if type(value) is not dict or len(value) > _MAX_CONTAINER_ITEMS:
        fail(f"{label} must be an object with at most 10000 entries")
    charge(translator, 1 + len(value), f"{label} scan")
    for key in value:
        if type(key) is not str:
            fail(f"{label} keys must be strings")
        charge(translator, len(key) + 1, f"{label} key scan")


def _feature_row_value(translator, feature, property_name):
    if type(feature) is not dict or len(feature) > _MAX_CONTAINER_ITEMS:
        fail("AggregateFeatureCollection rows must be bounded Feature objects")
    # These canonical fields have fixed, short names. Charge each lookup once;
    # scanning every row/property key spelling would exhaust the shared budget
    # on ordinary 1000-feature collections without adding validation value.
    charge(translator, 4, "Aggregate Feature shape lookup")
    if feature.get("type") != "Feature":
        fail("AggregateFeatureCollection rows must have type Feature")
    geometry = feature.get("geometry")
    if geometry is not None:
        if type(geometry) is not dict or len(geometry) > _MAX_CONTAINER_ITEMS:
            fail("Aggregate Feature geometry must be decoded GeoJSON or null")
        charge(translator, 1, "Aggregate Feature geometry type lookup")
        geometry_type = geometry.get("type")
        if type(geometry_type) is not str:
            fail("Aggregate Feature geometry must be decoded GeoJSON or null")
        charge(translator, len(geometry_type) + 1, "Aggregate geometry type scan")
        if geometry_type not in GEOMETRY_TYPES:
            fail("Aggregate Feature geometry must be decoded GeoJSON or null")
    if "id" in feature:
        charge(translator, 1, "Aggregate Feature ID lookup")
        identifier = feature["id"]
        if type(identifier) is not str:
            fail("Aggregate Feature ids must be strings")
    properties = feature.get("properties")
    if type(properties) is not dict or len(properties) > _MAX_CONTAINER_ITEMS:
        fail("Aggregate Feature properties must be a bounded object")
    charge(translator, len(property_name) + 1, "Aggregate selected property lookup")
    value = properties.get(property_name)
    if value is not None:
        _strict_json_value(translator, value, {id(properties)})
    return value


def _feature_values(translator, collection, property_name):
    if type(collection) is not dict:
        fail("AggregateFeatureCollection requires an inline feature list")
    charge(translator, len("type"))
    if collection.get("type") != "FeatureCollection":
        fail("AggregateFeatureCollection requires an inline feature list")
    charge(translator, len("features"))
    features = collection.get("features")
    if type(features) is not list:
        fail("AggregateFeatureCollection requires an inline feature list")
    if len(features) > _MAX_ROWS:
        fail("AggregateFeatureCollection supports at most 1000 inline features")
    charge(translator, 1 + len(features))
    values = []
    for feature in features:
        charge(translator, 1)
        values.append(_feature_row_value(translator, feature, property_name))
    return values, len(features)


def _image_collection_values(translator, collection, property_name):
    source = collection.source
    if not isinstance(source, Source):
        fail("ImageCollection aggregate requires a finite declared source")
    ids = source.ids
    if type(ids) is not tuple or len(ids) > _MAX_ROWS:
        fail("ImageCollection metadata aggregation supports at most 1000 selected images")
    charge(translator, len(ids) + 1, "ImageCollection ID preflight")
    for iid in ids:
        if type(iid) is not str:
            fail("ImageCollection metadata IDs must be strings")
        charge(translator, len(iid) + 1, "ImageCollection requested ID hash")
    if type(source.cid) is not str:
        fail("ImageCollection metadata requires a string collection ID")
    charge(translator, len(source.cid) + 1, "ImageCollection source lookup")
    items = translator.items.get(source.cid)
    if type(items) is not list:
        fail("ImageCollection aggregate property metadata is unavailable")
    # Charge the index scan and ordered output slots before allocating either.
    # Keep the first item for repeated IDs, matching the catalogue lookup.
    charge(translator, len(items) + len(ids) + 1, "ImageCollection metadata index")
    requested = set(ids)
    by_id = {}
    for item in items:
        if type(item) is not dict:
            fail("ImageCollection metadata entries must be objects")
        charge(translator, len("id"), "ImageCollection metadata field lookup")
        item_id = item.get("id")
        if type(item_id) is not str:
            fail("ImageCollection metadata entries require string IDs")
        charge(translator, 3 * (len(item_id) + 1), "ImageCollection metadata ID lookup")
        if item_id in requested and item_id not in by_id:
            by_id[item_id] = item

    image = collection.image
    if not isinstance(image, Image) or type(image.props) is not dict:
        fail("ImageCollection aggregate metadata requires a concrete Image")
    if type(image.copied_props) is not tuple or len(image.copied_props) > _MAX_CONTAINER_ITEMS:
        fail("ImageCollection copied-property metadata is malformed")
    _string_keys(translator, image.props, "ImageCollection image properties")
    charge(translator, len(image.copied_props) + 1, "ImageCollection copied-property scan")
    for name in image.copied_props:
        if type(name) is not str:
            fail("ImageCollection copied property names must be strings")
        charge(translator, len(name) + 1, "ImageCollection copied-property name")
    values = []
    for iid in ids:
        charge(translator, len(iid) + 1, "ImageCollection selected ID lookup")
        item = by_id.get(iid)
        if item is None:
            fail("ImageCollection aggregate references unavailable local metadata")
        charge(translator, len("properties"), "ImageCollection metadata field lookup")
        properties = item.get("properties", {})
        _string_keys(translator, properties, "ImageCollection metadata properties")
        charge(translator, len(property_name) + 1, "ImageCollection property lookup")
        if property_name in image.props:
            value = image.props[property_name]
        elif image.inherit_props:
            charge(translator, len(property_name) + 1, "ImageCollection inherited property lookup")
            value = properties.get(property_name)
        else:
            copied_lookup_work = sum(
                len(property_name) + len(name) + 1 for name in image.copied_props
            )
            charge(translator, copied_lookup_work, "ImageCollection copied-property lookup")
            if property_name in image.copied_props:
                charge(translator, len(property_name) + 1, "ImageCollection copied value lookup")
                value = properties.get(property_name)
            else:
                value = None
        if value is not None:
            _strict_json_value(translator, value)
        values.append(value)
    return values, len(ids)


def _image_sequence_values(translator, collection, property_name):
    images = collection.images
    if type(images) is not list or len(images) > _MAX_ROWS:
        fail("Finite ImageSequence metadata aggregation supports at most 1000 images")
    charge(translator, 1 + len(images))
    values = []
    for image in images:
        if not isinstance(image, Image) or image.mapped or type(image.props) is not dict:
            fail("ImageSequence aggregation requires concrete Image metadata")
        _string_keys(translator, image.props, "ImageSequence image properties")
        charge(translator, len(property_name) + 1, "ImageSequence property lookup")
        value = image.props.get(property_name)
        if value is not None:
            _strict_json_value(translator, value)
        values.append(value)
    return values, len(images)


def _property_values(translator, collection, property_name):
    """Read selected values in declared order without returning source IR."""
    if type(collection) is dict:
        return _feature_values(translator, collection, property_name)
    if isinstance(collection, Collection):
        return _image_collection_values(translator, collection, property_name)
    if isinstance(collection, ImageSequence):
        return _image_sequence_values(translator, collection, property_name)
    fail("AggregateFeatureCollection supports inline FeatureCollections and finite declared image metadata only")


def invoke_aggregate_statistics(translator, name, arguments):
    """Evaluate a signed aggregate on bounded actual metadata values."""
    if name not in AGGREGATE_STATISTICS_NAMES:
        fail(f"Unsupported aggregate statistic: {name}")
    translator.allowed(arguments, {"collection", "property"})
    property_name = arguments.get("property")
    if type(property_name) is not str:
        fail("AggregateFeatureCollection property must be a string")
    charge(translator, len(property_name), "AggregateFeatureCollection property name")
    values, row_count = _property_values(
        translator, arguments.get("collection"), property_name,
    )
    return aggregate_statistics_value(translator, name, values, row_count)
