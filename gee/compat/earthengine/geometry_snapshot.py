"""Single-pass, schema-bounded immutable geometry content snapshots."""
from __future__ import annotations

import math
import struct

from .geometry_preflight import (
    GEOMETRY_TYPES, MAX_GEOMETRY_CHILDREN, MAX_GEOMETRY_COORDINATES,
    MAX_GEOMETRY_DEPTH, _charge,
)
from .geometry_values import GeometryValue
from .ir import fail

_DEPTHS = {"Point": 0, "MultiPoint": 1, "LineString": 1, "LinearRing": 1,
           "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}


def snapshot(translator, value):
    """Freeze exact coordinate types/bits, field presence and every sidecar.

    The traversal never recursively explores coordinate scalars or unknown
    metadata forms. Every emitted token is reserved before allocation; the
    caller separately reserves hashing, equality and retained copies.
    """
    active = set()
    positions = 0

    def emit(token):
        _charge(translator, 1, "Geometry cache snapshot token")
        yield token

    def enter(raw):
        identity = id(raw)
        if identity in active:
            fail("Geometry snapshot contains a cycle")
        active.add(identity)
        return identity

    def crs(raw):
        if raw is None:
            yield from emit("null-crs")
        elif type(raw) is str and raw == "EPSG:4326":
            yield from emit("string-crs")
        elif type(raw) is dict and len(raw) == 2 and set(raw) == {"type", "properties"}:
            properties = raw["properties"]
            if (type(raw["type"]) is not str or raw["type"] != "name"
                    or type(properties) is not dict or len(properties) != 1
                    or set(properties) != {"name"}
                    or type(properties["name"]) is not str
                    or properties["name"] != "EPSG:4326"):
                raise TypeError("Unsupported CRS snapshot")
            yield from emit("named-crs")
        else:
            raise TypeError("Unsupported CRS snapshot")

    def options(raw):
        if type(raw) is not dict or len(raw) > 3:
            raise TypeError("Unsupported metadata snapshot")
        if any(type(key) is not str or key not in {"crs", "geodesic", "evenOdd"}
               for key in raw):
            raise TypeError("Unsupported metadata snapshot")
        yield from emit(sum(1 << index for index, key in enumerate(("crs", "geodesic", "evenOdd"))
                 if key in raw))
        for key in ("crs", "geodesic", "evenOdd"):
            if key not in raw:
                continue
            if key == "crs":
                yield from crs(raw[key])
            elif type(raw[key]) is bool:
                yield from emit(raw[key])
            else:
                raise TypeError("Unsupported metadata snapshot")

    def coordinates(raw, depth, *, empty=False):
        nonlocal positions
        if type(raw) not in (list, tuple) or len(raw) > MAX_GEOMETRY_COORDINATES:
            raise TypeError("Unsupported coordinate snapshot")
        identity = enter(raw)
        try:
            yield from emit(2 * len(raw) + (type(raw) is tuple))
            if depth == 0:
                if len(raw) != 2:
                    raise TypeError("Unsupported position snapshot")
                positions += 1
                if positions > MAX_GEOMETRY_COORDINATES:
                    fail("Geometry exceeds 10000 coordinate positions")
                for index, number in enumerate(raw):
                    if (type(number) not in (int, float) or not math.isfinite(number)
                            or not (-180 if index == 0 else -90) <= number
                            <= (180 if index == 0 else 90)):
                        raise TypeError("Unsupported coordinate snapshot")
                    # Reserve before struct.pack/to_bytes allocates numeric bits.
                    _charge(translator, 1, "Geometry cache numeric snapshot")
                    yield (b"f" + struct.pack(">d", number) if type(number) is float
                           else b"i" + number.to_bytes(2, "big", signed=True))
            else:
                if not raw and not empty:
                    raise TypeError("Unsupported empty coordinate snapshot")
                for child in raw:
                    yield from coordinates(child, depth - 1)
        finally:
            active.remove(identity)

    def geometry(raw, depth):
        if depth > MAX_GEOMETRY_DEPTH:
            fail("Geometry collection nesting exceeds 16 levels")
        if type(raw) not in (dict, GeometryValue) or len(raw) > 5:
            raise TypeError("Unsupported geometry snapshot")
        identity = enter(raw)
        try:
            kind = raw.get("type")
            if type(kind) is not str or kind not in GEOMETRY_TYPES:
                raise TypeError("Unsupported geometry snapshot type")
            field = "geometries" if kind == "GeometryCollection" else "coordinates"
            if (field not in raw or any(type(key) is not str
                    or key not in {"type", field, "crs", "geodesic", "evenOdd"}
                    for key in raw)):
                raise TypeError("Unsupported geometry snapshot fields")
            yield from emit("geometry" if type(raw) is GeometryValue else "dict")
            yield from emit(kind)
            # Option extraction is bounded by the five-field geometry schema.
            _charge(translator, 3, "Geometry cache public option scan")
            yield from options({key: raw[key] for key in ("crs", "geodesic", "evenOdd") if key in raw})
            if type(raw) is GeometryValue:
                yield from options(raw.geometry_metadata)
            if kind == "GeometryCollection":
                children = raw[field]
                if type(children) not in (list, tuple) or len(children) > MAX_GEOMETRY_CHILDREN:
                    raise TypeError("Unsupported collection snapshot")
                yield from emit(2 * len(children) + (type(children) is tuple))
                child_identity = enter(children)
                try:
                    for child in children:
                        yield from geometry(child, depth + 1)
                finally:
                    active.remove(child_identity)
            else:
                yield from coordinates(raw[field], _DEPTHS[kind], empty=kind in {
                    "MultiPoint", "MultiLineString", "MultiPolygon",
                })
        finally:
            active.remove(identity)

    try:
        return tuple(geometry(value, 0))
    except (TypeError, OverflowError):
        return None  # The ordinary decoder retains its original error/domain.
