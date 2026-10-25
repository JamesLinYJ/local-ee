"""Owned structure and flag accessors for validated local geometries."""
from __future__ import annotations

from .geometry_preflight import (
    GEOMETRY_TYPES,
    MAX_GEOMETRY_WORK,
)
from .ir import fail


GEOMETRY_STRUCTURE_ARGUMENTS = {
    f"Geometry.{method}": (frozenset({"geometry"}), frozenset())
    for method in (
        "coordinates", "edgesAreGeodesics", "geodesic", "geometries",
        "isUnbounded", "type",
    )
}
GEOMETRY_STRUCTURE_FUNCTIONS = frozenset(GEOMETRY_STRUCTURE_ARGUMENTS)


def _geometry_kind(translator, name, arguments):
    required, optional = GEOMETRY_STRUCTURE_ARGUMENTS[name]
    translator.allowed(arguments, required | optional)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires arguments: {sorted(missing)}")
    geometry = arguments["geometry"]
    if not isinstance(geometry, dict):
        fail(f"{name} requires a finite local Geometry value")
    from .geometry_components import decode_component_geometry_bounded

    # GeometryValue is mutable (including its nested coordinate lists), so a
    # previous decode marker cannot prove that a later direct-IR value remains
    # valid. Revalidate and detach each accessor input under the shared budget.
    geometry = decode_component_geometry_bounded(translator, geometry)
    kind = geometry.get("type")
    if type(kind) is not str or kind not in GEOMETRY_TYPES:
        fail(f"{name} requires a supported GeoJSON geometry")
    return geometry, kind


def _charge_scalar_inspection(translator, label):
    steps = getattr(translator, "steps", None)
    if type(steps) is not int or steps + 1 > MAX_GEOMETRY_WORK:
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + 1


def invoke_geometry_structure(translator, name, arguments):
    """Evaluate one structure accessor without borrowing mutable input data."""
    if name not in GEOMETRY_STRUCTURE_ARGUMENTS:
        fail(f"Unsupported geometry structure operation: {name}")
    geometry, kind = _geometry_kind(translator, name, arguments)
    if name == "Geometry.type":
        _charge_scalar_inspection(translator, name)
        return kind
    if name == "Geometry.isUnbounded":
        _charge_scalar_inspection(translator, name)
        return False
    if name in {"Geometry.geodesic", "Geometry.edgesAreGeodesics"}:
        _charge_scalar_inspection(translator, name)
        from .geometry_values import effective_geometry_geodesic

        value = effective_geometry_geodesic(geometry)
        if type(value) is not bool:
            fail("Geometry geodesic must be a boolean")
        return value

    if name == "Geometry.coordinates":
        if kind == "GeometryCollection":
            fail("GeometryCollection has no GeoJSON coordinates field")
        return geometry["coordinates"]
    if kind == "GeometryCollection":
        return geometry["geometries"]
    _charge_scalar_inspection(translator, name + " output list")
    return [geometry]
