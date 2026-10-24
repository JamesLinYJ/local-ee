"""Spherical geometry checks for bounded literal FeatureCollection exports."""
from __future__ import annotations

from typing import Any

from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.geometry_public import (
    public_geometry_mapping as _public_geometry_mapping,
)
from gee.compat.earthengine import spherical_native
from gee.compat.earthengine.spherical_preflight import native_work
from gee.table_geometry import TableGeometryError


MAX_SPHERICAL_TABLE_WORK = 50_000


def _sidecar(value: Any) -> dict[str, Any]:
    from gee.compat.earthengine.geometry_values import GeometryValue, _geometry_metadata

    if type(value) is not GeometryValue:
        return {}
    try:
        metadata = _geometry_metadata(value)
    except UnsupportedEEError as exc:
        raise TableGeometryError(str(exc)) from exc
    return metadata


def _flag(value: dict[str, Any], name: str, inherited: bool | None) -> bool | None:
    if name in value:
        flag = value[name]
    elif inherited is not None:
        return inherited
    else:
        flag = _sidecar(value).get(name)
    if flag is not None and type(flag) is not bool:
        raise TableGeometryError(f"GeoJSON geometry {name} must be boolean")
    return flag


def spherical_model(value: dict[str, Any], inherited: bool | None) -> bool | None:
    """Resolve public flags, collection inheritance, and typed EE defaults."""
    return _flag(value, "geodesic", inherited)


def even_odd_model(value: dict[str, Any], inherited: bool | None) -> bool:
    result = _flag(value, "evenOdd", inherited)
    return True if result is None else result


def needs_model_aware_validation(value: Any, *, depth: int = 0) -> bool:
    """Detect typed sidecars and public EE edge/interior flags recursively."""
    from gee.compat.earthengine.geometry_values import GeometryValue

    if depth > 16 or not isinstance(value, dict):
        return False
    if type(value) is GeometryValue or any(key in value for key in ("geodesic", "evenOdd")):
        return True
    if value.get("type") == "GeometryCollection":
        children = value.get("geometries")
        return type(children) is list and any(
            needs_model_aware_validation(child, depth=depth + 1) for child in children
        )
    return False


def reserve_spherical_table_work(components: list[tuple[Any, bool]]) -> int:
    """Precharge every pending S2 call using the exact C ABI work equation."""
    total = 0
    for geometry, _even_odd in components:
        work = native_work(geometry)
        if work > MAX_SPHERICAL_TABLE_WORK or total + work > MAX_SPHERICAL_TABLE_WORK:
            raise TableGeometryError(
                "Spherical FeatureCollection validation exceeds the shared 50000-step table work budget"
            )
        total += work
    return total


def validate_spherical_component(geometry: dict[str, Any], even_odd: bool) -> None:
    """Pass effective EE flags explicitly to the pinned local S2 bridge."""
    mapping = dict(geometry)
    mapping["geodesic"] = True
    mapping["evenOdd"] = even_odd
    try:
        spherical_native.validate(mapping)
    except UnsupportedEEError as exc:
        raise TableGeometryError(str(exc)) from exc


def public_geometry_mapping(
    value: Any,
    *,
    inherited_geodesic: bool | None = None,
    inherited_even_odd: bool | None = None,
) -> Any:
    """Compatibility wrapper for the shared EE public geometry mapping."""
    try:
        return _public_geometry_mapping(
            value,
            inherited_geodesic=inherited_geodesic,
            inherited_even_odd=inherited_even_odd,
        )
    except UnsupportedEEError as exc:
        raise TableGeometryError(str(exc)) from exc
