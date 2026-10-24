"""Typed Element metadata getters and bounded property replacement."""
from __future__ import annotations

import math

from .array_core import StaticArray
from .ir import Image, fail
from .owned_metadata_values import (
    charge_metadata,
    owned_metadata_copy,
    preflight_public_value,
)


ELEMENT_METADATA_VALUE_METHODS = frozenset({
    "Element.getNumber", "Element.getString", "Element.getArray",
    "Element.toDictionary", "Element.replaceProperties",
})
ELEMENT_METADATA_VALUE_ARGUMENTS = {
    "Element.getNumber": (frozenset({"object", "property"}), frozenset()),
    "Element.getString": (frozenset({"object", "property"}), frozenset()),
    "Element.getArray": (frozenset({"object", "property"}), frozenset()),
    "Element.toDictionary": (frozenset({"element"}), frozenset({"properties"})),
    "Element.replaceProperties": (frozenset({"destination"}), frozenset({"source"})),
}
_MAX_PROPERTIES = 10_000
_MAX_FEATURES = 1_000


def handles_element_metadata_values(name, arguments):
    """Claim all scoped methods so unsupported receivers fail explicitly."""
    return name in ELEMENT_METADATA_VALUE_METHODS


def _arguments(translator, name, arguments):
    if type(arguments) is not dict:
        fail(f"{name} arguments must be a dictionary")
    required, optional = ELEMENT_METADATA_VALUE_ARGUMENTS[name]
    translator.allowed(arguments, required | optional)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def _property_map(translator, value, *, label, allow_mapped=False, requested=None):
    if type(value) is dict and value.get("type") == "Feature":
        properties = value.get("properties")
        if type(properties) is not dict or len(properties) > _MAX_PROPERTIES:
            fail(f"{label} Feature properties must be a bounded dictionary with string keys")
        charge_metadata(translator, 1 + len(properties), label)
        for key in properties:
            charge_metadata(translator, 1 + len(key) if type(key) is str else 1, label)
            if type(key) is not str:
                fail(f"{label} Feature properties must have string keys")
        if "id" in value and type(value["id"]) is not str:
            fail(f"{label} Feature id must be a string")
        return properties, "feature"
    if type(value) is dict and value.get("type") == "FeatureCollection":
        features = value.get("features")
        if type(features) is not list or len(features) > _MAX_FEATURES:
            fail(f"{label} requires an inline FeatureCollection of at most 1000 features")
        properties = value.get("properties", {})
        if type(properties) is not dict or len(properties) > _MAX_PROPERTIES:
            fail(f"{label} FeatureCollection metadata must be a bounded string-keyed dictionary")
        charge_metadata(translator, 1 + len(properties), label)
        for key in properties:
            charge_metadata(translator, 1 + len(key) if type(key) is str else 1, label)
            if type(key) is not str:
                fail(f"{label} FeatureCollection metadata must have string keys")
        return properties, "collection"
    if isinstance(value, Image):
        properties = value.props
        if type(properties) is not dict or len(properties) > _MAX_PROPERTIES:
            fail(f"{label} Image metadata must be a bounded string-keyed dictionary")
        charge_metadata(translator, 1 + len(properties), label)
        for key in properties:
            charge_metadata(translator, 1 + len(key) if type(key) is str else 1, label)
            if type(key) is not str:
                fail(f"{label} Image metadata must have string keys")
        if value.mapped and not allow_mapped:
            fail(f"{label} does not support a mapped or opaque Image receiver")
        if value.mapped and requested is not None:
            charge_metadata(translator, len(requested), label)
            for key in requested:
                if key not in properties:
                    fail(f"{label} cannot resolve mapped Image property {key!r}")
        return properties, "image"
    fail(f"{label} requires an inline Feature, FeatureCollection, or concrete Image")


def _property_name(translator, value, label):
    if type(value) is not str:
        fail(f"{label} property must be a string")
    charge_metadata(translator, 1 + len(value), label + " property")
    return value


def _typed_getter(translator, name, arguments):
    _arguments(translator, name, arguments)
    key = _property_name(translator, arguments["property"], name)
    properties, _ = _property_map(
        translator, arguments["object"], label=name,
        allow_mapped=True, requested=[key],
    )
    value = properties.get(key)
    if value is None:
        # Missing and explicit null share this local nullable policy.
        preflight_public_value(translator, None, name)
        return None
    if name == "Element.getNumber":
        if type(value) not in (int, float):
            fail("Element.getNumber requires a numeric property or null")
        if type(value) is float and not math.isfinite(value):
            fail("Element.getNumber requires a finite numeric property")
    elif name == "Element.getString":
        if type(value) is not str:
            fail("Element.getString requires a string property or null")
    elif type(value) is not StaticArray:
        fail("Element.getArray requires a static ee.Array property or null")
    return owned_metadata_copy(translator, value, name)


