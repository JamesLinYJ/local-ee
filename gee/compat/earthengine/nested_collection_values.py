"""Validation and traversal for bounded nested FeatureCollection IR."""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass

import numpy as np

from .array_values import MAX_ARRAY_CELLS, MAX_ARRAY_RANK, StaticArray
from .feature_values import charge, is_collection, is_feature
from .geometry_values import GEOMETRY_TYPES
from .ir import Image, SampledFeatures, fail


_MAX_CHILDREN = 1000
_MAX_ROWS = 1000
_MAX_NODES = 10000
_MAX_DEPTH = 96
_MAX_PROPERTIES = 10000


@dataclass(frozen=True)
class NestedFeatureCollection:
    """Internal collection-of-collections; never accepted as a flat table."""

    elements: tuple
    properties: dict
    include_properties: bool = False

    def __bool__(self):
        fail("Nested FeatureCollections are not static conditions")


def is_nested_collection(value):
    return isinstance(value, NestedFeatureCollection)


def is_collection_value(value):
    return is_collection(value) or is_nested_collection(value)


def _new_state():
    return {
        "nodes": 0, "rows": 0, "copy_work": 0,
        "row_copy_work": 0, "root_copy_work": 0,
    }


def _node(state, amount=1):
    state["nodes"] += amount
    if state["nodes"] > _MAX_NODES:
        fail("Nested FeatureCollection exceeds 10000 total nodes")


def _string(translator, state, value):
    if type(value) is not str:
        fail("Nested FeatureCollection JSON keys and text must be strings")
    charge(translator, len(value) + 1)
    _node(state)
    state["copy_work"] += len(value) + 1


def _scan_json(translator, state, value, depth, active):
    if depth > _MAX_DEPTH:
        fail("Nested FeatureCollection exceeds depth 96")
    kind = type(value)
    from .geometry_values import GeometryValue

    geometry_value = kind is GeometryValue
    if geometry_value:
        # GeometryValue is mutable, so its historical decode marker cannot
        # authorize the current coordinates or option sidecar.
        from .geometry_components import decode_component_geometry_bounded

        decode_component_geometry_bounded(translator, value)
        kind = dict
    if value is None or kind is bool:
        charge(translator)
        _node(state)
        state["copy_work"] += 1
        return
    if kind is int:
        if value.bit_length() > 160000:
            fail("Nested FeatureCollection integer exceeds the JSON output limit")
        charge(translator, 1 + math.ceil(value.bit_length() * math.log10(2)))
        _node(state)
        state["copy_work"] += 1
        return
    if kind is float:
        if not math.isfinite(value):
            fail("Nested FeatureCollection values must be finite")
        charge(translator)
        _node(state)
        state["copy_work"] += 1
        return
    if kind is str:
        _string(translator, state, value)
        return
    if kind is StaticArray:
        array = value.data
        if (not isinstance(array, np.ndarray) or array.ndim > MAX_ARRAY_RANK
                or array.size > MAX_ARRAY_CELLS or array.dtype.kind not in "iuf"):
            fail("Nested FeatureCollection arrays exceed static array limits")
        charge(translator, 1 + int(array.size))
        _node(state, 1 + int(array.size))
        if not np.isfinite(array).all():
            fail("Nested FeatureCollection arrays must be finite")
        state["copy_work"] += 1 + int(array.size)
        return
    if kind not in (dict, list):
        if isinstance(value, (Image, SampledFeatures)):
            fail("Nested FeatureCollections cannot contain dynamic Image or sampled values")
        fail(f"Nested FeatureCollection cannot contain {kind.__name__} values")
    identity = id(value)
    if identity in active:
        fail("Nested FeatureCollection values cannot be cyclic")
    if len(value) > _MAX_PROPERTIES:
        fail("Nested FeatureCollection values support at most 10000 container entries")
    charge(translator, 1 + len(value))
    _node(state)
    state["copy_work"] += 1 + len(value)
    active.add(identity)
    try:
        if kind is dict:
            for key, child in value.items():
                _string(translator, state, key)
                _scan_json(translator, state, child, depth + 1, active)
            if geometry_value:
                _scan_json(
                    translator, state, value.geometry_metadata, depth + 1, active,
                )
        else:
            for child in value:
                _scan_json(translator, state, child, depth + 1, active)
    finally:
        active.remove(identity)


def _collection_parts(value):
    if is_nested_collection(value):
        if type(value.elements) is not tuple or type(value.properties) is not dict:
            fail("Nested FeatureCollection IR is malformed")
        return value.elements, value.properties, value.include_properties
    if type(value) is not dict or not is_collection(value):
        fail("Nested FeatureCollection elements must be finite FeatureCollections")
    if len(value) > 3:
        fail("Nested FeatureCollection has unsupported collection fields")
    if set(value) - {"type", "features", "properties"}:
        fail("Nested FeatureCollection has unsupported collection fields")
    features = value.get("features")
    if type(features) is not list or len(features) > _MAX_CHILDREN:
        fail("Nested FeatureCollection requires a finite feature list")
    properties = value.get("properties", {})
    if type(properties) is not dict:
        fail("Nested FeatureCollection properties must be a JSON object")
    return features, properties, "properties" in value


