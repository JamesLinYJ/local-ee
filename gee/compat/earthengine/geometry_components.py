"""Owned EE component geometry, distinct from strict aggregate topology."""
from __future__ import annotations

from .geometry_preflight import precharge_geometry_decode
from .ir import fail


def _validate_components(translator, value, inherited_geodesic=None,
                         inherited_even_odd=None):
    """Validate atomic planar polygons and retain the existing spherical policy."""
    from gee.planar_geometry_validation import (
        PlanarGeometryError,
        planar_component_bounds,
    )
    from .geometry_topology import (
        _edge_model,
        _has_planar_left_inside,
        _interior_rule,
        component_model,
        validate_geometry_topology,
    )

    model = component_model(value, inherited_geodesic)
    if value["type"] == "GeometryCollection" and model is None:
        inherited = _edge_model(value, inherited_geodesic)
        interior = _interior_rule(value, inherited_even_odd)
        for child in value["geometries"]:
            _validate_components(translator, child, inherited, interior)
    elif model is True:
        validate_geometry_topology(
            translator, value, inherited_geodesic, inherited_even_odd,
        )
    else:
        if _has_planar_left_inside(value, inherited_geodesic, inherited_even_odd):
            fail("Planar Geometry evenOdd=false left-inside interiors are unsupported")
        try:
            planar_component_bounds(value)
        except PlanarGeometryError as error:
            fail(f"Invalid planar GeoJSON geometry topology: {error}")


def decode_component_geometry_bounded(translator, value):
    """Normalize and freshly validate an EE geometry while preserving its parts.

    Overlap between individually valid MultiPolygon parts is meaningful to EE
    component measures. This does not prove validity for GEOS set operations;
    those consumers must continue using the strict geometry decoder.
    """
    from .geometry_topology import (
        contains_spherical_component,
        reserve_spherical_validation,
    )
    from .geometry_values import _attach_geometry_metadata, _normalize_geometry

    cost = precharge_geometry_decode(translator, value)
    normalized = _normalize_geometry(value)
    owned = _attach_geometry_metadata(value, normalized)
    if contains_spherical_component(owned):
        reserve_spherical_validation(translator, owned, cost=cost)
    _validate_components(translator, owned)
    return owned


def own_component_geometry_bounded(translator, value):
    """Return a fresh owned component value; mutable decode markers are ignored."""
    return decode_component_geometry_bounded(translator, value)
