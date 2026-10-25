"""Atomic GEOS measures that preserve original component multiplicity."""
from __future__ import annotations

import math

from .ir import fail


PLANAR_WORK_PER_NODE = 2
PLANAR_WORK_PER_POSITION = 6
PLANAR_WORK_PER_GEOMETRY = 4
PLANAR_WORK_PER_RING = 6


def _iter_planar_components(value, inherited_even_odd=None):
    """Yield atomic GEOS inputs, preserving multi-part multiplicity."""
    from .geometry_topology import _interior_rule

    kind = value["type"]
    even_odd = _interior_rule(value, inherited_even_odd)
    if kind == "GeometryCollection":
        for child in value["geometries"]:
            yield from _iter_planar_components(child, even_odd)
    elif kind == "Point":
        yield {"type": "Point", "coordinates": value["coordinates"]}, 0
    elif kind == "MultiPoint":
        for point in value["coordinates"]:
            yield {"type": "Point", "coordinates": point}, 0
    elif kind in {"LineString", "LinearRing"}:
        yield {"type": kind, "coordinates": value["coordinates"]}, 1
    elif kind == "MultiLineString":
        for line in value["coordinates"]:
            yield {"type": "LineString", "coordinates": line}, 1
    elif kind == "Polygon":
        if even_odd is False:
            fail("Planar Geometry evenOdd=false left-inside interiors are unsupported")
        yield {"type": "Polygon", "coordinates": value["coordinates"]}, 2
    elif kind == "MultiPolygon":
        if even_odd is False:
            fail("Planar Geometry evenOdd=false left-inside interiors are unsupported")
        for polygon in value["coordinates"]:
            yield {"type": "Polygon", "coordinates": polygon}, 2


def planar_components(geometry, label):
    """Validate atomic inputs without rejecting cross-component overlap."""
    from shapely.errors import GEOSException
    from shapely.geometry import shape

    components = []
    try:
        for mapping, dimension in _iter_planar_components(geometry):
            component = shape(mapping)
            if not component.is_valid:
                fail(f"{label} contains an invalid planar component")
            if not component.is_empty:
                components.append((dimension, component))
    except (GEOSException, TypeError, ValueError) as error:
        fail(f"{label} planar component validation failed: {error}")
    return components


def planar_result(components, method, label):
    """Calculate a public planar metric or weighted highest-dimension centroid."""
    if method != "centroid":
        if method == "area":
            value = sum(float(component.area) for dimension, component in components
                        if dimension == 2)
        elif method == "length":
            value = sum(float(component.length) for dimension, component in components
                        if dimension == 1)
        else:
            value = sum(float(component.length) for dimension, component in components
                        if dimension == 2)
        if not math.isfinite(value) or value < 0:
            fail(f"{label} produced a non-finite planar measure")
        return value

    if not components:
        fail("Geometry.centroid has no highest-dimension component")
    dimension = max(item[0] for item in components)
    selected = [(component, float(component.area if dimension == 2 else
                                  component.length if dimension == 1 else 1.0))
                for kind, component in components if kind == dimension]
    weight = sum(item[1] for item in selected)
    if not math.isfinite(weight) or weight <= 0:
        fail("Geometry.centroid has no positive highest-dimension measure")
    x = sum(float(component.centroid.x) * component_weight
            for component, component_weight in selected) / weight
    y = sum(float(component.centroid.y) * component_weight
            for component, component_weight in selected) / weight
    if not math.isfinite(x) or not math.isfinite(y):
        fail(f"{label} produced a non-finite planar point")
    return x, y
