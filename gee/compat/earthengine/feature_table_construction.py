"""Bounded copying and construction for finite FeatureCollections."""
from __future__ import annotations

import copy
import json
import math

import numpy as np

from .array_values import StaticArray
from .feature_values import charge, validate_json_value
from .ir import Image, Pixel, fail


_MAX_FEATURES = 1000
_MAX_PROPERTIES = 10000
_MAX_JSON_BYTES = 1_000_000


def _copy_work(value, depth=0, active=None):
    """Estimate bounded object-copy work before deepcopy starts."""
    if depth > 96:
        fail("FeatureCollection copy exceeds the metadata depth limit")
    if active is None:
        active = set()
    kind = type(value)
    if value is None or kind in (bool, int, float):
        return 1
    if kind is str:
        return 1 + len(value)
    if kind is StaticArray:
        return 1 + int(value.data.size)
    if kind is Pixel:
        return 1 + sum(_copy_work(child, depth + 1, active) for child in value.args)
    if kind is Image:
        identity = id(value)
        if identity in active:
            fail("FeatureCollection values cannot contain cyclic Images")
        active.add(identity)
        try:
            return (2 + _copy_work(value.props, depth + 1, active)
                    + sum(1 + len(name) + _copy_work(pixel, depth + 1, active)
                          for name, pixel in value.bands))
        finally:
            active.remove(identity)
    from .geometry_values import GeometryValue

    if kind is GeometryValue:
        identity = id(value)
        if identity in active:
            fail("FeatureCollection values cannot contain cyclic metadata")
        if len(value) > _MAX_PROPERTIES:
            fail("FeatureCollection values support at most 10000 container entries")
        active.add(identity)
        try:
            mapping_work = 1 + sum(
                1 + len(key) + _copy_work(child, depth + 1, active)
                for key, child in value.items()
            )
            return mapping_work + _copy_work(
                value.geometry_metadata, depth + 1, active,
            )
        finally:
            active.remove(identity)
    if kind in (dict, list, tuple):
        identity = id(value)
        if identity in active:
            fail("FeatureCollection values cannot contain cyclic metadata")
        if len(value) > _MAX_PROPERTIES:
            fail("FeatureCollection values support at most 10000 container entries")
        active.add(identity)
        try:
            if kind is dict:
                if any(type(key) is not str for key in value):
                    fail("Feature properties require string keys")
                return 1 + sum(1 + len(key) + _copy_work(child, depth + 1, active)
                               for key, child in value.items())
            return 1 + sum(_copy_work(child, depth + 1, active) for child in value)
        finally:
            active.remove(identity)
    fail(f"FeatureCollection cannot copy {kind.__name__} values")


def _copy_features(translator, features):
    work = 1 + sum(_copy_work(feature) for feature in features)
    charge(translator, work)
    return copy.deepcopy(features)


def _wire_add(wire, amount):
    if amount > _MAX_JSON_BYTES - wire[0]:
        fail("FeatureCollection output exceeds the 1 MB public JSON limit")
    wire[0] += amount


def _text_size(translator, value, wire):
    """Precharge and measure a string as public_values serializes it."""
    base = len(value) + 2
    charge(translator, base)
    _wire_add(wire, base)
    size = base
    for character in value:
        code = ord(character)
        if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
            extra = 1
        elif code < 32 or code >= 127:
            extra = 5 if code <= 0xffff else 11
        else:
            extra = 0
        if extra:
            charge(translator, extra)
            _wire_add(wire, extra)
            size += extra
    return size


def _number_size(translator, value, wire):
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        fail("Computed values must be finite")
    if type(value) is int:
        if value.bit_length() > 160000:
            fail("FeatureCollection output exceeds the 1 MB public JSON limit")
        # Reserve decimal conversion and formatting before allocating text.
        digits = max(1, math.ceil(value.bit_length() * math.log10(2)))
        charge(translator, 1 + digits + (value < 0))
    else:
        charge(translator, 1)
    size = len(json.dumps(value, allow_nan=False))
    if type(value) is not int:
        charge(translator, size)
    _wire_add(wire, size)
    return size


def _array_list_size(shape):
    size = 0
    prefixes = 1
    for dimension in shape:
        size += prefixes * (2 + 2 * max(0, dimension - 1))
        prefixes *= dimension
    return size


