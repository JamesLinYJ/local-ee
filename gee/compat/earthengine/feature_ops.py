"""Bounded operations on inline Earth Engine FeatureCollections."""
from __future__ import annotations

import math

from .feature_values import (
    FEATURE_VALUE_METHODS,
    charge,
    invoke_feature_value,
    is_collection,
    is_feature,
    property_name,
    validate_feature,
    validate_json_value,
    with_properties,
)
from .feature_filters import matches_feature_filter, validate_filter_structure
from .collection_metadata import copy_collection_metadata, collection_with_metadata
from .ir import Filter, Function, Image, ImageSequence, SampledFeatures, fail, integer
from .nested_collections import construct_nested_collection, is_collection_value
from .runtime_feature_ir import RFClassifiedFeatureTable


_COLLECTION_METHODS = frozenset({
    "Collection.size", "Collection.first", "Collection.toList", "Collection.map",
    "Collection.filter", "Collection.limit", "Collection.merge", "Collection.iterate",
    "Collection.randomColumn", "AggregateFeatureCollection.array",
})
_MAX_FEATURES = 1000


def handles_feature(name, arguments):
    """Claim only operations whose receiver uses the inline Feature encoding."""
    a = arguments
    if (name.startswith("Collection.")
            and any(isinstance(a.get(key), RFClassifiedFeatureTable)
                    for key in ("collection", "collection1", "collection2"))):
        return True
    if (name in _COLLECTION_METHODS | {"Collection.errorMatrix", "FeatureCollection.classify"}
            and any(isinstance(a.get(key), SampledFeatures)
                    for key in ("collection", "collection1", "collection2", "features"))):
        return True
    if name == "Feature.geometry":
        return is_feature(a.get("feature"))
    if name in _COLLECTION_METHODS:
        if name == "Collection.merge":
            return is_collection(a.get("collection1")) or is_collection(a.get("collection2"))
        return is_collection(a.get("collection"))
    if name in FEATURE_VALUE_METHODS:
        if name in {"Element.get", "Element.set", "Element.setMulti"}:
            return is_feature(a.get("object"))
        if name == "Element.propertyNames":
            return is_feature(a.get("element"))
        return is_feature(a.get("destination")) or is_feature(a.get("source"))
    return False


def _features(translator, value):
    if not is_collection(value):
        fail("Expected an inline FeatureCollection")
    features = value.get("features")
    if not isinstance(features, list):
        fail("Inline FeatureCollection requires a feature list")
    if len(features) > _MAX_FEATURES:
        fail("Inline FeatureCollection operations support at most 1000 features")
    for feature in features:
        charge(translator)
        validate_feature(translator, feature)
    return features


def _collection(features):
    return {"type": "FeatureCollection", "features": features}


def _merged_features(translator, features, prefix):
    merged = []
    for feature in features:
        charge(translator)
        properties = feature["properties"]
        property_id = properties.get("system:index")
        top_level_id = feature.get("id")
        has_property_id = "system:index" in properties
        has_top_level_id = "id" in feature
        if has_property_id and has_top_level_id:
            fail("Inline Feature cannot have both id and system:index")
        if has_property_id:
            if not isinstance(property_id, str):
                fail("FeatureCollection.merge requires string system:index values")
            charge(translator, len(prefix) + len(property_id))
            updated = dict(properties)
            updated["system:index"] = prefix + property_id
            merged.append(with_properties(feature, updated))
        elif has_top_level_id:
            if not isinstance(top_level_id, str):
                fail("FeatureCollection.merge requires string Feature ids")
            charge(translator, len(prefix) + len(top_level_id))
            merged.append({**feature, "id": prefix + top_level_id})
        else:
            fail("FeatureCollection.merge requires an explicit Feature id or system:index")
    return merged


