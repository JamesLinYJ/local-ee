"""Validate planar 2D GeoJSON; coordinates stay longitude/latitude without reprojection."""

from __future__ import annotations

import math
from typing import Any, Callable, TypeAlias


Bounds: TypeAlias = tuple[float, float, float, float]


class TableGeometryError(ValueError):
    """Raised for unsupported or malformed inline GeoJSON geometry metadata."""


def _fail(message: str) -> None:
    raise TableGeometryError(message)


def validate_crs(obj: dict[str, Any]) -> None:
    """Allow absent/null CRS or a named EPSG:4326 CRS; never reproject."""
    if "crs" not in obj or obj["crs"] is None:
        return
    crs = obj["crs"]
    if type(crs) is not dict or crs.get("type") != "name":
        _fail("GeoJSON crs must be null or a named EPSG:4326 CRS")
    properties = crs.get("properties")
    if type(properties) is not dict or set(properties) != {"name"}:
        _fail("GeoJSON crs must be null or a named EPSG:4326 CRS")
    name = properties["name"]
    accepted = {
        "epsg:4326",
        "urn:ogc:def:crs:epsg::4326",
        "http://www.opengis.net/def/crs/epsg/0/4326",
        "https://www.opengis.net/def/crs/epsg/0/4326",
    }
    if type(name) is not str or name.casefold() not in accepted:
        _fail("Only named EPSG:4326 GeoJSON crs is supported; no reprojection is performed")


def union_bounds(left: Bounds | None, right: Bounds | None) -> Bounds | None:
    """Combine actual non-empty geometry extents without coordinate conversion."""
    if left is None:
        return right
    if right is None:
        return left
    return (
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    )


def validate_bbox(obj: dict[str, Any], bounds: Bounds | None) -> None:
    """Validate a 2D ordered bbox and require it to enclose supplied geometry."""
    if "bbox" not in obj:
        return
    bbox = obj["bbox"]
    if type(bbox) is not list or len(bbox) != 4:
        _fail("Two-dimensional GeoJSON bbox must contain four finite numbers")
    if any(
        type(value) not in (int, float)
        or (type(value) is float and not math.isfinite(value))
        for value in bbox
    ):
        _fail("Two-dimensional GeoJSON bbox must contain four finite numbers")
    west, south, east, north = bbox
    if not -180 <= west <= east <= 180 or not -90 <= south <= north <= 90:
        _fail("GeoJSON bbox must be ordered within WGS84 longitude/latitude bounds")
    if bounds is not None:
        min_x, min_y, max_x, max_y = bounds
        if west > min_x or south > min_y or east < max_x or north < max_y:
            _fail("GeoJSON bbox must enclose its non-empty geometry")


def _number(value: Any) -> bool:
    return type(value) in (int, float) and (
        type(value) is not float or math.isfinite(value)
    )


def _position(value: Any) -> None:
    if type(value) is not list or len(value) != 2:
        _fail("GeoJSON positions must contain exactly two coordinates")
    longitude, latitude = value
    if not _number(longitude) or not _number(latitude):
        _fail("GeoJSON coordinates must be finite numbers")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        _fail("GeoJSON coordinates must be within WGS84 longitude/latitude bounds")


def _line(value: Any) -> None:
    if type(value) is not list or len(value) < 2:
        _fail("GeoJSON LineString coordinates require at least two positions")
    for point in value:
        _position(point)


def _ring(value: Any) -> None:
    if type(value) is not list or len(value) < 4:
        _fail("GeoJSON polygon rings require at least four positions")
    for point in value:
        _position(point)
    if value[0] != value[-1]:
        _fail("GeoJSON polygon rings must be closed")


def _polygon(value: Any) -> None:
    if type(value) is not list or not value:
        _fail("GeoJSON Polygon coordinates require an exterior ring")
    for ring in value:
        _ring(ring)


