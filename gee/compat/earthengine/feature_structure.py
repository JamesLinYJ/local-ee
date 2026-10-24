"""Bounded Feature identity, selection, geometry and numeric-array values."""
from __future__ import annotations

import math

import numpy as np

from .array_core import MAX_ARRAY_CELLS, StaticArray
from .geometry_values import GEOMETRY_TYPES
from .ir import fail
from .owned_metadata_values import (
    charge_metadata,
    owned_metadata_copy,
    preflight_owned_metadata_value,
    preflight_public_value,
)
from .regex_values import compile_pattern


FEATURE_STRUCTURE_METHODS = frozenset({
    "Feature.id", "Feature.select", "Feature.setGeometry", "Feature.toArray",
})
FEATURE_STRUCTURE_ARGUMENTS = {
    "Feature.id": (frozenset({"element"}), frozenset()),
    "Feature.select": (
        frozenset({"input", "propertySelectors"}),
        frozenset({"newProperties", "retainGeometry"}),
    ),
    "Feature.setGeometry": (frozenset({"feature"}), frozenset({"geometry"})),
    "Feature.toArray": (frozenset({"feature", "properties"}), frozenset()),
}
_MAX_FEATURE_PROPERTIES = 10_000
_MAX_ARRAY_CELLS = MAX_ARRAY_CELLS
_MAX_EXACT_INTEGER = 2**53
_LITERAL_SELECTOR_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_:"
)


def handles_feature_structure(name, arguments):
    """Claim scoped methods so unsupported receivers fail explicitly."""
    return name in FEATURE_STRUCTURE_METHODS


def _arguments(translator, name, arguments):
    if type(arguments) is not dict:
        fail(f"{name} arguments must be a dictionary")
    required, optional = FEATURE_STRUCTURE_ARGUMENTS[name]
    translator.allowed(arguments, required | optional)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def _feature(translator, value, label):
    if type(value) is not dict or value.get("type") != "Feature":
        fail(f"{label} requires an actual inline Feature")
    properties = value.get("properties")
    if (type(properties) is not dict or len(properties) > _MAX_FEATURE_PROPERTIES
            or any(type(key) is not str for key in properties)):
        fail(f"{label} Feature properties must be a bounded string-keyed dictionary")
    geometry = value.get("geometry")
    if geometry is not None and (
        not isinstance(geometry, dict) or geometry.get("type") not in GEOMETRY_TYPES
    ):
        fail(f"{label} Feature geometry must be decoded GeoJSON or null")
    preflight_owned_metadata_value(translator, value, label)
    return value


def _identity(feature):
    properties = feature["properties"]
    has_top = "id" in feature
    has_index = "system:index" in properties
    top = feature.get("id")
    index = properties.get("system:index")
    if has_top and type(top) is not str:
        fail("Feature ids must be strings")
    if has_index and type(index) is not str:
        fail("Feature system:index must be a string")
    if has_top and has_index and top != index:
        fail("Feature id and system:index identify different elements")
    return top if has_top else index if has_index else None


def _name_list(translator, value, label):
    if type(value) is not list or len(value) > _MAX_FEATURE_PROPERTIES:
        fail(f"{label} must be a list of at most 10000 strings")
    charge_metadata(translator, 1 + len(value), label)
    for name in value:
        if type(name) is not str:
            fail(f"{label} must contain only strings")
        charge_metadata(translator, len(name), label)
    return value


def _is_literal_selector(value):
    """Recognize ASCII names with no RE2 metacharacters for exact lookup."""
    return all(character in _LITERAL_SELECTOR_CHARS for character in value)


def _feature_id(translator, arguments):
    name = "Feature.id"
    _arguments(translator, name, arguments)
    feature = _feature(translator, arguments["element"], name)
    identity = _identity(feature)
    preflight_public_value(translator, identity, name)
    return identity


