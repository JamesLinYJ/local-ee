"""Bounded collection-level metadata for literal inline FeatureCollections."""
from __future__ import annotations

import copy
import math

from .feature_values import property_name
from .ir import SampledFeatures, fail


_METADATA_METHODS = frozenset({
    "Element.get", "Element.set", "Element.setMulti", "Element.propertyNames",
    "Element.copyProperties",
})
_MAX_FEATURES = 1000
_MAX_PROPERTIES = 10000
_MAX_DEPTH = 96
_MAX_WORK = 50000
_MAX_JSON_BYTES = 1_000_000


def _looks_like_collection(value):
    return isinstance(value, dict) and dict.get(value, "type") == "FeatureCollection"


def handles_collection_metadata(name, arguments):
    """Claim collection-level Element calls, including explicit rejects."""
    if name not in _METADATA_METHODS:
        return False
    if name == "Element.copyProperties":
        values = (arguments.get("destination"), arguments.get("source"))
        return any(_looks_like_collection(value) or isinstance(value, SampledFeatures)
                   for value in values)
    receiver_key = "element" if name == "Element.propertyNames" else "object"
    receiver = arguments.get(receiver_key)
    if _looks_like_collection(receiver):
        return True
    # Sampled table metadata remains read-only through metadata_ops. Route only
    # mutations here so they fail with a capability error, never AttributeError.
    return (isinstance(receiver, SampledFeatures)
            and name in {"Element.set", "Element.setMulti"})


def _inline_collection(value):
    if type(value) is not dict or dict.get(value, "type") != "FeatureCollection":
        fail("Collection metadata requires an inline FeatureCollection")
    features = value.get("features")
    if type(features) is not list:
        fail("Inline FeatureCollection requires a feature list")
    if len(features) > _MAX_FEATURES:
        fail("Inline FeatureCollection metadata supports at most 1000 features")
    return features


def _charge(translator, work):
    if work > _MAX_WORK or translator.steps + work > _MAX_WORK:
        fail("FeatureCollection metadata exceeds the 50000-step compilation work budget")
    translator.steps += work


def _wire_add(wire, amount):
    if amount > _MAX_JSON_BYTES - wire[0]:
        fail("FeatureCollection metadata exceeds the 1 MB JSON size limit")
    wire[0] += amount


def _integer_size(value):
    bits = value.bit_length()
    if bits > 160000:
        fail("FeatureCollection metadata exceeds the JSON size limit")
    return max(1, math.ceil(bits * math.log10(2)) + (1 if value < 0 else 0))


def _string_characters(value):
    """Iteration seam used to prove work is reserved before scanning text."""
    return iter(value)


def _iter_json_container(value):
    """Return a container iterator only after its scan cost was reserved."""
    return value.items() if type(value) is dict else enumerate(value)


def _scan_string(translator, value, wire):
    """Reserve a string's length and bytes before inspecting any character."""
    if type(value) is not str:
        fail("FeatureCollection metadata property names must be strings")
    base_size = len(value) + 2
    _charge(translator, base_size)
    _wire_add(wire, base_size)
    work = base_size
    size = base_size
    for character in _string_characters(value):
        code = ord(character)
        if character in {'"', "\\"} or code < 32:
            extra = 1 if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"} else 5
        elif code >= 127:
            extra = 5 if code <= 0xffff else 11
        else:
            extra = 0
        if extra:
            _charge(translator, extra)
            _wire_add(wire, extra)
            work += extra
            size += extra
    return work, size