def _public_value_size(translator, value, wire, active=None, depth=0, overrides=None):
    """Preflight public_values' bounded JSON size without materializing output."""
    if depth > 96:
        fail("Computed metadata exceeds materialization limits")
    if active is None:
        active = set()
    kind = type(value)
    from .geometry_values import GeometryValue

    if kind is GeometryValue:
        # Geometry flags live in a private sidecar; public GeoJSON contains
        # only the normalized mapping, matching public_values.public_value.
        kind = dict
    if value is None:
        charge(translator)
        _wire_add(wire, 4)
        return 4
    if kind is bool:
        charge(translator)
        size = 4 if value else 5
        _wire_add(wire, size)
        return size
    if kind in (int, float):
        return _number_size(translator, value, wire)
    if kind is str:
        return _text_size(translator, value, wire)
    if kind is StaticArray:
        data = value.data
        if (not isinstance(data, np.ndarray) or data.ndim > 8
                or data.size > _MAX_FEATURES * _MAX_PROPERTIES
                or data.dtype.kind not in "iuf" or not np.isfinite(data).all()):
            fail("FeatureCollection output contains an unsupported ee.Array")
        list_nodes = sum(math.prod(data.shape[:axis]) for axis in range(data.ndim))
        charge(translator, int(data.size) + int(list_nodes))
        _wire_add(wire, _array_list_size(data.shape))
        total = _array_list_size(data.shape)
        for scalar in data.flat:
            numeric = scalar.item()
            try:
                finite = math.isfinite(numeric)
            except OverflowError:
                finite = False
            if not finite:
                fail("Computed values must be finite")
            size = len(json.dumps(numeric, allow_nan=False))
            charge(translator, size)
            _wire_add(wire, size)
            total += size
        return total
    if kind is Image:
        identity = id(value)
        if identity in active:
            fail("FeatureCollection values cannot contain cyclic Images")
        active.add(identity)
        try:
            # Match public_value's finite Image description exactly: four map
            # fields, selected system:index, properties, and band-name list.
            charge(translator, 1 + 4)
            image_size = 2 + 2 * 4 + 2 * 3
            _wire_add(wire, image_size)
            total = image_size
            for key in ("type", "id", "properties", "bands"):
                total += _text_size(translator, key, wire)
            total += _text_size(translator, "Image", wire)
            total += _public_value_size(
                translator, value.props.get("system:index"), wire,
                active, depth + 1, overrides,
            )
            total += _public_value_size(
                translator, value.props, wire, active, depth + 1, overrides,
            )
            charge(translator, 1 + len(value.bands))
            bands_size = 2 + 2 * max(0, len(value.bands) - 1)
            _wire_add(wire, bands_size)
            total += bands_size
            for name, _ in value.bands:
                charge(translator, 1 + 1)
                _wire_add(wire, 4)
                total += 4
                total += _text_size(translator, "id", wire)
                total += _text_size(translator, name, wire)
            return total
        finally:
            active.remove(identity)
    if kind not in (dict, list):
        fail(f"Unsupported internal value at the public JSON boundary: {kind.__name__}")
    identity = id(value)
    if identity in active:
        fail("FeatureCollection values cannot contain cyclic metadata")
    if len(value) > _MAX_PROPERTIES:
        fail("FeatureCollection values support at most 10000 container entries")
    active.add(identity)
    try:
        count = len(value)
        charge(translator, 1 + count)
        structural = (2 + 2 * count + 2 * max(0, count - 1)
                      if kind is dict else 2 + 2 * max(0, count - 1))
        _wire_add(wire, structural)
        total = structural
        if kind is dict:
            for key, child in value.items():
                if type(key) is not str:
                    fail("Computed dictionary keys must be strings")
                total += _text_size(translator, key, wire)
                child = (overrides or {}).get(identity, {}).get(key, child)
                total += _public_value_size(
                    translator, child, wire, active, depth + 1, overrides,
                )
        else:
            for child in value:
                total += _public_value_size(
                    translator, child, wire, active, depth + 1, overrides,
                )
        return total
    finally:
        active.remove(identity)


def preflight_feature_collection_output(translator, source, features, *, overrides=None):
    """Check the public output envelope before row or metadata deepcopies."""
    collection = {"type": "FeatureCollection", "features": features}
    if "properties" in source:
        collection["properties"] = source["properties"]
    wrapper = {"kind": "value", "value": collection,
               "warnings": translator.warnings}
    wire = [0]
    _public_value_size(translator, wrapper, wire, overrides=overrides)