def _select(translator, arguments):
    name = "Feature.select"
    _arguments(translator, name, arguments)
    feature = _feature(translator, arguments["input"], name)
    selectors = _name_list(translator, arguments["propertySelectors"],
                           "Feature.select propertySelectors")
    properties = feature["properties"]
    if len(properties) > _MAX_FEATURE_PROPERTIES:
        fail("Feature.select supports at most 10000 input properties")
    charge_metadata(translator, 1 + len(properties), name)
    keys = list(properties)
    for key in keys:
        charge_metadata(translator, len(key), name)

    selected = []
    # Resolve overlaps in selector order and keep each source property once.
    seen = set()
    classification_work = len(selectors) + sum(len(selector) for selector in selectors)
    charge_metadata(translator, classification_work, name + " selector classification")
    literal_flags = [_is_literal_selector(selector) for selector in selectors]
    regex_count = literal_flags.count(False)
    charge_metadata(translator, len(keys) * regex_count, name + " selector scan")
    for selector, is_literal in zip(selectors, literal_flags):
        if is_literal:
            # Compile even exact names with RE2; only the redundant full scan
            # is avoided when the pattern contains no metacharacters.
            compile_pattern(translator, selector, ())
            charge_metadata(translator, len(selector) + 1, name + " exact-key lookup")
            if selector not in properties:
                continue
            charge_metadata(translator, len(selector) + 1, name + " exact-key equality")
            charge_metadata(translator, len(selector) + 1, name + " selector deduplication")
            if selector not in seen:
                charge_metadata(translator, len(selector) + 1, name + " selected property")
                seen.add(selector)
                selected.append(selector)
            continue
        pattern = compile_pattern(translator, selector, keys)
        for key in keys:
            if pattern.fullmatch(key):
                charge_metadata(translator, len(key) + 1, name + " selector deduplication")
                if key not in seen:
                    charge_metadata(translator, len(key) + 1, name + " selected property")
                    seen.add(key)
                    selected.append(key)

    rename_value = arguments.get("newProperties")
    if rename_value is None:
        output_names = list(selected)
    else:
        output_names = _name_list(
            translator, rename_value, "Feature.select newProperties",
        )
        if len(output_names) != len(selected):
            fail("Feature.select newProperties must match the number of selected properties")
    if len(set(output_names)) != len(output_names):
        fail("Feature.select output property names must be unique")

    retain_geometry = arguments.get("retainGeometry", True)
    if retain_geometry is None:
        retain_geometry = True
    if type(retain_geometry) is not bool:
        fail("Feature.select retainGeometry must be a boolean")
    identity = _identity(feature)
    charge_metadata(translator, 1 + len(selected), name + " selected properties")
    output_properties = {
        output_name: properties[source_name]
        for source_name, output_name in zip(selected, output_names)
    }
    if "system:index" in output_properties:
        new_index = output_properties.get("system:index")
        if type(new_index) is not str:
            fail("Feature.select output system:index must be a string")
        if identity is not None and new_index != identity:
            fail("Feature.select cannot replace the selected Feature identity")
    output = {**feature, "properties": output_properties}
    if not retain_geometry:
        output["geometry"] = None
    if identity is not None and "system:index" not in output_properties:
        # The local Feature form stores IDs either in top-level id or
        # properties.system:index. Preserve the real identity when selection
        # removes or renames that system property.
        output["id"] = identity
    return owned_metadata_copy(translator, output, name)


def _set_geometry(translator, arguments):
    name = "Feature.setGeometry"
    _arguments(translator, name, arguments)
    feature = _feature(translator, arguments["feature"], name)
    geometry = arguments.get("geometry")
    if geometry is not None:
        from .geometry_values import own_geometry_bounded

        geometry = own_geometry_bounded(translator, geometry)
    output = {key: value for key, value in feature.items() if key != "geometry"}
    output["geometry"] = geometry
    return owned_metadata_copy(translator, output, name)


def _to_array(translator, arguments):
    name = "Feature.toArray"
    _arguments(translator, name, arguments)
    feature = _feature(translator, arguments["feature"], name)
    properties = feature["properties"]
    names = _name_list(translator, arguments["properties"], "Feature.toArray properties")
    if len(names) > _MAX_ARRAY_CELLS:
        fail("Feature.toArray supports at most 10000 properties")
    charge_metadata(translator, len(names), name)
    values = []
    for property_name in names:
        if property_name not in properties:
            fail(f"Feature.toArray property is missing: {property_name}")
        value = properties[property_name]
        if type(value) not in (int, float):
            fail("Feature.toArray properties must be non-null real numbers")
        if type(value) is float and not math.isfinite(value):
            fail("Feature.toArray properties must be finite real numbers")
        if type(value) is int and abs(value) > _MAX_EXACT_INTEGER:
            fail("Feature.toArray integers must be in the exact Float64 domain")
        values.append(value)
    # Preflight the public list representation and reserve the array allocation
    # before NumPy receives a newly allocated buffer.
    preflight_owned_metadata_value(translator, values, name)
    charge_metadata(translator, 1 + len(values), name + " output array")
    if values:
        array = np.array(values)
    else:
        array = np.empty((0,), dtype=np.float64)
    array.flags.writeable = False
    return StaticArray(array)


def invoke_feature_structure(translator, name, arguments):
    """Evaluate one bounded Feature structure or identity operation."""
    if name not in FEATURE_STRUCTURE_METHODS:
        fail(f"Unsupported Feature structure operation: {name}")
    if name == "Feature.id":
        return _feature_id(translator, arguments)
    if name == "Feature.select":
        return _select(translator, arguments)
    if name == "Feature.setGeometry":
        return _set_geometry(translator, arguments)
    return _to_array(translator, arguments)