def _validate_semantics(geometry: dict[str, Any], *, spherical: bool = False) -> None:
    if "geodesic" in geometry:
        if type(geometry["geodesic"]) is not bool:
            _fail("GeoJSON geometry geodesic must be boolean")
        if geometry["geodesic"] and not spherical:
            _fail("geodesic=true EE geometry is unsupported; table geometry is planar")
    if "evenOdd" in geometry:
        if type(geometry["evenOdd"]) is not bool:
            _fail("GeoJSON geometry evenOdd must be boolean")
        if not geometry["evenOdd"] and not spherical:
            _fail("evenOdd=false EE geometry is unsupported by planar GeoJSON tables")


def validate_geometry(geometry: Any, *, planar_components: bool = False) -> Bounds | None:
    """Validate a GeoJSON geometry, including nested collections and its bbox."""
    if geometry is None:
        return None
    if type(geometry) is not dict or type(geometry.get("type")) is not str:
        _fail("Feature geometry must be null or a GeoJSON geometry object")
    validate_crs(geometry)
    _validate_semantics(geometry)
    kind = geometry["type"]
    coordinates = geometry.get("coordinates")
    if kind == "Point":
        _position(coordinates)
    elif kind == "MultiPoint":
        if type(coordinates) is not list or not coordinates:
            _fail("GeoJSON MultiPoint coordinates must be non-empty")
        for point in coordinates:
            _position(point)
    elif kind == "LineString":
        _line(coordinates)
    elif kind == "MultiLineString":
        if type(coordinates) is not list or not coordinates:
            _fail("GeoJSON MultiLineString coordinates must be non-empty")
        for line in coordinates:
            _line(line)
    elif kind == "Polygon":
        _polygon(coordinates)
    elif kind == "MultiPolygon":
        if type(coordinates) is not list or (not coordinates and not planar_components):
            _fail("GeoJSON MultiPolygon coordinates must be non-empty")
        for polygon in coordinates:
            _polygon(polygon)
    elif kind == "GeometryCollection":
        geometries = geometry.get("geometries")
        if type(geometries) is not list:
            _fail("GeoJSON GeometryCollection requires a geometries array")
        bounds = None
        for child in geometries:
            child_bounds = validate_geometry(child, planar_components=planar_components)
            bounds = union_bounds(bounds, child_bounds)
        if planar_components:
            validate_bbox(geometry, bounds)
            return bounds
    else:
        _fail(f"Unsupported GeoJSON geometry type: {kind}")

    if planar_components:
        bounds = _planar_component_bounds(geometry)
        validate_bbox(geometry, bounds)
        return bounds

    try:
        from shapely.geometry import shape

        parsed = shape(geometry)
    except Exception as exc:
        raise TableGeometryError("Invalid GeoJSON geometry") from exc
    if not parsed.is_valid:
        _fail("GeoJSON geometry topology is invalid")
    bounds = None if parsed.is_empty else tuple(parsed.bounds)
    validate_bbox(geometry, bounds)
    return bounds  # type: ignore[return-value]


def _planar_component_bounds(geometry):
    from .planar_geometry_validation import PlanarGeometryError, planar_component_bounds

    try:
        return planar_component_bounds(geometry)
    except PlanarGeometryError as error:
        raise TableGeometryError(str(error)) from error


