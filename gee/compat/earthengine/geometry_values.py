"""Bounded geometry decoding for official legacy SDK serialization."""
from __future__ import annotations

import math

from .geometry_preflight import (
    GEOMETRY_TYPES,
    precharge_geometry_decode,
)
from .ir import fail


_MAX_COORDINATES = 10000


class GeometryValue(dict):
    """Owned normalized GeoJSON plus effective geometry metadata.

    Default flags live in the sidecar so the public GeoJSON can retain the
    exact omissions used by the pinned SDK.  Consumers must use the sidecar
    when choosing a topology engine; an absent public ``geodesic`` field is
    not evidence that GEOS is safe.
    """

    def __init__(self, mapping, metadata=None, *, validated=False):
        super().__init__(mapping)
        self.geometry_metadata = dict(metadata or {})
        self._geometry_validated = validated is True


def _crs(value):
    # ee.Geometry.encode emits a named GeoJSON CRS, whereas constructors emit
    # an evaluated Projection. Never use set membership on an untrusted dict.
    if isinstance(value, dict):
        properties = value.get("properties")
        if (set(value) != {"type", "properties"} or value.get("type") != "name"
                or not isinstance(properties, dict) or set(properties) != {"name"}
                or not isinstance(properties["name"], str)):
            fail("Geometry CRS must be an EPSG:4326 string or named GeoJSON CRS")
        value = properties["name"]
    if value is not None and value != "EPSG:4326":
        fail("Only EPSG:4326 input GeoJSON geometries are supported")
    return value


def _geometry_metadata(value):
    stored = getattr(value, "geometry_metadata", {})
    if type(stored) is not dict:
        fail("Geometry constructor metadata is malformed")
    metadata = dict(stored)
    if set(metadata) - {"crs", "geodesic", "evenOdd"}:
        fail("Geometry constructor metadata is malformed")
    metadata.update({key: value[key] for key in ("crs", "geodesic", "evenOdd")
                     if key in value})
    if "crs" in metadata:
        metadata["crs"] = _crs(metadata["crs"])
    # The only admitted CRS is geographic EPSG:4326.  EE treats numeric
    # coordinates in that CRS as geodesic by default and polygon interiors
    # as even/odd by default.  Keep those effective defaults out of the
    # public mapping, but make them explicit to every local consumer.
    if metadata.get("crs") is None:
        metadata["crs"] = "EPSG:4326"
    for key in ("geodesic", "evenOdd"):
        if key in metadata and type(metadata[key]) is not bool:
            fail(f"Geometry {key} must be a boolean")
    if value.get("type") != "GeometryCollection":
        metadata.setdefault("geodesic", True)
        metadata.setdefault("evenOdd", True)
    else:
        # A collection may contain components with different edge models.
        # Its children carry their effective state; only preserve a collection
        # flag when the caller explicitly supplied one.
        if "geodesic" not in value and "geodesic" not in stored:
            metadata.pop("geodesic", None)
        if "evenOdd" not in value and "evenOdd" not in stored:
            metadata.pop("evenOdd", None)
    return metadata