def _from_columns(translator, arguments):
    translator.allowed(arguments, {"columns", "propertyNames", "propertyTypes"})
    columns = arguments.get("columns")
    names = arguments.get("propertyNames")
    if type(columns) is not list or len(columns) > _MAX_PROPERTIES:
        fail("FeatureCollection.fromColumns columns must be a list of at most 10000 columns")
    if type(names) is not list or len(names) > _MAX_PROPERTIES:
        fail("FeatureCollection.fromColumns propertyNames must be a list of at most 10000 names")
    if len(columns) != len(names):
        fail("FeatureCollection.fromColumns columns and propertyNames must have equal lengths")
    if any(type(name) is not str for name in names):
        fail("FeatureCollection.fromColumns propertyNames must contain only strings")
    charge(translator, len(names) + sum(map(len, names)))
    if len(set(names)) != len(names):
        fail("FeatureCollection.fromColumns propertyNames must be unique")
    property_types = arguments.get("propertyTypes")
    if property_types is not None:
        fail("FeatureCollection.fromColumns propertyTypes is unsupported because its value schema is undocumented")
    row_count = None
    for column in columns:
        if type(column) is not list:
            fail("FeatureCollection.fromColumns requires literal list columns")
        if len(column) > _MAX_FEATURES:
            fail("FeatureCollection.fromColumns supports at most 1000 rows")
        if row_count is None:
            row_count = len(column)
        elif len(column) != row_count:
            fail("FeatureCollection.fromColumns columns must have equal row counts")
        charge(translator, 1 + len(column))
        for value in column:
            validate_json_value(translator, value)
    row_count = row_count or 0

    # Measure the exact output envelope before row dictionaries or deep copies
    # are created. Property-name scans are intentionally repeated per row: JSON
    # output repeats each key in every feature.
    wire = [0]
    outer = {"kind": "value", "value": None, "warnings": []}
    fixed = 2 + 2 * len(outer) + 2 * (len(outer) - 1)
    _wire_add(wire, fixed)
    charge(translator, 1 + len(outer))
    for key in outer:
        _text_size(translator, key, wire)
    _text_size(translator, "value", wire)
    _public_value_size(translator, translator.warnings, wire)

    # The FeatureCollection and its feature-list structure.
    _wire_add(wire, 2 + 2 * 2 + 2)
    charge(translator, 3)
    _text_size(translator, "type", wire)
    _text_size(translator, "features", wire)
    _text_size(translator, "FeatureCollection", wire)
    feature_list = 2 + 2 * max(0, row_count - 1)
    _wire_add(wire, feature_list)
    charge(translator, 1 + row_count)

    property_map_size = 2 + 2 * len(names) + 2 * max(0, len(names) - 1)
    _wire_add(wire, row_count * property_map_size)
    charge(translator, row_count * (1 + len(names)))
    for name in names:
        for _ in range(row_count):
            _text_size(translator, name, wire)

    for row_index in range(row_count):
        # Feature row object and its fixed field names/values.
        charge(translator, 1 + 3)
        _wire_add(wire, 2 + 2 * 3 + 2 * 2)
        _text_size(translator, "type", wire)
        _text_size(translator, "geometry", wire)
        _text_size(translator, "properties", wire)
        _text_size(translator, "Feature", wire)
        charge(translator)
        _wire_add(wire, 4)  # null geometry
        # Per-row cell scans and exact public output size.
        for column in columns:
            value = column[row_index]
            _public_value_size(translator, value, wire)

    work = 1 + row_count * (1 + len(names))
    work += sum(_copy_work(value) for column in columns for value in column)
    charge(translator, work)
    rows = []
    for row_index in range(row_count):
        properties = {
            name: copy.deepcopy(columns[column_index][row_index])
            for column_index, name in enumerate(names)
        }
        rows.append({"type": "Feature", "geometry": None, "properties": properties})
    return {"type": "FeatureCollection", "features": rows}


def invoke_feature_table_construction(translator, name, arguments):
    if name == "Collection.fromColumns":
        return _from_columns(translator, arguments)
    fail(f"Unsupported Earth Engine algorithm: {name}")
