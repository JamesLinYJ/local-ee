"""Finite FeatureCollection selection and column construction operations."""
from __future__ import annotations

import hashlib
import json
import math

from .collection_metadata import copy_collection_metadata, collection_with_metadata
from .feature_values import (
    charge,
    is_collection,
    validate_feature,
)
from .feature_table_construction import (
    _copy_features,
    invoke_feature_table_construction,
    preflight_feature_collection_output,
)
from .ir import Collection, ImageSequence, SampledFeatures, fail
from .runtime_feature_ir import RFClassifiedFeatureTable


FEATURE_TABLE_SELECTION_METHODS = frozenset({
    "Collection.distinct", "Collection.remap", "Collection.fromColumns",
})
_MAX_FEATURES = 1000
_MAX_PROPERTIES = 10000
_MAX_JSON_BYTES = 1_000_000
_MAX_EXACT_INTEGER = 2**53


def handles_feature_table_selection(name, arguments):
    """Claim these names so dynamic receivers fail with a scoped error."""
    return name in FEATURE_TABLE_SELECTION_METHODS


def _inline_features(translator, value):
    if not is_collection(value):
        if isinstance(value, (SampledFeatures, RFClassifiedFeatureTable)):
            fail("FeatureCollection selection does not support dynamic sample or classified tables")
        if isinstance(value, (Collection, ImageSequence)):
            fail("FeatureCollection selection does not support ImageCollections")
        fail("FeatureCollection selection requires a finite inline FeatureCollection")
    features = value.get("features")
    if type(features) is not list:
        fail("Inline FeatureCollection requires a feature list")
    if len(features) > _MAX_FEATURES:
        fail("FeatureCollection selection supports at most 1000 features")
    for feature in features:
        charge(translator)
        validate_feature(translator, feature)
    return features


def _selection_names(translator, value):
    if type(value) is str:
        names = [value]
    elif type(value) is list and len(value) <= _MAX_PROPERTIES:
        names = value
    else:
        fail("FeatureCollection.distinct properties must be a string or a list of at most 10000 names")
    if any(type(name) is not str for name in names):
        fail("FeatureCollection.distinct properties must contain only strings")
    # Reserve the string scan and set-build pass before allocating it.
    charge(translator, 1 + len(names) + sum(map(len, names)))
    if len(set(names)) != len(names):
        fail("FeatureCollection.distinct properties cannot contain duplicates")
    return names


def _distinct_text_bytes(translator, value):
    """Measure canonical ensure_ascii=False text without making an encoded copy."""
    charge(translator, 1 + len(value))
    size = 2
    for character in value:
        code = ord(character)
        if character in {'"', "\\"}:
            size += 2
        elif code < 0x20:
            size += 2 if character in {"\b", "\f", "\n", "\r", "\t"} else 6
        elif 0xD800 <= code <= 0xDFFF:
            fail("FeatureCollection.distinct cannot encode an isolated Unicode surrogate")
        elif code <= 0x7F:
            size += 1
        elif code <= 0x7FF:
            size += 2
        elif code <= 0xFFFF:
            size += 3
        else:
            size += 4
    return size


def _scan_distinct_value(translator, value, active, depth=0):
    """Reserve canonical JSON scan and byte work before serialization."""
    if depth > 96:
        fail("FeatureCollection.distinct exceeds the metadata depth limit")
    kind = type(value)
    charge(translator)
    if value is None:
        fail("FeatureCollection.distinct does not define null or missing property equality")
    if kind is bool:
        return 4 if value else 5
    if kind is int:
        if abs(value) > _MAX_EXACT_INTEGER:
            fail("FeatureCollection.distinct requires integers in the exact Float64 domain")
        return len(str(value))
    if kind is float:
        if not math.isfinite(value):
            fail("FeatureCollection.distinct requires finite numbers")
        return len(json.dumps(value, allow_nan=False))
    if kind is str:
        return _distinct_text_bytes(translator, value)
    if kind not in (list, dict):
        fail("FeatureCollection.distinct supports finite JSON values only")
    identity = id(value)
    if identity in active:
        fail("FeatureCollection.distinct properties cannot contain cyclic JSON")
    if len(value) > _MAX_PROPERTIES:
        fail("FeatureCollection.distinct supports at most 10000 container entries")
    charge(translator, 1 + len(value))
    if kind is dict:
        # Sorting defines the local canonical object form.
        charge(translator, len(value) * max(1, math.ceil(math.log2(max(2, len(value))))))
    active.add(identity)
    try:
        children = value.items() if kind is dict else enumerate(value)
        size = 2 + max(0, len(value) - 1)
        for key, child in children:
            if kind is dict:
                if type(key) is not str:
                    fail("FeatureCollection.distinct dictionaries require string keys")
                key_size = _distinct_text_bytes(translator, key)
                child_size = _scan_distinct_value(translator, child, active, depth + 1)
                size += key_size + 1 + child_size
            else:
                size += _scan_distinct_value(translator, child, active, depth + 1)
        return size
    finally:
        active.remove(identity)


