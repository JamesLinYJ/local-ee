"""Bounded validation and ownership for Element metadata values.

The public encoder can describe StaticArray and concrete joined Image values,
but metadata operations must keep those values typed until the final boundary.
This module preflights the public envelope and a detached-copy plan before it
allocates any returned dictionaries, arrays, or mutable Image wrappers.
"""
from __future__ import annotations

import math

import numpy as np

from .array_core import MAX_ARRAY_CELLS, MAX_ARRAY_RANK, StaticArray
from .feature_table_construction import _public_value_size
from .ir import Image, Pixel, fail


MAX_METADATA_WORK = 50_000
MAX_METADATA_BYTES = 1_000_000
MAX_METADATA_ENTRIES = 10_000
MAX_METADATA_DEPTH = 96


def charge_metadata(translator, amount, label="Element metadata"):
    """Reserve work against the shared 50000-step compilation budget."""
    if amount < 0 or translator.steps + amount > MAX_METADATA_WORK:
        fail(f"{label} exceeds the 50000-step compilation work budget")
    translator.steps += amount


def preflight_public_value(translator, value, label="Element metadata"):
    """Validate and account for the final public JSON form without flattening IR."""
    copy_cost = _copy_plan(translator, value, set())
    charge_metadata(translator, copy_cost, label + " JSON preflight")
    public_form = _public_form(translator, value, set())
    wire = [0]
    try:
        _public_value_size(translator, public_form, wire)
    except RecursionError:
        fail(f"{label} exceeds the metadata nesting limit")
    if wire[0] > MAX_METADATA_BYTES:
        fail(f"{label} exceeds the 1 MB JSON size limit")
    return wire[0]


def _copy_plan(translator, value, active, depth=0):
    """Precharge a structural scan and return the later detached-copy cost."""
    if depth > MAX_METADATA_DEPTH:
        fail("Element metadata exceeds the depth limit")
    charge_metadata(translator, 1)
    kind = type(value)
    if value is None or kind in (bool, int, float, str):
        if kind is float and not math.isfinite(value):
            fail("Element metadata numbers must be finite")
        if kind is str:
            charge_metadata(translator, len(value))
        return 1 + (len(value) if kind is str else 0)
    if kind is StaticArray:
        data = value.data
        if (
            not isinstance(data, np.ndarray)
            or data.ndim > MAX_ARRAY_RANK
            or data.size > MAX_ARRAY_CELLS
            or data.dtype.kind not in "iuf"
        ):
            fail("Element metadata arrays must be finite real arrays of at most 10000 cells")
        charge_metadata(translator, int(data.size))
        if not np.isfinite(data).all():
            fail("Element metadata arrays must be finite real arrays of at most 10000 cells")
        return 1 + int(data.size)
    if kind is Image:
        if value.mapped:
            fail("Nested Element metadata Images must be concrete and unmapped")
        identity = id(value)
        if identity in active:
            fail("Element metadata cannot contain cyclic Images")
        if type(value.props) is not dict or type(value.bands) is not list:
            fail("Element metadata Image representation is malformed")
        if len(value.bands) > MAX_METADATA_ENTRIES:
            fail("Element metadata Image has too many bands")
        charge_metadata(translator, 2 + len(value.bands))
        active.add(identity)
        try:
            cost = 2 + _copy_plan(translator, value.props, active, depth + 1)
            for band in value.bands:
                if (type(band) is not tuple or len(band) != 2
                        or type(band[0]) is not str or not isinstance(band[1], Pixel)):
                    fail("Element metadata Image requires valid named Pixel bands")
                charge_metadata(translator, len(band[0]) + 1)
                cost += 1 + len(band[0])
            if value.footprint is not None:
                cost += _copy_plan(translator, value.footprint, active, depth + 1)
            return cost
        finally:
            active.remove(identity)
    if not isinstance(value, dict) and kind is not list:
        fail(f"Element metadata cannot copy {kind.__name__} values")
    identity = id(value)
    if identity in active:
        fail("Element metadata cannot contain cycles")
    if len(value) > MAX_METADATA_ENTRIES:
        fail("Element metadata containers support at most 10000 entries")
    charge_metadata(translator, 1 + len(value))
    active.add(identity)
    try:
        cost = 1 + len(value)
        if isinstance(value, dict):
            for key, child in value.items():
                if type(key) is not str:
                    fail("Element metadata dictionaries require string keys")
                charge_metadata(translator, len(key))
                cost += 1 + len(key) + _copy_plan(translator, child, active, depth + 1)
            from .geometry_values import GeometryValue

            if isinstance(value, GeometryValue):
                metadata = value.geometry_metadata
                if type(metadata) is not dict or len(metadata) > 8:
                    fail("Geometry constructor metadata is malformed")
                cost += _copy_plan(translator, metadata, active, depth + 1)
        else:
            for child in value:
                cost += _copy_plan(translator, child, active, depth + 1)
        return cost
    finally:
        active.remove(identity)