def _scan_json(translator, value, depth, active, wire, collect_items=False):
    """Validate JSON while reserving each scan before iteration or recursion."""
    if depth > _MAX_DEPTH:
        fail("FeatureCollection metadata exceeds the depth limit")
    kind = type(value)
    if kind is str:
        return _scan_string(translator, value, wire)[0], None
    if value is None:
        _charge(translator, 1)
        _wire_add(wire, 4)
        return 1, None
    if kind is bool:
        _charge(translator, 1)
        _wire_add(wire, 4 if value else 5)
        return 1, None
    if kind is int:
        size = _integer_size(value)
        _charge(translator, 1 + size)
        _wire_add(wire, size)
        return 1 + size, None
    if kind is float:
        if not math.isfinite(value):
            fail("FeatureCollection metadata numbers must be finite")
        size = len(repr(value))
        _charge(translator, 1 + size)
        _wire_add(wire, size)
        return 1 + size, None
    if kind not in (dict, list):
        fail("FeatureCollection metadata accepts finite JSON values only")

    identity = id(value)
    if identity in active:
        fail("FeatureCollection metadata cannot contain cyclic JSON")
    if kind is dict and len(value) > _MAX_PROPERTIES:
        fail("FeatureCollection metadata supports at most 10000 properties")

    count = len(value)
    # Reserve the whole imminent iterator pass and punctuation before asking
    # for an iterator. Nested scans reserve their own work before recursing.
    container_work = 1 + count
    punctuation = 2 + max(0, count - 1) + (count if kind is dict else 0)
    _charge(translator, container_work)
    _wire_add(wire, punctuation)
    work = container_work
    item_work = {} if collect_items and kind is dict else None
    active.add(identity)
    try:
        for key, child in _iter_json_container(value):
            if kind is dict:
                if type(key) is not str:
                    fail("FeatureCollection metadata property names must be strings")
                key_work, _ = _scan_string(translator, key, wire)
                child_work, _ = _scan_json(
                    translator, child, depth + 1, active, wire,
                )
                work += key_work + child_work
                if item_work is not None:
                    item_work[key] = key_work + child_work
            else:
                child_work, _ = _scan_json(
                    translator, child, depth + 1, active, wire,
                )
                work += child_work
        return work, item_work
    finally:
        active.remove(identity)


def _validated_property_map(translator, properties):
    if type(properties) is not dict:
        fail("FeatureCollection collection-level properties must be a dictionary")
    start = translator.steps
    wire = [0]
    _, item_work = _scan_json(translator, properties, 0, set(), wire, True)
    return translator.steps - start, wire[0], item_work


def _properties(collection):
    properties = collection.get("properties", {})
    if type(properties) is not dict:
        fail("FeatureCollection collection-level properties must be a dictionary")
    return properties


def _new_collection(features, properties, include_properties):
    result = {"type": "FeatureCollection", "features": features}
    if include_properties:
        result["properties"] = properties
    return result


def copy_collection_metadata(translator, collection):
    """Copy actual collection properties before a row-preserving result is built."""
    features = _inline_collection(collection)
    properties = _properties(collection)
    work, _, _ = _validated_property_map(translator, properties)
    # Copying the nested metadata and row list is separately charged before
    # deepcopy or list allocation starts.
    _charge(translator, work + len(features) + 4)
    return copy.deepcopy(properties), "properties" in collection


def collection_with_metadata(features, metadata):
    properties, include_properties = metadata
    return _new_collection(features, properties, include_properties)


def _updated_collection(translator, collection, additions):
    features = _inline_collection(collection)
    old = _properties(collection)
    old_work, _, _ = _validated_property_map(translator, old)
    added_work, _, _ = _validated_property_map(translator, additions)
    # Both independent copies and the copied row list are reserved before
    # allocating the updated map.
    _charge(translator, old_work + added_work + len(additions) + len(features) + 8)
    properties = copy.deepcopy(old)
    properties.update(copy.deepcopy(additions))
    return _new_collection(features.copy(), properties, True)


def _property_list(translator, value, label):
    if type(value) is not list or len(value) > _MAX_PROPERTIES:
        fail(f"{label} must be a list of at most 10000 property names")
    # Reserve this pass before type checks and name scans.
    _charge(translator, 1 + len(value))
    wire = [0]
    for name in value:
        _scan_string(translator, name, wire)
    return value