def _distinct_bytes(translator, selected, wire):
    estimated = _scan_distinct_value(translator, selected, set())
    if estimated > _MAX_JSON_BYTES - wire[0]:
        fail("FeatureCollection.distinct exceeds the 1 MB serialized comparison limit")
    wire[0] += estimated
    charge(translator, 2 * estimated)  # serialization/hash and collision-safe membership
    try:
        payload = json.dumps(
            selected, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError, OverflowError):
        fail("FeatureCollection.distinct could not serialize selected properties")
    if len(payload) != estimated:
        fail("FeatureCollection.distinct canonical byte preflight did not match serialization")
    return payload


def _distinct(translator, arguments):
    translator.allowed(arguments, {"collection", "properties"})
    source = arguments.get("collection")
    features = _inline_features(translator, source)
    names = _selection_names(translator, arguments.get("properties"))
    seen = {}
    kept = []
    wire = [0]
    for feature in features:
        properties = feature["properties"]
        charge(translator, 1 + len(names) + sum(map(len, names)))
        selected = {}
        for name in names:
            if name == ".geo":
                value = feature.get("geometry")
            else:
                if name not in properties:
                    fail(f"FeatureCollection.distinct selected property is missing: {name}")
                value = properties[name]
            selected[name] = value
        payload = _distinct_bytes(translator, selected, wire)
        digest = hashlib.sha256(payload).digest()
        bucket = seen.setdefault(digest, set())
        if payload in bucket:
            continue
        bucket.add(payload)
        kept.append(feature)
    preflight_feature_collection_output(translator, source, kept)
    metadata = copy_collection_metadata(translator, source)
    return collection_with_metadata(_copy_features(translator, kept), metadata)


def _mapping_values(translator, value, label, *, output=False):
    if type(value) is not list or len(value) > _MAX_FEATURES:
        fail(f"FeatureCollection.remap {label} must be a list of at most 1000 values")
    charge(translator, 1 + len(value))
    normalized = []
    for item in value:
        if output:
            if type(item) is not int:
                fail("FeatureCollection.remap lookupOut values must be integers")
            if abs(item) > _MAX_EXACT_INTEGER:
                fail("FeatureCollection.remap integers must be in the exact Float64 domain")
            normalized.append(item)
        elif type(item) is str:
            charge(translator, len(item))
            normalized.append(item)
        elif type(item) is int and abs(item) <= _MAX_EXACT_INTEGER:
            normalized.append(item)
        else:
            fail("FeatureCollection.remap lookupIn values must be strings or exact integers")
    return normalized


def _remap_key(value):
    if type(value) is str:
        return ("string", value)
    if type(value) is int:
        return ("integer", value)
    return None


def _remap(translator, arguments):
    translator.allowed(arguments, {"collection", "lookupIn", "lookupOut", "columnName"})
    source_collection = arguments.get("collection")
    features = _inline_features(translator, source_collection)
    lookup_in = _mapping_values(translator, arguments.get("lookupIn"), "lookupIn")
    lookup_out = _mapping_values(
        translator, arguments.get("lookupOut"), "lookupOut", output=True,
    )
    if len(lookup_in) != len(lookup_out):
        fail("FeatureCollection.remap lookupIn and lookupOut must have equal lengths")
    mapping = {}
    for source, target in zip(lookup_in, lookup_out):
        key = _remap_key(source)
        if key in mapping:
            fail("FeatureCollection.remap lookupIn values must be unique")
        mapping[key] = target
    column = arguments.get("columnName")
    if type(column) is not str:
        fail("FeatureCollection.remap columnName must be a string")
    charge(translator, len(column))
    selected = []
    for feature in features:
        properties = feature["properties"]
        if column not in properties or properties[column] is None:
            # The public algorithm drops values absent from lookupIn. Missing
            # and null values have no legal lookupIn representation.
            continue
        value = properties[column]
        if type(value) is str:
            charge(translator, len(value))
        key = _remap_key(value)
        if key is None:
            fail("FeatureCollection.remap column values must be strings or integers")
        if key not in mapping:
            continue
        selected.append((feature, mapping[key]))
    charge(translator, len(selected) * (2 + len(column)))
    selected_features = []
    overrides = {}
    for feature, replacement in selected:
        selected_features.append(feature)
        overrides[id(feature["properties"])] = {column: replacement}
    preflight_feature_collection_output(
        translator, source_collection, selected_features, overrides=overrides,
    )
    metadata = copy_collection_metadata(translator, source_collection)
    kept = _copy_features(translator, selected_features)
    charge(translator, len(kept))
    for feature, (_, replacement) in zip(kept, selected):
        feature["properties"][column] = replacement
    return collection_with_metadata(kept, metadata)


def invoke_feature_table_selection(translator, name, arguments):
    """Compute one finite inline FeatureCollection selection operation."""
    if name == "Collection.distinct":
        return _distinct(translator, arguments)
    if name == "Collection.remap":
        return _remap(translator, arguments)
    if name == "Collection.fromColumns":
        return invoke_feature_table_construction(translator, name, arguments)
    fail(f"Unsupported Earth Engine algorithm: {name}")
