"""Bounded geometry structure measurement and shared-work reservation."""
from __future__ import annotations

from dataclasses import dataclass

from .ir import fail


GEOMETRY_TYPES = frozenset({
    "Point", "MultiPoint", "LineString", "LinearRing", "MultiLineString",
    "Polygon", "MultiPolygon", "GeometryCollection",
})
MAX_GEOMETRY_COORDINATES = 10_000
MAX_GEOMETRY_CHILDREN = 1_000
MAX_GEOMETRY_DEPTH = 16
MAX_GEOMETRY_WORK = 50_000

_COORDINATE_DEPTH = {
    "Point": 0,
    "MultiPoint": 1,
    "LineString": 1,
    "LinearRing": 1,
    "MultiLineString": 2,
    "Polygon": 2,
    "MultiPolygon": 3,
}


@dataclass(frozen=True)
class GeometryCost:
    """A bounded count used before geometry validation or owned copies."""

    nodes: int
    positions: int
    geometries: int
    coordinate_arrays: int
    ring_closures: int


def measure_geometry(value) -> GeometryCost:
    """Count a finite inline GeoJSON tree without allocating normalized output.

    This pass bounds recursion and container visits, and detects Python object
    cycles before normalization, copying, or GEOS conversion. Numeric and
    topological validation remains in the decoder after work is reserved.
    """
    counts = {"nodes": 0, "positions": 0, "geometries": 0,
              "arrays": 0, "closures": 0}
    active = set()

    def add(name, amount=1):
        counts[name] += amount
        if counts["nodes"] > MAX_GEOMETRY_WORK:
            fail("Geometry exceeds the shared 50000-step compilation work budget")

    def enter(item, label):
        identity = id(item)
        if identity in active:
            fail(f"{label} contains a cycle")
        active.add(identity)
        return identity

    def coordinates(raw, depth):
        if type(raw) not in (list, tuple):
            fail("Geometry coordinate arrays must be lists")
        if len(raw) > MAX_GEOMETRY_COORDINATES:
            fail("Geometry exceeds 10000 coordinate positions")
        identity = enter(raw, "Geometry coordinates")
        try:
            add("nodes", 1)
            if depth == 0:
                if len(raw) != 2:
                    fail("Geometry coordinates must be finite two-dimensional positions")
                add("positions")
                if counts["positions"] > MAX_GEOMETRY_COORDINATES:
                    fail("Geometry exceeds 10000 coordinate positions")
                add("nodes", len(raw))
                return
            if not raw:
                fail("Geometry coordinate arrays must be nonempty")
            add("arrays")
            add("nodes", len(raw))
            for child in raw:
                coordinates(child, depth - 1)
        finally:
            active.remove(identity)

    def metadata(raw):
        options = getattr(raw, "geometry_metadata", None)
        if options is None:
            return
        if type(options) is not dict or len(options) > 3:
            fail("Geometry constructor metadata is malformed")
        identity = enter(options, "Geometry metadata")
        try:
            add("nodes", 1 + len(options))
            for key, value in options.items():
                if type(key) is not str or key not in {"crs", "geodesic", "evenOdd"}:
                    fail("Geometry constructor metadata is malformed")
                add("nodes", len(key) + 1)
                if key == "crs" and type(value) is dict:
                    if len(value) > 2:
                        fail("Geometry CRS must be an EPSG:4326 string or named GeoJSON CRS")
                    child_identity = enter(value, "Geometry CRS")
                    try:
                        add("nodes", 1 + len(value))
                        properties = value.get("properties")
                        if type(properties) is dict:
                            if len(properties) > 1:
                                fail("Geometry CRS must be an EPSG:4326 string or named GeoJSON CRS")
                            properties_identity = enter(properties, "Geometry CRS properties")
                            try:
                                add("nodes", 1 + len(properties))
                            finally:
                                active.remove(properties_identity)
                    finally:
                        active.remove(child_identity)
                elif key == "crs" and type(value) is str:
                    add("nodes", len(value))
                elif key == "crs" and value is not None:
                    fail("Geometry CRS must be an EPSG:4326 string or named GeoJSON CRS")
                elif key != "crs" and type(value) is not bool:
                    fail(f"Geometry {key} must be a boolean")
        finally:
            active.remove(identity)

    def geometry(raw, depth):
        if depth > MAX_GEOMETRY_DEPTH:
            fail("Geometry collection nesting exceeds 16 levels")
        if not isinstance(raw, dict):
            fail("Expected a supported GeoJSON geometry")
        if len(raw) > 5:
            fail("Unsupported GeoJSON geometry fields")
        identity = enter(raw, "Geometry collection")
        try:
            kind = raw.get("type")
            if type(kind) is not str or kind not in GEOMETRY_TYPES:
                fail("Expected a supported GeoJSON geometry")
            field = "geometries" if kind == "GeometryCollection" else "coordinates"
            fields = {"type", field, "crs", "geodesic", "evenOdd"}
            if any(key not in fields for key in raw):
                fail("Unsupported GeoJSON geometry fields")
            if field not in raw:
                fail("GeoJSON geometry is missing its coordinate field")
            add("geometries")
            add("nodes", 1 + len(raw))
            metadata(raw)
            if "crs" in raw and type(raw["crs"]) is dict:
                crs = raw["crs"]
                if len(crs) > 2:
                    fail("Geometry CRS must be an EPSG:4326 string or named GeoJSON CRS")
                add("nodes", 1 + len(crs))
                properties = crs.get("properties")
                if type(properties) is dict:
                    if len(properties) > 1:
                        fail("Geometry CRS must be an EPSG:4326 string or named GeoJSON CRS")
                    add("nodes", 1 + len(properties))
            if kind == "GeometryCollection":
                children = raw[field]
                if type(children) not in (list, tuple) or len(children) > MAX_GEOMETRY_CHILDREN:
                    fail("GeometryCollection requires at most 1000 inline geometries")
                add("nodes", len(children))
                if children:
                    list_identity = enter(children, "GeometryCollection")
                    try:
                        for child in children:
                            geometry(child, depth + 1)
                    finally:
                        active.remove(list_identity)
                return
            coordinate_values = raw[field]
            nesting = _COORDINATE_DEPTH[kind]
            empty_multi = (
                kind in {"MultiPoint", "MultiLineString", "MultiPolygon"}
                and type(coordinate_values) in (list, tuple)
                and len(coordinate_values) == 0
            )
            if empty_multi:
                return
            if kind == "MultiPolygon":
                if type(coordinate_values) not in (list, tuple) or not coordinate_values:
                    fail("MultiPolygon coordinates must be nonempty")
                if len(coordinate_values) > MAX_GEOMETRY_COORDINATES:
                    fail("Geometry exceeds 10000 coordinate positions")
                for polygon in coordinate_values:
                    if type(polygon) in (list, tuple):
                        counts["closures"] += len(polygon)
                coordinates(coordinate_values, nesting)
            else:
                if kind in {"Polygon", "LinearRing"}:
                    if type(coordinate_values) in (list, tuple):
                        counts["closures"] += (
                            len(coordinate_values) if kind == "Polygon" else 1
                        )
                coordinates(coordinate_values, nesting)
        finally:
            active.remove(identity)

    geometry(value, 0)
    return GeometryCost(
        nodes=counts["nodes"],
        positions=counts["positions"],
        geometries=counts["geometries"],
        coordinate_arrays=counts["arrays"],
        ring_closures=counts["closures"],
    )


def _charge(translator, amount, label):
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or amount < 0 or amount > MAX_GEOMETRY_WORK
            or steps + amount > MAX_GEOMETRY_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def precharge_geometry_decode(translator, value) -> GeometryCost:
    """Reserve validation, coordinate-copy, GEOS, and closure work once."""
    cost = measure_geometry(value)
    amount = cost.nodes + cost.positions + 3 * cost.ring_closures
    _charge(translator, amount, "Geometry decoding")
    return cost


def precharge_geometry_copy(
        translator, value, label="Geometry output", *,
        additional_geometry_walks=0) -> GeometryCost:
    """Reserve a measured owned copy and any complete geometry-tree passes."""
    if type(additional_geometry_walks) is not int or additional_geometry_walks < 0:
        fail("Geometry copy walk count must be a non-negative integer")
    cost = measure_geometry(value)
    amount = (
        cost.nodes + cost.geometries + cost.positions
        + additional_geometry_walks * cost.geometries
    )
    _charge(translator, amount, label)
    return cost