def validate_geometry_with_models(
    geometry: Any,
    *,
    spherical_model: Callable[[dict[str, Any], bool | None], bool | None],
    even_odd_model: Callable[[dict[str, Any], bool | None], bool],
    spherical_validator: Callable[[dict[str, Any], bool], None],
    inherited_geodesic: bool | None = None,
    inherited_even_odd: bool | None = None,
    planar_components: bool = False,
) -> Bounds | None:
    """Validate a typed/mixed EE geometry without sending spherical parts to GEOS.

    Raw standalone GeoJSON continues to use :func:`validate_geometry` and its
    historical planar policy.  This path is selected only when effective EE
    constructor metadata or an explicit public geodesic flag makes spherical
    validation necessary.
    """
    active: set[int] = set()
    visits = [0]

    def walk(
        current: Any,
        inherited_sphere: bool | None,
        inherited_parity: bool | None,
        depth: int,
    ) -> Bounds | None:
        if current is None:
            return None
        if depth > 16:
            _fail("GeoJSON GeometryCollection nesting exceeds 16 levels")
        if not isinstance(current, dict) or type(current.get("type")) is not str:
            _fail("Feature geometry must be null or a GeoJSON geometry object")
        identity = id(current)
        if identity in active:
            _fail("GeoJSON GeometryCollection contains a cycle")
        visits[0] += 1
        if visits[0] > 50_000:
            _fail("GeoJSON geometry exceeds the bounded table traversal limit")
        active.add(identity)
        try:
            validate_crs(current)
            model = spherical_model(current, inherited_sphere)
            even_odd = even_odd_model(current, inherited_parity)
            _validate_semantics(current, spherical=model is True)
            kind = current["type"]
            coordinates = current.get("coordinates")
            if kind == "Point":
                _position(coordinates)
            elif kind == "MultiPoint":
                if type(coordinates) is not list or not coordinates:
                    _fail("GeoJSON MultiPoint coordinates must be non-empty")
                for point in coordinates:
                    _position(point)
            elif kind == "LineString":
                _line(coordinates)
            elif kind == "MultiLineString":
                if type(coordinates) is not list or not coordinates:
                    _fail("GeoJSON MultiLineString coordinates must be non-empty")
                for line in coordinates:
                    _line(line)
            elif kind == "Polygon":
                _polygon(coordinates)
            elif kind == "MultiPolygon":
                if type(coordinates) is not list or (not coordinates and not planar_components):
                    _fail("GeoJSON MultiPolygon coordinates must be non-empty")
                for polygon in coordinates:
                    _polygon(polygon)
            elif kind == "GeometryCollection":
                children = current.get("geometries")
                if type(children) is not list:
                    _fail("GeoJSON GeometryCollection requires a geometries array")
                if len(children) > 1_000:
                    _fail("GeoJSON GeometryCollection exceeds 1000 inline geometries")
                bounds: Bounds | None = None
                for child in children:
                    bounds = union_bounds(
                        bounds, walk(child, model, even_odd, depth + 1),
                    )
                if not children and model is True:
                    spherical_validator(current, even_odd)
                validate_bbox(current, bounds)
                return bounds
            else:
                _fail(f"Unsupported GeoJSON geometry type: {kind}")

            if model is True:
                spherical_validator(current, even_odd)
                # Points have no curved edges. For lines and areas, the
                # conservative full-world extent avoids claiming that vertex
                # extrema enclose S2 arcs.
                if kind == "Point":
                    x, y = coordinates
                    bounds = (x, y, x, y)
                elif kind == "MultiPoint":
                    west = east = coordinates[0][0]
                    south = north = coordinates[0][1]
                    for index in range(1, len(coordinates)):
                        x, y = coordinates[index]
                        west, south = min(west, x), min(south, y)
                        east, north = max(east, x), max(north, y)
                    bounds = (west, south, east, north)
                else:
                    bounds = (-180, -90, 180, 90)
            elif planar_components:
                bounds = _planar_component_bounds(current)
            else:
                try:
                    from shapely.geometry import shape

                    parsed = shape(current)
                except Exception as exc:
                    raise TableGeometryError("Invalid GeoJSON geometry") from exc
                if not parsed.is_valid:
                    _fail("GeoJSON geometry topology is invalid")
                bounds = None if parsed.is_empty else tuple(parsed.bounds)
            validate_bbox(current, bounds)
            return bounds  # type: ignore[return-value]
        finally:
            active.remove(identity)

    return walk(geometry, inherited_geodesic, inherited_even_odd, 0)