def _scan_feature(translator, state, feature, depth, active):
    if type(feature) is not dict or not is_feature(feature):
        fail("Nested FeatureCollections may contain only Features or FeatureCollections")
    identity = id(feature)
    if identity in active:
        fail("Nested FeatureCollection values cannot be cyclic")
    if len(feature) > 4:
        fail("Nested FeatureCollection Feature has unsupported fields")
    charge(translator, 1 + len(feature))
    _node(state)
    state["copy_work"] += 1 + len(feature)
    state["rows"] += 1
    if state["rows"] > _MAX_ROWS:
        fail("Nested FeatureCollection flatten supports at most 1000 total rows")
    if set(feature) - {"type", "geometry", "properties", "id"}:
        fail("Nested FeatureCollection Feature has unsupported fields")
    geometry = feature.get("geometry")
    from .geometry_values import GeometryValue

    properties = feature.get("properties")
    if geometry is not None and (
        type(geometry) not in (dict, GeometryValue)
        or geometry.get("type") not in GEOMETRY_TYPES
    ):
        fail("Nested FeatureCollection geometry must be decoded GeoJSON or null")
    if geometry is not None and type(geometry) is dict:
        # Raw direct IR geometry needs the same bounded validation; typed
        # GeometryValue instances are checked by _scan_json below.
        from .geometry_components import decode_component_geometry_bounded

        decode_component_geometry_bounded(translator, geometry)
    if type(properties) is not dict:
        fail("Nested FeatureCollection Feature properties must be a JSON object")
    if "id" in feature and type(feature["id"]) is not str:
        fail("Nested FeatureCollection Feature ids must be strings")
    before = state["copy_work"]
    active.add(identity)
    try:
        for key, child in feature.items():
            _string(translator, state, key)
            _scan_json(translator, state, child, depth + 1, active)
    finally:
        active.remove(identity)
    state["row_copy_work"] += 1 + len(feature) + state["copy_work"] - before


def _measure_collection(translator, state, value, depth, active):
    if depth > _MAX_DEPTH:
        fail("Nested FeatureCollection exceeds depth 96")
    if not is_collection_value(value):
        fail("Nested FeatureCollection elements must be finite FeatureCollections")
    identity = id(value)
    if identity in active:
        fail("Nested FeatureCollections cannot be cyclic")
    elements, properties, include_properties = _collection_parts(value)
    if type(elements) not in (list, tuple) or len(elements) > _MAX_CHILDREN:
        fail("Nested FeatureCollection nodes support at most 1000 immediate elements")
    if type(include_properties) is not bool:
        fail("Nested FeatureCollection metadata flag is invalid")
    charge(translator, 1 + len(elements))
    _node(state)
    state["copy_work"] += 1 + len(elements)
    before = state["copy_work"]
    active.add(identity)
    try:
        _scan_json(translator, state, properties, depth + 1, active)
        property_work = state["copy_work"] - before
        if depth == 0:
            state["root_copy_work"] += property_work
        if len(elements):
            kinds = set()
            # The full child pass is reserved before classifying elements.
            for element in elements:
                if is_feature(element):
                    kinds.add("feature")
                elif is_collection_value(element):
                    kinds.add("collection")
                elif isinstance(element, (Image, SampledFeatures)):
                    fail("Nested FeatureCollections cannot contain Image or sampled elements")
                else:
                    fail("Nested FeatureCollections may contain only Features or FeatureCollections")
            if len(kinds) != 1:
                fail("Nested FeatureCollection cannot mix Features and child collections")
            if kinds == {"feature"}:
                if state["rows"] + len(elements) > _MAX_ROWS:
                    fail("Nested FeatureCollection flatten supports at most 1000 total rows")
                for feature in elements:
                    _scan_feature(translator, state, feature, depth + 1, active)
            else:
                for child in elements:
                    _measure_collection(translator, state, child, depth + 1, active)
    finally:
        active.remove(identity)


def _clone_collection(value):
    elements, properties, include_properties = _collection_parts(value)
    cloned = []
    for element in elements:
        cloned.append(_clone_collection(element) if is_collection_value(element)
                      else copy.deepcopy(element))
    return NestedFeatureCollection(
        tuple(cloned), copy.deepcopy(properties), include_properties,
    )


def _iter_feature_refs(elements):
    """Yield depth-first rows with O(nodes + rows) traversal work."""
    stack = [iter(elements)]
    while stack:
        try:
            element = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        if is_collection_value(element):
            stack.append(iter(_collection_parts(element)[0]))
        else:
            yield element
