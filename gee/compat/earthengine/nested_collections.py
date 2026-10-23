"""Bounded nested FeatureCollection construction and flatten operations."""
from __future__ import annotations

import copy

from .feature_table_construction import preflight_feature_collection_output
from .feature_values import charge, is_collection, is_feature
from .ir import fail
from .nested_collection_values import (
    NestedFeatureCollection,
    _MAX_CHILDREN,
    _clone_collection,
    _iter_feature_refs,
    _measure_collection,
    _new_state,
    _node,
    _scan_json,
    _collection_parts,
    is_collection_value,
    is_nested_collection,
)


def handles_nested_collection_operation(name, arguments):
    return name == "Collection.flatten" and is_collection_value(arguments.get("collection"))


def invoke_nested_collection_operation(translator, name, arguments):
    if name != "Collection.flatten":
        fail(f"Unsupported nested FeatureCollection operation: {name}")
    translator.allowed(arguments, {"collection"})
    return flatten_collection(translator, arguments.get("collection"))


def _preflight_public_output(translator, rows, properties, include_properties):
    source = {"type": "FeatureCollection", "features": []}
    if include_properties:
        source["properties"] = properties
    preflight_feature_collection_output(translator, source, rows)


def construct_nested_collection(translator, collections, metadata=None):
    """Build an owned nested IR from homogeneous finite FeatureCollections."""
    if type(collections) not in (list, tuple) or len(collections) > _MAX_CHILDREN:
        fail("Nested FeatureCollection constructor supports at most 1000 children")
    charge(translator, 1 + len(collections))
    if not collections:
        fail("Nested FeatureCollection constructor requires only child collections")
    kinds = set()
    for child in collections:
        if is_collection_value(child):
            kinds.add("collection")
        elif is_feature(child):
            kinds.add("feature")
        else:
            fail("Nested FeatureCollection constructor requires only child collections")
    if len(kinds) > 1:
        fail("Nested FeatureCollection cannot mix Features and child collections")
    if kinds != {"collection"}:
        fail("Nested FeatureCollection constructor requires only child collections")

    state = _new_state()
    _node(state)
    state["copy_work"] += 1 + len(collections)
    active = set()
    for child in collections:
        _measure_collection(translator, state, child, 1, active)
    if metadata is None:
        properties, include_properties = {}, False
    elif type(metadata) is tuple and len(metadata) == 2:
        properties, include_properties = metadata
    else:
        fail("Nested FeatureCollection metadata is invalid")
    if type(properties) is not dict or type(include_properties) is not bool:
        fail("Nested FeatureCollection metadata is invalid")
    root_copy_before = state["copy_work"]
    _scan_json(translator, state, properties, 1, active)
    state["root_copy_work"] += state["copy_work"] - root_copy_before
    charge(translator, state["nodes"] + state["rows"])
    # Precharge row references and the owned clone before materializing either.
    charge(translator, state["copy_work"] + len(collections) + 1)
    rows = list(_iter_feature_refs(collections))
    _preflight_public_output(translator, rows, properties, include_properties)
    return NestedFeatureCollection(
        tuple(_clone_collection(child) for child in collections),
        copy.deepcopy(properties), include_properties,
    )


def flatten_collection(translator, value):
    """Flatten child collection trees into an owned, ordinary FeatureCollection."""
    if is_collection(value):
        charge(translator, 4)
        elements, properties, include_properties = _collection_parts(value)
        if elements:
            fail("Collection.flatten requires a finite nested FeatureCollection")
        # Empty mapped input has no callback result from which to infer nested IR.
        state = _new_state()
        _scan_json(translator, state, properties, 0, set())
        _preflight_public_output(translator, [], properties, include_properties)
        charge(translator, state["copy_work"] + 4)
        return {
            "type": "FeatureCollection", "features": [],
            **({"properties": copy.deepcopy(properties)} if include_properties else {}),
        }
    if not is_nested_collection(value):
        fail("Collection.flatten requires a finite nested FeatureCollection")
    state = _new_state()
    _measure_collection(translator, state, value, 0, set())
    charge(translator, state["nodes"] + state["rows"])
    charge(translator, state["row_copy_work"] + state["root_copy_work"]
           + state["rows"] + 4)
    elements, properties, include_properties = _collection_parts(value)
    rows = list(_iter_feature_refs(elements))
    _preflight_public_output(translator, rows, properties, include_properties)
    # Child metadata was validated but only the outer properties are retained.
    output = [copy.deepcopy(feature) for feature in rows]
    copied_properties = copy.deepcopy(properties) if include_properties else {}
    return {
        "type": "FeatureCollection",
        "features": output,
        **({"properties": copied_properties} if include_properties else {}),
    }