def _copy_properties(translator, destination, source, names, excluded):
    if names is not None and excluded is not None:
        fail("copyProperties cannot use properties and exclude together")
    destination_features = _inline_collection(destination)
    _inline_collection(source)
    destination_properties = _properties(destination)
    source_properties = _properties(source)
    destination_work, _, _ = _validated_property_map(translator, destination_properties)
    source_work, _, source_item_work = _validated_property_map(translator, source_properties)
    if names is not None:
        names = _property_list(translator, names, "copyProperties properties")
        _charge(translator, len(names))
    if excluded is not None:
        excluded = _property_list(translator, excluded, "copyProperties exclude")
        _charge(translator, len(excluded))

    # Reserve source selection passes before allocating sets or traversing the
    # source dictionary. The source root was already validated and item costs
    # are available without another recursive scan.
    _charge(translator, len(source_properties) + 2)
    selected_names = set(names) if names is not None else None
    excluded_names = set(excluded or ())

    def selected(key):
        if selected_names is None:
            return not key.startswith("system:") and key not in excluded_names
        return key in selected_names and key not in excluded_names

    selected_cost = 0
    selected_count = 0
    for key, _ in _iter_json_container(source_properties):
        if selected(key):
            selected_cost += source_item_work[key]
            selected_count += 1

    # Deep-copying destination metadata and each selected item, and copying
    # the destination row list, each have an explicit precharge.
    _charge(translator, destination_work + selected_cost + selected_count + len(source_properties)
            + len(destination_features) + 8)
    copied = copy.deepcopy(destination_properties)
    for key, value in _iter_json_container(source_properties):
        if selected(key):
            copied[key] = copy.deepcopy(value)
    include_properties = "properties" in destination or selected_count > 0
    return _new_collection(destination_features.copy(), copied, include_properties)


def invoke_collection_metadata(translator, name, arguments):
    """Evaluate Element metadata calls against collection-level properties."""
    a = arguments
    if name in {"Element.get", "Element.set", "Element.setMulti", "Element.propertyNames"}:
        allowed = {
            "Element.get": {"object", "property"},
            "Element.set": {"object", "key", "value"},
            "Element.setMulti": {"object", "properties"},
            "Element.propertyNames": {"element"},
        }[name]
        translator.allowed(a, allowed)
        receiver_key = "element" if name == "Element.propertyNames" else "object"
        receiver = a.get(receiver_key)
        if isinstance(receiver, SampledFeatures):
            fail("Sampled FeatureCollection metadata is read-only")
        _inline_collection(receiver)
        if name == "Element.get":
            properties = _properties(receiver)
            _, _, item_work = _validated_property_map(translator, properties)
            key = property_name(a.get("property"))
            _scan_string(translator, key, [0])
            result = properties.get(key)
            if type(result) in (dict, list):
                _charge(translator, item_work.get(key, 0))
                return copy.deepcopy(result)
            return result
        if name == "Element.propertyNames":
            properties = _properties(receiver)
            _validated_property_map(translator, properties)
            _charge(translator, len(properties) + 2)
            # Reserve the result list before asking for an iterator or allocating it.
            return list(properties)
        if name == "Element.set":
            key = property_name(a.get("key"))
            _scan_string(translator, key, [0])
            additions = {key: a.get("value")}
        else:
            additions = a.get("properties")
            if type(additions) is not dict:
                fail("Element.setMulti properties must be a dictionary with string keys")
        return _updated_collection(translator, receiver, additions)

    if name == "Element.copyProperties":
        translator.allowed(a, {"destination", "source", "properties", "exclude"})
        destination, source = a.get("destination"), a.get("source")
        if isinstance(destination, SampledFeatures) or isinstance(source, SampledFeatures):
            fail("Sampled FeatureCollection copyProperties is unsupported")
        if not _looks_like_collection(destination) or not _looks_like_collection(source):
            fail("FeatureCollection copyProperties requires inline FeatureCollection source and destination")
        return _copy_properties(
            translator, destination, source, a.get("properties"), a.get("exclude"),
        )
    fail(f"Unsupported collection metadata algorithm: {name}")
