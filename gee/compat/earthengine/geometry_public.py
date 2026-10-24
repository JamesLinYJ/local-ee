"""Public GeoJSON materialization for Earth Engine geometry values."""
from __future__ import annotations

from typing import Any

from .geometry_values import GeometryValue, _geometry_metadata
from .ir import fail


def _sidecar(value: Any) -> dict[str, Any]:
    if type(value) is not GeometryValue:
        return {}
    return _geometry_metadata(value)


def _flag(value: dict[str, Any], name: str, inherited: bool | None) -> bool | None:
    if name in value:
        flag = value[name]
    elif inherited is not None:
        flag = inherited
    else:
        flag = _sidecar(value).get(name)
    if flag is not None and type(flag) is not bool:
        fail(f"GeoJSON geometry {name} must be boolean")
    return flag


def public_geometry_mapping(
    value: Any,
    *,
    inherited_geodesic: bool | None = None,
    inherited_even_odd: bool | None = None,
) -> Any:
    """Materialize only constructor-supported EE flags before sidecars drop.

    Raw GeoJSON keeps its historical omissions. Typed ``GeometryValue``
    instances may contribute effective defaults from their metadata sidecar;
    inherited collection options are represented by the parent or supported
    polygon children according to the pinned SDK constructor signatures.
    """
    if not isinstance(value, dict):
        return value
    kind = value.get("type")
    if type(kind) is not str:
        return value

    geodesic = _flag(value, "geodesic", inherited_geodesic)
    even_odd = _flag(value, "evenOdd", inherited_even_odd)
    result = dict(value)
    result.pop("geodesic", None)
    result.pop("evenOdd", None)

    # The pinned SDK's constructors accept geodesic only for line and area
    # types, and evenOdd only for polygonal types. Point flags have no semantic
    # effect and become invalid constructor arguments if they are serialized.
    geodesic_supported = kind in {
        "LineString", "LinearRing", "MultiLineString", "Polygon",
        "MultiPolygon", "GeometryCollection",
    }
    even_odd_supported = kind in {"Polygon", "MultiPolygon"}
    if geodesic_supported and geodesic is not None:
        # An inherited collection flag is already represented by its parent.
        # Keep an explicit child override, but do not duplicate sidecar defaults.
        if "geodesic" in value or inherited_geodesic is None:
            result["geodesic"] = geodesic
    if even_odd_supported and even_odd is not None:
        # GeometryCollection has no evenOdd constructor parameter. Carry its
        # inherited interior rule to supported polygon children instead.
        result["evenOdd"] = even_odd

    if kind == "GeometryCollection":
        children = value.get("geometries")
        if type(children) is list:
            result["geometries"] = [
                public_geometry_mapping(
                    child,
                    inherited_geodesic=geodesic,
                    inherited_even_odd=even_odd,
                )
                for child in children
            ]
    return result
