"""Atomic planar validity for component-preserving EE geometry values.

Callers first bound and structurally validate coordinates, nesting and models,
and reserve their work. This module never grants topology-operation readiness:
individually valid polygons may overlap, repeat or share complete edges.
"""
from __future__ import annotations

import math

from shapely.errors import GEOSException
from shapely.geometry import shape


class PlanarGeometryError(ValueError):
    """An individual planar geometry component is invalid."""


def _atomic_mappings(value):
    kind = value.get("type")
    if kind == "GeometryCollection":
        for child in value["geometries"]:
            yield from _atomic_mappings(child)
    elif kind == "MultiPolygon":
        for polygon in value["coordinates"]:
            # Validate each complete shell with all its holes. Treating rings
            # independently would accept outside/intersecting holes.
            yield {"type": "Polygon", "coordinates": polygon}
    else:
        yield value


def planar_component_bounds(value):
    """Validate bounded planar atoms and return their coordinate envelope.

    No overlays, topology repair, normalization, or mutation occurs here.
    Coordinate/geodesic/evenOdd policy and resource limits belong to callers.
    Empty components contribute nothing to the envelope.
    """
    bounds = None
    try:
        for mapping in _atomic_mappings(value):
            component = shape(mapping)
            if not component.is_valid:
                raise PlanarGeometryError("Invalid planar geometry component topology")
            if component.is_empty:
                continue
            current = tuple(component.bounds)
            if len(current) != 4 or not all(math.isfinite(number) for number in current):
                raise PlanarGeometryError("Planar geometry component has non-finite bounds")
            if bounds is None:
                bounds = current
            else:
                west, south, east, north = bounds
                bounds = (min(west, current[0]), min(south, current[1]),
                          max(east, current[2]), max(north, current[3]))
    except (GEOSException, TypeError, KeyError, AttributeError) as error:
        raise PlanarGeometryError("Invalid planar geometry component") from error
    except ValueError as error:
        if isinstance(error, PlanarGeometryError):
            raise
        raise PlanarGeometryError("Invalid planar geometry component") from error
    return bounds