def _normalize_geometry(value):
    """Validate supported options and return an independently owned mapping."""
    budget = [0]

    def point(coordinates):
        if (not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2
                or any(not _finite_coordinate(number) for number in coordinates)):
            fail("Geometry coordinates must be finite two-dimensional positions")
        x, y = coordinates
        if not -180 <= x <= 180 or not -90 <= y <= 90:
            fail("EPSG:4326 geometry coordinates exceed longitude/latitude bounds")
        budget[0] += 1
        if budget[0] > _MAX_COORDINATES:
            fail("Geometry exceeds 10000 coordinate positions")
        return [x, y]

    def coordinates(raw, depth, *, polygon=False, linear_ring=False):
        if depth == 0:
            return point(raw)
        if not isinstance(raw, (list, tuple)) or not raw:
            fail("Geometry coordinate arrays must be nonempty")
        result = [coordinates(child, depth - 1) for child in raw]
        if polygon:
            for ring in result:
                if len(ring) < 3:
                    fail("Polygon rings require at least three positions")
                if ring[0] != ring[-1]:
                    ring.append(ring[0].copy())
        elif linear_ring:
            if len(result) < 3:
                fail("LinearRing requires at least three positions")
            if result[0] != result[-1]:
                result.append(result[0].copy())
        return result

    def decode(raw, depth=0):
        if depth > 16:
            fail("Geometry collection nesting exceeds 16 levels")
        if (not isinstance(raw, dict) or type(raw.get("type")) is not str
                or raw["type"] not in GEOMETRY_TYPES):
            fail("Expected a supported GeoJSON geometry")
        kind = raw["type"]
        field = "geometries" if kind == "GeometryCollection" else "coordinates"
        unknown = set(raw) - {"type", field, "crs", "geodesic", "evenOdd"}
        if unknown:
            fail(f"Unsupported GeoJSON geometry fields: {sorted(unknown)}")
        _geometry_metadata(raw)
        if kind == "GeometryCollection":
            children = raw.get(field)
            if not isinstance(children, (list, tuple)) or len(children) > 1000:
                fail("GeometryCollection requires at most 1000 inline geometries")
            output = {"type": kind, field: [decode(child, depth + 1) for child in children]}
        else:
            nesting = {"Point": 0, "MultiPoint": 1, "LineString": 1,
                       "LinearRing": 1, "MultiLineString": 2, "Polygon": 2,
                       "MultiPolygon": 3}[kind]
            raw_coordinates = raw.get(field)
            empty_multi = (
                kind in {"MultiPoint", "MultiLineString", "MultiPolygon"}
                and isinstance(raw_coordinates, (list, tuple))
                and len(raw_coordinates) == 0
            )
            if empty_multi:
                normalized = []
            else:
                if kind == "MultiPolygon" and (
                        not isinstance(raw_coordinates, (list, tuple)) or not raw_coordinates):
                    fail("MultiPolygon coordinates must be nonempty")
                if kind == "MultiPolygon":
                    normalized = [coordinates(poly, 2, polygon=True)
                                  for poly in raw_coordinates]
                else:
                    normalized = coordinates(raw_coordinates, nesting,
                                             polygon=kind == "Polygon",
                                             linear_ring=kind == "LinearRing")
            output = {"type": kind, field: normalized}
        # Preserve flags that were explicitly present in the source wire.
        # Inferred defaults stay in geometry_metadata and therefore do not
        # change the pinned SDK's public serialization.
        for key in ("geodesic", "evenOdd"):
            if key in raw:
                output[key] = raw[key]
        return output

    return decode(value)


def decode_geometry(value):
    """Decode with an isolated 50000-step budget for non-translator callers."""
    class _LocalBudget:
        steps = 0

    return decode_geometry_bounded(_LocalBudget(), value)


def decode_geometry_value(value):
    """Normalize and own a geometry while retaining sidecar options."""
    return decode_geometry(value)


def decode_geometry_bounded(translator, value):
    """Precharge one bounded decode, then validate and own its typed geometry."""
    cost = precharge_geometry_decode(translator, value)
    normalized = _normalize_geometry(value)
    owned = _attach_geometry_metadata(value, normalized)
    from .geometry_topology import (
        contains_spherical_component,
        reserve_spherical_validation,
        validate_geometry_topology,
    )

    if contains_spherical_component(owned):
        reserve_spherical_validation(translator, owned, cost=cost)
    validate_geometry_topology(translator, owned)
    return owned


def _attach_geometry_metadata(raw, normalized):
    if raw["type"] == "GeometryCollection":
        for index, child in enumerate(raw["geometries"]):
            normalized["geometries"][index] = _attach_geometry_metadata(
                child, normalized["geometries"][index]
            )
    return GeometryValue(normalized, _geometry_metadata(raw), validated=True)


def reserve_spherical_validation(translator, value, *, cost=None):
    """Backward-compatible facade for the topology work reserver."""
    from .geometry_topology import reserve_spherical_validation as reserve

    return reserve(translator, value, cost=cost)


def effective_geometry_geodesic(value):
    """Backward-compatible facade for effective edge-model resolution."""
    from .geometry_topology import effective_geometry_geodesic as resolve

    return resolve(value)


def _component_model(value, inherited=None):
    from .geometry_topology import component_model

    return component_model(value, inherited)


def _contains_spherical_component(value, inherited=None):
    from .geometry_topology import contains_spherical_component

    return contains_spherical_component(value, inherited)


def _validate_geometry_topology(translator, value):
    from .geometry_topology import validate_geometry_topology

    return validate_geometry_topology(translator, value)


def own_geometry_bounded(translator, value):
    """Return an owned finite geometry after a fresh bounded validation.

    GeometryValue inherits mutable dict/list behavior, so its prior validation
    marker is informational and cannot authorize later contents.
    """
    return decode_geometry_bounded(translator, value)


def _finite_coordinate(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def construct_geometry(translator, operation, arguments):
    """Resolve a constructor without discarding supported geometry options."""
    from .geometry_constructors import construct_geometry_value

    return construct_geometry_value(translator, operation, arguments)
