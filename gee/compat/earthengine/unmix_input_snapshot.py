"""Bounded ownership snapshots for Image.unmix input Pixel graphs."""
from __future__ import annotations

import struct

from .ir import Pixel, Source, UnsupportedEEError, fail


_MAX_IR_VISITS = 50_000
_MAX_IR_DEPTH = 96


def _retain(value, retained):
    identity = id(value)
    existing = retained.get(identity)
    if existing is not None and existing is not value:
        fail("Internal Image.unmix input snapshot identity collision")
    retained[identity] = value


def _snapshot_geometry(graph, value, retained):
    """Validate and freeze one mutable geometry used by an Image.clip node."""
    from .geometry_preflight import measure_geometry
    from .geometry_values import GeometryValue, own_geometry_bounded
    from .array_core import charge_array

    if type(value) not in (dict, GeometryValue):
        fail("Image.unmix clip operands require a bounded local geometry")
    try:
        cost = measure_geometry(value)
        # Reserve an owned structural snapshot before allocating its nested
        # tuples. Geometry decoding separately precharges validation and its
        # normalized copy, keeping both operations inside the existing limit.
        charge_array(graph.t, 2 * cost.nodes + cost.positions + 8)
        checked = own_geometry_bounded(graph.t, value)
    except UnsupportedEEError:
        raise
    except (TypeError, OverflowError, RecursionError):
        fail("Image.unmix clip geometry is malformed")
    if checked.get("type") not in {"Polygon", "MultiPolygon"}:
        fail("Image.unmix supports only Polygon/MultiPolygon clip operands")

    def freeze(item):
        kind = type(item)
        if item is None:
            return ("none",)
        if kind is bool:
            return ("bool", item)
        if kind is int:
            return ("int", item)
        if kind is float:
            return ("float", struct.pack(">d", item))
        if kind is str:
            return ("str", item)
        if kind is bytes:
            return ("bytes", item)
        if kind is GeometryValue:
            _retain(item, retained)
            fields = tuple((key, freeze(child)) for key, child in item.items())
            metadata = getattr(item, "geometry_metadata", None)
            return ("geometry-value", id(item), fields, freeze(metadata))
        if kind is dict:
            _retain(item, retained)
            return ("dict", id(item), tuple(
                (freeze(key), freeze(child)) for key, child in item.items()
            ))
        if kind in (list, tuple):
            _retain(item, retained)
            return ("list" if kind is list else "tuple", id(item), tuple(
                freeze(child) for child in item
            ))
        fail("Image.unmix clip geometry contains unsupported mutable values")

    return freeze(value)


def snapshot_unmix_inputs(graph, operands):
    """Validate bounded IR and own a structural snapshot, including clip data."""
    from .array_core import charge_array
    from .geometry_values import GeometryValue

    active = set()
    complete = set()
    retained = {}
    geometries = {}
    stack = [(operands, False, 0, False)]
    visits = 0
    edges = 0
    while stack:
        value, leaving, depth, geometry_slot = stack.pop()
        charge_array(graph.t, 2)
        visits += 1
        if visits > _MAX_IR_VISITS:
            fail("Image.unmix input graph exceeds the bounded Pixel work limit")
        if depth > _MAX_IR_DEPTH:
            fail("Image.unmix input graph exceeds the bounded Pixel depth limit")
        kind = type(value)
        if kind in (type(None), bool, int, float, str, bytes):
            if kind is int:
                charge_array(graph.t, max(1, value.bit_length()))
            elif kind in (str, bytes):
                charge_array(graph.t, len(value))
            continue
        identity = id(value)
        if geometry_slot:
            if kind not in (dict, GeometryValue):
                fail("Image.unmix clip operands require a bounded local geometry")
            existing = geometries.get(identity)
            if existing is not None and existing[0] is value:
                continue
            snapshot = _snapshot_geometry(graph, value, retained)
            geometries[identity] = (value, snapshot)
            visits += 1
            if visits > _MAX_IR_VISITS:
                fail("Image.unmix input graph exceeds the bounded Pixel work limit")
            continue
        if leaving:
            active.remove(identity)
            complete.add(identity)
            continue
        if identity in active:
            fail("Image.unmix input graph contains cyclic Pixel operands")
        if identity in complete:
            continue
        _retain(value, retained)
        if kind is tuple:
            children = value
        elif kind is Pixel:
            if (type(value.args) is not tuple or type(value.op) is not str
                    or type(value.boolean) is not bool):
                fail("Image.unmix input graph contains malformed Pixel operands")
            if value.op == "clip" and len(value.args) != 2:
                fail("Image.unmix input graph contains malformed clip operands")
            children = value.args
        elif kind is Source:
            if (type(value.cid) is not str or type(value.ids) is not tuple
                    or type(value.names) is not tuple or type(value.alias) is not bool):
                fail("Image.unmix input graph contains malformed source operands")
            charge_array(graph.t, 8)
            children = (value.cid, value.ids, value.names, value.alias)
        else:
            fail("Image.unmix requires bounded acyclic Pixel operands")
        if len(children) > _MAX_IR_VISITS - visits:
            fail("Image.unmix input graph exceeds the bounded Pixel work limit")
        edges += len(children)
        if edges > _MAX_IR_VISITS:
            fail("Image.unmix input graph exceeds the bounded Pixel work limit")
        charge_array(graph.t, 2 * len(children))
        active.add(identity)
        stack.append((value, True, depth, False))
        stack.extend(
            (child, False, depth + 1,
             kind is Pixel and value.op == "clip" and index == 1)
            for index, child in reversed(tuple(enumerate(children)))
        )

    memo = {}
    snapshot_active = set()

    def freeze(value, depth=0, geometry_slot=False):
        if depth > _MAX_IR_DEPTH:
            fail("Image.unmix input graph exceeds the bounded Pixel depth limit")
        kind = type(value)
        if kind in (type(None), bool, int, str, bytes):
            return (kind.__name__, value)
        if kind is float:
            return ("float", struct.pack(">d", value))
        identity = id(value)
        if geometry_slot:
            entry = geometries.get(identity)
            if entry is None or entry[0] is not value:
                fail("Image.unmix input graph has an unvalidated clip geometry")
            return entry[1]
        if identity in snapshot_active:
            fail("Image.unmix input graph contains cyclic Pixel operands")
        cached = memo.get(identity)
        if cached is not None and cached[0] is value:
            return ("ref", kind.__name__, identity)
        snapshot_active.add(identity)
        if kind is Pixel:
            children = tuple(
                freeze(child, depth + 1, value.op == "clip" and index == 1)
                for index, child in enumerate(value.args)
            )
            result = ("pixel", identity, value.op, value.boolean, children)
        elif kind is Source:
            result = ("source", identity, value.cid, value.ids,
                      value.names, value.alias)
        elif kind is tuple:
            result = ("tuple", identity, tuple(
                freeze(child, depth + 1) for child in value
            ))
        else:
            fail("Image.unmix input graph requires bounded acyclic Pixel operands")
        snapshot_active.remove(identity)
        memo[identity] = (value, result)
        return result

    fingerprint = freeze(operands)
    return fingerprint, tuple(retained.values())