def _sort_features(translator, features, key, ascending):
    if key is None:
        return list(features)
    key = property_name(key)
    if not key:
        fail("Collection sort key must be a nonempty property name")
    # Python's stable sort takes O(n log n) comparisons; account for that
    # upper bound in the shared budget with decoded callback and filter work.
    comparisons = max(1, math.ceil(math.log2(max(2, len(features)))))
    charge(translator, len(features) * comparisons)
    values = []
    category = None
    for feature in features:
        properties = feature["properties"]
        if key not in properties or properties[key] is None:
            fail(f"Sort property is unavailable or null: {key}")
        value = properties[key]
        if isinstance(value, bool):
            current = "boolean"
        elif type(value) in (int, float):
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                fail("Inline Feature sort properties must be finite")
            current = "number"
        elif isinstance(value, str):
            current = "string"
        else:
            fail("Inline Feature sorting requires non-null scalar properties")
        if category is not None and current != category:
            fail("Inline Feature sort properties must have one compatible scalar type")
        category = current
        values.append(value)
    if category == "string":
        # Bound repeated shared long keys before sorting. Charging each key's
        # length per comparison level conservatively covers prefix scanning.
        charge(translator, sum(map(len, values)) * comparisons)
    try:
        return [feature for _, feature in sorted(
            enumerate(features), key=lambda item: values[item[0]], reverse=not ascending
        )]
    except (TypeError, ValueError):
        fail("Inline Feature sort properties are not comparable")


