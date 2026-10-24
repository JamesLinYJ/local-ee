"""Earth Engine geometry handling at service query and export boundaries."""
from __future__ import annotations

import json
import math

from ..compat.earthengine.decoder import Translator
from ..compat.earthengine.geometry_regions import own_ee_region
from ..compat.earthengine.geometry_values import GEOMETRY_TYPES
from ..compat.earthengine.ir import UnsupportedEEError
from ..compat.earthengine.spherical_wire import FullSphere


def geometry(value, catalog, items, *, include_bounds=False):
    """Own, validate, and bound one EE geometry before a GEOS operation.

    The EE wire's absent ``geodesic`` flag means spherical for edge-bearing
    geometries. This service currently uses GEOS for rectangular query/export
    bounds, so spherical edges must be rejected before GEOS can planarize them.
    Explicit planar inputs retain their model in the returned mapping.
    """
    translator = Translator(catalog, items, {})
    source = value
    if isinstance(source, str):
        try:
            source = json.loads(source)
        except json.JSONDecodeError as error:
            raise UnsupportedEEError(
                "Expected serialized Earth Engine JSON"
            ) from error

    direct_geojson = (
        isinstance(source, dict)
        and source.get("type") in GEOMETRY_TYPES | {"Feature"}
    )
    if direct_geojson:
        geo, result = own_ee_region(
            translator, source, "EE geometry region",
        )
    else:
        try:
            if len(json.dumps(source)) > 1_000_000:
                raise UnsupportedEEError(
                    "Serialized Earth Engine expression exceeds 1 MB"
                )
            decoded = translator.evaluate(source)
        except UnsupportedEEError:
            raise
        except (KeyError, IndexError, TypeError, AttributeError, ValueError,
                RecursionError, OverflowError) as error:
            raise UnsupportedEEError(
                f"Malformed or unsupported Earth Engine expression: {error}"
            ) from error
        if isinstance(decoded, FullSphere):
            own_ee_region(translator, decoded, "EE geometry region")
        if not isinstance(decoded, dict) or decoded.get("type") not in GEOMETRY_TYPES:
            raise UnsupportedEEError("An explicit geometry is required")
        # SDK expression evaluation can return raw mappings after a dictionary
        # lookup. Re-decode every result at this boundary so defaults and
        # constructor metadata cannot be erased by an earlier typed decode.
        geo, result = own_ee_region(
            translator, decoded, "EE geometry region",
        )

    from shapely.geometry import shape

    planar = shape(geo)
    if (planar.is_empty or not planar.is_valid
            or any(not math.isfinite(bound) for bound in planar.bounds)):
        raise ValueError("Invalid geometry")
    west, south, east, north = planar.bounds
    if west < -180 or east > 180 or south < -90 or north > 90:
        raise ValueError("Only WGS84 lon/lat geometry is supported")

    bounds = (west, south, east, north)
    return (result, bounds) if include_bounds else result