def _public_form(translator, value, active):
    """Build a charged JSON-sizing view while retaining nonpublic IR types."""
    from .geometry_values import GeometryValue

    kind = type(value)
    if isinstance(value, GeometryValue):
        # Its GeoJSON mapping is public; constructor flags remain typed
        # sidecar metadata used by Geometry accessors.
        return {key: _public_form(translator, child, active)
                for key, child in value.items()}
    if kind is Image:
        identity = id(value)
        if identity in active:
            fail("Element metadata cannot contain cyclic Images")
        active.add(identity)
        try:
            return Image(
                value.bands, _public_form(translator, value.props, active),
                value.source, value.mapped, value.inherit_props,
                value.copied_props,
                _public_form(translator, value.footprint, active)
                if value.footprint is not None else None,
                value.footprint_is_absolute,
            )
        finally:
            active.remove(identity)
    if kind not in (dict, list):
        return value
    identity = id(value)
    if identity in active:
        fail("Element metadata cannot contain cycles")
    active.add(identity)
    try:
        if isinstance(value, dict):
            return {key: _public_form(translator, child, active)
                    for key, child in value.items()}
        return [_public_form(translator, child, active) for child in value]
    finally:
        active.remove(identity)


def _clone(value, memo):
    """Copy mutable public containers and wrappers while retaining typed IR."""
    from .geometry_values import GeometryValue

    identity = id(value)
    if identity in memo:
        return memo[identity]
    kind = type(value)
    if kind is StaticArray:
        result = StaticArray(value.data.copy())
        result.data.flags.writeable = False
        memo[identity] = result
        return result
    if kind is Image:
        result = Image([], {}, value.source, value.mapped, value.inherit_props,
                       value.copied_props, None, value.footprint_is_absolute)
        memo[identity] = result
        result.props = _clone(value.props, memo)
        result.bands = [(name, pixel) for name, pixel in value.bands]
        if value.footprint is not None:
            result.footprint = _clone(value.footprint, memo)
        return result
    if isinstance(value, GeometryValue):
        result = GeometryValue(
            {}, _clone(value.geometry_metadata, memo),
            validated=value._geometry_validated,
        )
        memo[identity] = result
        result.update((key, _clone(child, memo)) for key, child in value.items())
        return result
    if isinstance(value, dict):
        result = {}
        memo[identity] = result
        result.update((key, _clone(child, memo)) for key, child in value.items())
        return result
    if kind is list:
        result = []
        memo[identity] = result
        result.extend(_clone(child, memo) for child in value)
        return result
    return value


def owned_metadata_copy(translator, value, label="Element metadata"):
    """Preflight JSON size, cycles and copy work, then return an owned value."""
    copy_cost = preflight_owned_metadata_value(translator, value, label)
    charge_metadata(translator, copy_cost, label + " copy")
    return _clone(value, {})


def preflight_owned_metadata_value(translator, value, label="Element metadata"):
    """Preflight public size and mutable-copy safety without materializing."""
    copy_cost = _copy_plan(translator, value, set())
    charge_metadata(translator, copy_cost, label + " JSON preflight")
    public_form = _public_form(translator, value, set())
    wire = [0]
    try:
        _public_value_size(translator, public_form, wire)
    except RecursionError:
        fail(f"{label} exceeds the metadata nesting limit")
    if wire[0] > MAX_METADATA_BYTES:
        fail(f"{label} exceeds the 1 MB JSON size limit")
    return copy_cost