def _invoke_collection(translator, name, a):
    if name == "Collection.randomColumn":
        from .random_column import apply_inline_random_column, prepare_random_column

        spec = prepare_random_column(translator, a)
        features = _features(translator, a["collection"])
        metadata = copy_collection_metadata(translator, a["collection"])
        return collection_with_metadata(
            apply_inline_random_column(translator, features, spec), metadata,
        )
    if name == "Collection.size":
        translator.allowed(a, {"collection"})
        return len(_features(translator, a["collection"]))
    if name == "Collection.first":
        translator.allowed(a, {"collection"})
        features = _features(translator, a["collection"])
        return features[0] if features else None
    if name == "Collection.toList":
        translator.allowed(a, {"collection", "count", "offset"})
        features = _features(translator, a["collection"])
        count = integer(a["count"], "Collection count", 0)
        offset = integer(a.get("offset", 0), "Collection offset", 0)
        if count > _MAX_FEATURES:
            fail("Collection.toList supports at most 1000 features")
        charge(translator, min(len(features), offset + count))
        return list(features[offset:offset + count])
    if name == "Collection.map":
        translator.allowed(a, {"collection", "baseAlgorithm", "dropNulls"})
        features = _features(translator, a["collection"])
        function = a.get("baseAlgorithm")
        if not isinstance(function, Function) or len(function.names) != 1:
            fail("FeatureCollection.map needs a one-argument serialized function")
        drop_nulls = a.get("dropNulls", False)
        if drop_nulls is not None and type(drop_nulls) is not bool:
            fail("Collection.map dropNulls must be a boolean")
        if not features:
            from .feature_map_preflight import preflight_empty_feature_map

            preflight_empty_feature_map(translator, function)
        output = []
        metadata = None
        for feature in features:
            charge(translator)
            mapped = translator.evaluate(
                function.body,
                {**function.env, function.names[0]: feature},
            )
            if mapped is None:
                if drop_nulls is True:
                    continue
                fail("FeatureCollection.map returned null; set dropNulls=true")
            if is_collection_value(mapped):
                output.append(mapped)
            if isinstance(mapped, Image):
                # A common Join.inner workflow maps matched Features back to
                # Images, then wraps the result with ee.ImageCollection. Both
                # SDKs omit that wrapper in the DAG, so retain actual Images.
                validate_json_value(translator, mapped)
                output.append(mapped)
            elif is_feature(mapped):
                if metadata is None:
                    # Pay for preserved root metadata before the first mapped
                    # Feature is appended to the result collection.
                    metadata = copy_collection_metadata(translator, a["collection"])
                output.append(validate_feature(translator, mapped))
            else:
                if not is_collection_value(mapped):
                    fail("FeatureCollection.map must return a Feature, Image, or FeatureCollection")
        if any(is_collection_value(value) for value in output):
            if not all(is_collection_value(value) for value in output):
                fail("Collection.map cannot mix FeatureCollections with Features or Images")
            metadata = copy_collection_metadata(translator, a["collection"])
            return construct_nested_collection(translator, output, metadata)
        if any(isinstance(value, Image) for value in output):
            if not all(isinstance(value, Image) for value in output):
                fail("Collection.map cannot mix Feature and Image outputs")
            return ImageSequence(output)
        if metadata is None:
            # An empty input maps to an empty FeatureCollection; retain its
            # collection metadata even though no callback result was produced.
            metadata = copy_collection_metadata(translator, a["collection"])
        return collection_with_metadata(output, metadata)
    if name == "Collection.filter":
        translator.allowed(a, {"collection", "filter"})
        features = _features(translator, a["collection"])
        metadata = copy_collection_metadata(translator, a["collection"])
        filt = a.get("filter")
        if not isinstance(filt, Filter):
            fail("Inline FeatureCollection.filter requires a serialized ee.Filter")
        validate_filter_structure(translator, filt)
        output = []
        for feature in features:
            charge(translator)
            if matches_feature_filter(translator, filt, feature) is True:
                output.append(feature)
        return collection_with_metadata(output, metadata)
    if name == "Collection.limit":
        translator.allowed(a, {"collection", "limit", "key", "ascending"})
        features = _features(translator, a["collection"])
        metadata = copy_collection_metadata(translator, a["collection"])
        ascending = a.get("ascending", True)
        if type(ascending) is not bool:
            fail("Collection ascending must be a boolean")
        output = _sort_features(translator, features, a.get("key"), ascending)
        limit = a.get("limit")
        if limit is not None:
            limit = integer(limit, "Collection limit", 0)
            if limit > _MAX_FEATURES:
                fail("Collection.limit supports at most 1000 features")
            output = output[:limit]
        return collection_with_metadata(output, metadata)
    if name == "Collection.merge":
        translator.allowed(a, {"collection1", "collection2"})
        first = _features(translator, a["collection1"])
        second = _features(translator, a["collection2"])
        if len(first) + len(second) > _MAX_FEATURES:
            fail("FeatureCollection.merge supports at most 1000 features")
        return _collection([
            *_merged_features(translator, first, "1_"),
            *_merged_features(translator, second, "2_"),
        ])
    if name == "Collection.iterate":
        translator.allowed(a, {"collection", "function", "first"})
        features = _features(translator, a["collection"])
        function = a.get("function")
        if not isinstance(function, Function) or len(function.names) != 2:
            fail("FeatureCollection.iterate needs a two-argument serialized function")
        result = a.get("first")
        for feature in features:
            charge(translator)
            result = translator.evaluate(
                function.body,
                {**function.env, function.names[0]: feature, function.names[1]: result},
            )
        return result
    if name == "AggregateFeatureCollection.array":
        translator.allowed(a, {"collection", "property"})
        features = _features(translator, a["collection"])
        key = property_name(a.get("property"))
        output = []
        for feature in features:
            charge(translator)
            # Element.get returns null for absent and explicit null properties.
            output.append(feature["properties"].get(key))
        return output
    fail(f"Unsupported Earth Engine algorithm: {name}")


def invoke_feature(translator, name, arguments):
    """Evaluate a bounded operation on inline synthetic Feature data."""
    if any(isinstance(arguments.get(key), RFClassifiedFeatureTable)
           for key in ("collection", "collection1", "collection2")):
        from .classified_feature_ops import invoke_classified_feature_operation

        return invoke_classified_feature_operation(translator, name, arguments)
    if isinstance(arguments.get("collection"), SampledFeatures):
        from .sampled_feature_ops import invoke_sampled_feature_operation

        return invoke_sampled_feature_operation(translator, name, arguments)
    if any(isinstance(arguments.get(key), SampledFeatures)
           for key in ("collection1", "collection2", "features")):
        fail("Sampled FeatureCollections support filter, limit, randomColumn, and the declared classifier consumers only")
    if name in FEATURE_VALUE_METHODS:
        return invoke_feature_value(translator, name, arguments)
    if name in _COLLECTION_METHODS:
        return _invoke_collection(translator, name, arguments)
    fail(f"Unsupported Earth Engine algorithm: {name}")
