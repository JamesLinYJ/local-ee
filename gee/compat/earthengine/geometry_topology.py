"""Geometry-model resolution, bounded validation routing, and work reservation."""
from __future__ import annotations

from .geometry_preflight import MAX_GEOMETRY_WORK, measure_geometry
from .geometry_values import _geometry_metadata
from .ir import fail


def reserve_spherical_validation(translator, value, *, cost=None):
    """Reserve local compiler work before calling the native S2 validator."""
    from .spherical_preflight import native_work

    cost = cost or measure_geometry(value)
    closed_positions = cost.positions + cost.ring_closures
    amount = 1 + cost.nodes + 4 * closed_positions + native_work(value)
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or amount < 0 or amount > MAX_GEOMETRY_WORK
            or steps + amount > MAX_GEOMETRY_WORK):
        fail("Spherical geometry validation exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount
    return amount


def component_model(value, inherited=None):
    """Return effective edge model (True=spherical, False=planar, None=mixed)."""
    kind = value.get("type")
    model = _edge_model(value, inherited)
    if kind != "GeometryCollection":
        return model
    children = value.get("geometries", [])
    edge_children = [child for child in children if _has_edges(child)]
    if not edge_children:
        return True if model is None else model
    child_models = [component_model(child, model) for child in edge_children]
    if any(item is None for item in child_models) or len(set(child_models)) != 1:
        return None
    child_model = child_models[0]
    # A collection flag supplies an inherited default, but an explicitly
    # conflicting child flag must not make a mixed tree look homogeneous.
    if model is not None and child_model is not model:
        return None
    return child_model if model is None else model


def _edge_model(value, inherited=None):
    """Resolve literal flag, inherited collection default, then sidecar."""
    if "geodesic" in value:
        return value["geodesic"]
    if inherited is not None:
        return inherited
    return _geometry_metadata(value).get("geodesic")


def _has_edges(value):
    """Return whether the component contains at least one actual edge."""
    kind = value.get("type")
    if kind == "GeometryCollection":
        return any(_has_edges(child) for child in value.get("geometries", []))
    if kind in {"Point", "MultiPoint"}:
        return False
    coordinates = value.get("coordinates", [])
    if kind in {"LineString", "LinearRing"}:
        return len(coordinates) >= 2
    if kind == "MultiLineString":
        return any(len(line) >= 2 for line in coordinates)
    if kind == "Polygon":
        return any(len(ring) >= 2 for ring in coordinates)
    if kind == "MultiPolygon":
        return any(len(ring) >= 2 for polygon in coordinates for ring in polygon)
    return False


def geometry_edge_models(value, inherited=None):
    """Yield effective models of actual edge leaves after bounded decoding."""
    from .spherical_wire import FullSphere

    if isinstance(value, FullSphere):
        yield True
        return
    model = _edge_model(value, inherited)
    if value["type"] == "GeometryCollection":
        for child in value["geometries"]:
            yield from geometry_edge_models(child, model)
    elif _has_edges(value):
        yield model


def common_edge_model(*values):
    """Resolve a homogeneous model without treating points as curved edges.

    Callers own fresh validated input and reserve this complete model walk
    before entering it. This helper neither transforms nor relabels geometry.
    """
    result = None
    for value in values:
        for model in geometry_edge_models(value):
            if type(model) is not bool:
                fail("Geometry edge model is unresolved")
            if result is not None and model is not result:
                fail("Mixed geodesic edge models require unsupported reprojection")
            result = model
    return True if result is None else result


def effective_geometry_geodesic(value):
    """Return a scalar effective edge flag, rejecting mixed collections."""
    model = component_model(value)
    if model is None:
        fail("GeometryCollection has mixed geodesic edge models")
    return model


def contains_spherical_component(value, inherited=None):
    """Check recursively so mixed collections never make the whole tree GEOS input."""
    kind = value.get("type")
    model = _edge_model(value, inherited)
    if kind == "GeometryCollection":
        children = value.get("geometries", [])
        if not children:
            return component_model(value, inherited) is True
        return any(contains_spherical_component(child, model) for child in children)
    return model is True


def _has_planar_left_inside(value, inherited_geodesic=None, inherited_even_odd=None):
    kind = value.get("type")
    metadata = _geometry_metadata(value)
    geodesic = value.get("geodesic", inherited_geodesic)
    if geodesic is None:
        geodesic = metadata.get("geodesic")
    even_odd = value.get("evenOdd", inherited_even_odd)
    if even_odd is None:
        even_odd = metadata.get("evenOdd", True)
    if kind == "GeometryCollection":
        return any(_has_planar_left_inside(child, geodesic, even_odd)
                   for child in value.get("geometries", []))
    return kind in {"Polygon", "MultiPolygon"} and geodesic is False and even_odd is False


def _interior_rule(value, inherited=None):
    if "evenOdd" in value:
        return value["evenOdd"]
    if inherited is not None:
        return inherited
    return _geometry_metadata(value).get("evenOdd")


def _validation_view(value, inherited_geodesic, inherited_even_odd):
    """Give a child native validation its inherited flags without mutating it."""
    if ((inherited_geodesic is None or "geodesic" in value)
            and (inherited_even_odd is None or "evenOdd" in value)):
        return value
    from .geometry_values import GeometryValue

    metadata = _geometry_metadata(value)
    if inherited_geodesic is not None and "geodesic" not in value:
        metadata["geodesic"] = inherited_geodesic
    if inherited_even_odd is not None and "evenOdd" not in value:
        metadata["evenOdd"] = inherited_even_odd
    return GeometryValue(value, metadata, validated=True)


def _validate_planar_geometry(value, inherited_geodesic=None, inherited_even_odd=None):
    from shapely.errors import GEOSException
    from shapely.geometry import shape

    if _has_planar_left_inside(value, inherited_geodesic, inherited_even_odd):
        fail("Planar Geometry evenOdd=false left-inside interiors are unsupported")
    try:
        geometry = shape(value)
    except (TypeError, ValueError, GEOSException) as error:
        fail(f"Invalid planar GeoJSON geometry: {error}")
    if not geometry.is_valid:
        fail("Invalid planar GeoJSON geometry topology")


def validate_geometry_topology(translator, value, inherited_geodesic=None,
                               inherited_even_odd=None):
    """Use S2 for spherical values and GEOS only for explicitly planar values."""
    kind = value.get("type")
    model = component_model(value, inherited_geodesic)
    if kind == "GeometryCollection" and model is None:
        # Mixed collections have no single topology model. Validate each child
        # against the parent's inherited default; later binary consumers must
        # reject the mixed tree or explicitly preserve each component model.
        inherited = _edge_model(value, inherited_geodesic)
        interior = _interior_rule(value, inherited_even_odd)
        for child in value.get("geometries", []):
            validate_geometry_topology(translator, child, inherited, interior)
        return
    if model is True:
        from . import spherical_native

        spherical_native.validate(_validation_view(
            value, inherited_geodesic, inherited_even_odd,
        ))
    else:
        _validate_planar_geometry(value, inherited_geodesic, inherited_even_odd)


# Private-name compatibility for callers that used the earlier value-module
# implementation. Keep the actual policy in this cohesive topology module.
_component_model = component_model
_contains_spherical_component = contains_spherical_component
_validate_geometry_topology = validate_geometry_topology
