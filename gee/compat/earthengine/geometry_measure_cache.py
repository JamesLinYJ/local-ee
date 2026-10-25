"""Request-local immutable component proofs and successful measure results."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import struct

from .geometry_preflight import _charge, measure_geometry
from .geometry_values import GeometryValue


MAX_ENTRIES = 64
MAX_RETAINED_BYTES = 1_000_000
MAX_RESULTS = 8
ABSENT = object()
_DEPTHS = {"Point": 0, "MultiPoint": 1, "LineString": 1, "LinearRing": 1,
           "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}


@dataclass(frozen=True)
class Entry:
    key: tuple
    key_hash: int
    key_work: int
    models: tuple | None = None
    component: tuple | None = None
    component_cost: object = None
    component_native: bool = False
    results: tuple = ()
    retained_bytes: int = 0


@dataclass
class Cache:
    buckets: dict
    entries: int = 0
    retained_bytes: int = 0


@dataclass(frozen=True)
class Ticket:
    cache: Cache
    entry: Entry
    existing: bool


def _scalar(value):
    kind = type(value)
    if kind is float:
        return ("float", struct.pack(">d", value))
    if kind in (bool, int, str) or value is None:
        return (kind.__name__, value)
    raise TypeError("Unsupported geometry snapshot scalar")


def _crs(value):
    if value is None or type(value) is str and value == "EPSG:4326":
        return _scalar(value)
    if (type(value) is not dict or set(value) != {"type", "properties"}
            or type(value["type"]) is not str or value["type"] != "name"):
        raise TypeError("Unsupported geometry snapshot CRS")
    properties = value["properties"]
    if (type(properties) is not dict or set(properties) != {"name"}
            or type(properties["name"]) is not str
            or properties["name"] != "EPSG:4326"):
        raise TypeError("Unsupported geometry snapshot CRS")
    return ("dict", (("type", _scalar("name")), ("properties",
            ("dict", (("name", _scalar("EPSG:4326")),), None))), None)


def _options(value):
    if type(value) is not dict or len(value) > 3:
        raise TypeError("Unsupported geometry snapshot metadata")
    items = []
    for key, child in value.items():
        if key == "crs":
            child = _crs(child)
        elif key in ("geodesic", "evenOdd") and type(child) is bool:
            child = _scalar(child)
        else:
            raise TypeError("Unsupported geometry snapshot metadata")
        items.append((key, child))
    return ("dict", tuple(items), None)


def _coordinates(value, depth):
    # measure_geometry bounds container recursion, but deliberately does not
    # descend into numeric slots. Never recursively freeze an untrusted slot.
    if depth == 0:
        frozen = []
        for index, number in enumerate(value):
            if (type(number) not in (int, float) or not math.isfinite(number)
                    or not (-180 if index == 0 else -90) <= number
                    <= (180 if index == 0 else 90)):
                raise TypeError("Unsupported geometry snapshot coordinate")
            frozen.append(_scalar(number))
        return (type(value).__name__, tuple(frozen))
    return (type(value).__name__, tuple(_coordinates(child, depth - 1) for child in value))


def _freeze(value):
    """Snapshot only the measured geometry schema, including exact sidecars."""
    kind = type(value)
    if kind not in (dict, GeometryValue):
        raise TypeError("Unsupported geometry snapshot mapping")
    geometry_type = value["type"]
    items = []
    for key, child in value.items():
        if key == "type":
            child = _scalar(child)
        elif key == "geometries":
            child = (type(child).__name__, tuple(_freeze(item) for item in child))
        elif key == "coordinates":
            child = _coordinates(child, _DEPTHS[geometry_type])
        elif key == "crs":
            child = _crs(child)
        elif type(child) is bool:
            child = _scalar(child)
        else:
            raise TypeError("Unsupported geometry snapshot metadata")
        items.append((key, child))
    metadata = _options(value.geometry_metadata) if kind is GeometryValue else None
    return ("geometry" if kind is GeometryValue else "dict", tuple(items), metadata)


def _thaw(value):
    kind = value[0]
    if kind == "float":
        return struct.unpack(">d", value[1])[0]
    if kind in ("bool", "int", "str", "NoneType"):
        return value[1]
    if kind in ("list", "tuple"):
        result = [_thaw(child) for child in value[1]]
        return tuple(result) if kind == "tuple" else result
    result = {key: _thaw(child) for key, child in value[1]}
    if kind == "geometry":
        return GeometryValue(result, _thaw(value[2]), validated=True)
    return result


def lookup(translator, raw, *, create=False):
    """Fresh content is the only key; callback identity and markers are unused."""
    cache = getattr(translator, "_geometry_measure_cache", None)
    if cache is None:
        if not create:
            return None
        cache = Cache({})
        translator._geometry_measure_cache = cache
    if type(raw) not in (dict, GeometryValue):
        return None
    from .geometry_snapshot import snapshot

    key = snapshot(translator, raw)
    if key is None:
        return None
    work = len(key)
    _charge(translator, work, "Geometry cache snapshot hash")
    key_hash = hash(key)
    for entry in cache.buckets.get(key_hash, ()):
        _charge(translator, work, "Geometry cache exact snapshot comparison")
        if entry.key == key:
            return Ticket(cache, entry, True)
    return Ticket(cache, Entry(key, key_hash, work,
                              retained_bytes=128 * work), False)


def _store(translator, ticket, entry, *, precharged=False):
    cache = ticket.cache
    previous_size = ticket.entry.retained_bytes if ticket.existing else 0
    feature = getattr(translator, "_feature_preflight_cache", None)
    retained = cache.retained_bytes - previous_size + entry.retained_bytes
    total_retained = retained + (feature.retained_bytes if feature else 0)
    total_entries = cache.entries + (feature.entries if feature else 0)
    bucket = cache.buckets.get(entry.key_hash, ())
    work = 2 + len(entry.results) + len(bucket) * (1 + (0 if ticket.existing else entry.key_work))
    if (not ticket.existing and total_entries >= MAX_ENTRIES
            or total_retained > MAX_RETAINED_BYTES
            or not precharged and translator.steps + work > 50_000):
        return
    if not precharged:
        _charge(translator, work, "Geometry cache immutable entry store")
    if ticket.existing:
        for index, previous in enumerate(bucket):
            if previous is ticket.entry:
                bucket[index] = entry
                cache.retained_bytes = retained
                return
        return  # A stale ticket never overwrites a newer successful proof.
    if any(previous.key == entry.key for previous in bucket):
        return
    cache.buckets.setdefault(entry.key_hash, []).append(entry)
    cache.entries += 1
    cache.retained_bytes = retained


def store_component(translator, ticket, geometry, native):
    """Admit only after the complete component validator succeeded."""
    if ticket is None or ticket.entry.component is not None:
        return
    from .geometry_topology import geometry_edge_models

    # Normalization adds bounded closures and three scalar sidecar options.
    upper_nodes = 16 * ticket.entry.key_work
    if translator.steps + 4 * upper_nodes + 16 > 50_000:
        return
    cost = measure_geometry(geometry)
    _charge(translator, 2 * cost.nodes + cost.positions + cost.geometries,
            "Geometry cache validated component snapshot")
    frozen = _freeze(geometry)
    models = tuple(geometry_edge_models(geometry))
    entry = replace(ticket.entry, component=frozen, component_cost=cost,
                    component_native=native, models=models,
                    retained_bytes=ticket.entry.retained_bytes + 256 * cost.nodes)
    _store(translator, ticket, entry)


def restore_component(translator, ticket):
    entry = ticket.entry
    if entry.component is None:
        return None
    cost = entry.component_cost
    _charge(translator, cost.nodes + cost.positions + cost.geometries,
            "Geometry cache fresh component copy")
    if entry.component_native:
        from .spherical_native import _load

        _load()
    return _thaw(entry.component), cost, entry.models


def cached_result(translator, ticket, route, method):
    if ticket is None:
        return ABSENT
    _charge(translator, len(ticket.entry.results), "Geometry cache result lookup")
    for item in ticket.entry.results:
        if item[:2] == (route, method):
            return item[2:]
    return ABSENT


def reserve_result(translator, ticket):
    """Reserve actual immutable result allocation before any numeric kernel."""
    if ticket is None or len(ticket.entry.results) >= MAX_RESULTS:
        return None
    entry, cache = ticket.entry, ticket.cache
    added_size = 128 + (0 if ticket.existing else entry.retained_bytes)
    feature = getattr(translator, "_feature_preflight_cache", None)
    total_entries = cache.entries + (feature.entries if feature else 0)
    total_retained = cache.retained_bytes + (feature.retained_bytes if feature else 0)
    bucket = cache.buckets.get(entry.key_hash, ())
    work = 4 + 3 + len(entry.results) + len(bucket) * (1 + (0 if ticket.existing else entry.key_work))
    if (not ticket.existing and total_entries >= MAX_ENTRIES
            or total_retained + added_size > MAX_RETAINED_BYTES
            or translator.steps + work > 50_000):
        return None
    _charge(translator, work, "Geometry cache result snapshot and store reservation")
    return ticket


def store_result(translator, ticket, route, method, result, models, native):
    """Admit a prepaid result only after the selected kernel/output succeeds."""
    if ticket is None:
        return
    if method == "centroid":
        result = tuple(result["coordinates"])
    results = ticket.entry.results + ((route, method, result, native),)
    _store(translator, ticket, replace(
        ticket.entry, models=models, results=results,
        retained_bytes=ticket.entry.retained_bytes + 128,
    ), precharged=True)