def _property_names(translator, value, label):
    if type(value) is not list or len(value) > _MAX_PROPERTIES:
        fail(f"{label} must be a list of at most 10000 property names")
    charge_metadata(translator, 1 + len(value), label)
    for name in value:
        if type(name) is not str:
            fail(f"{label} must contain only strings")
        charge_metadata(translator, len(name), label)
    if len(set(value)) != len(value):
        fail(f"{label} cannot contain duplicate names")
    return value


def _to_dictionary(translator, arguments):
    name = "Element.toDictionary"
    _arguments(translator, name, arguments)
    explicit = "properties" in arguments and arguments["properties"] is not None
    names = _property_names(translator, arguments["properties"], name) if explicit else None
    properties, _ = _property_map(
        translator, arguments["element"], label=name, allow_mapped=explicit,
        requested=names,
    )
    if names is None:
        charge_metadata(translator, len(properties), name)
        names = []
        for key in properties:
            charge_metadata(translator, 1 + len(key), name)
            if not key.startswith("system:"):
                names.append(key)
    # A missing requested key is omitted under this local static-value policy.
    charge_metadata(translator, 1 + len(names), name)
    selected = {}
    for key in names:
        if key in properties:
            selected[key] = properties[key]
    return owned_metadata_copy(translator, selected, name)


def _element_source_properties(translator, source, label):
    if source is None:
        return {}
    properties, _ = _property_map(
        translator, source, label=label, allow_mapped=False,
    )
    return properties



def _feature_identity(feature):
    properties = feature.get("properties")
    if type(properties) is not dict:
        fail("Element.replaceProperties destination Feature has invalid properties")
    top_id = feature.get("id")
    system_index = properties.get("system:index")
    if "id" in feature and type(top_id) is not str:
        fail("Feature ids must be strings")
    if "system:index" in properties and type(system_index) is not str:
        fail("Feature system:index must be a string")
    if top_id is not None and system_index is not None and top_id != system_index:
        fail("Feature id and system:index identify different elements")
    return top_id if top_id is not None else system_index


def _replace_feature_properties(feature, replacement):
    identity = _feature_identity(feature)
    result = {**feature, "properties": replacement}
    if ("system:index" in replacement
            and type(replacement["system:index"]) is not str):
        fail("Element.replaceProperties source system:index must be a string")
    replacement_index = replacement.get("system:index")
    if (identity is not None and replacement_index is not None
            and replacement_index != identity):
        fail("Element.replaceProperties source system:index conflicts with "
             "the destination Feature id")
    if identity is not None and replacement_index is None and "id" not in result:
        # Carry the real source identity when replacement removes its property.
        result["id"] = identity
    return result


def _replace_properties(translator, arguments):
    name = "Element.replaceProperties"
    _arguments(translator, name, arguments)
    destination = arguments["destination"]
    replacement = _element_source_properties(translator, arguments.get("source"), name)
    if type(destination) is dict and destination.get("type") == "Feature":
        _property_map(translator, destination, label=name)
        charge_metadata(translator, 1 + len(destination), name + " result")
        result = _replace_feature_properties(destination, replacement)
        return owned_metadata_copy(translator, result, name)
    if type(destination) is dict and destination.get("type") == "FeatureCollection":
        _property_map(translator, destination, label=name)
        charge_metadata(translator, 1 + len(destination), name + " result")
        result = {**destination, "properties": replacement}
        return owned_metadata_copy(translator, result, name)
    if isinstance(destination, Image):
        if destination.mapped:
            fail(f"{name} does not support a mapped Image destination")
        image_index = destination.props.get("system:index")
        if "system:index" in destination.props:
            if type(image_index) is not str:
                fail("Element.replaceProperties Image system:index must be a string")
            replacement_index = replacement.get("system:index")
            if ("system:index" in replacement
                    and type(replacement_index) is not str):
                fail("Element.replaceProperties source Image system:index must be a string")
            if (replacement_index is not None and replacement_index != image_index):
                fail("Element.replaceProperties source system:index conflicts with "
                     "the destination Image id")
            if replacement_index is None:
                # Local identity policy retains a real destination index even
                # though the API inventory specifies that null clears props.
                charge_metadata(translator, 1 + len(replacement), name + " Image id")
                replacement = {**replacement, "system:index": image_index}
        charge_metadata(translator, 1 + len(destination.bands), name + " result")
        staged = Image(
            destination.bands, replacement, destination.source, False,
            False, (), destination.footprint, destination.footprint_is_absolute,
        )
        # Prevent cleared catalog properties from reappearing on resolution.
        return owned_metadata_copy(translator, staged, name)
    fail(f"{name} destination must be an inline Feature, FeatureCollection, or concrete Image")


def invoke_element_metadata_values(translator, name, arguments):
    """Evaluate one typed metadata getter, conversion, or property replacement."""
    if name not in ELEMENT_METADATA_VALUE_METHODS:
        fail(f"Unsupported Element metadata operation: {name}")
    if name in {"Element.getNumber", "Element.getString", "Element.getArray"}:
        return _typed_getter(translator, name, arguments)
    if name == "Element.toDictionary":
        return _to_dictionary(translator, arguments)
    return _replace_properties(translator, arguments)
