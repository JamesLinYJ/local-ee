"""Bounded geometry predicates for finite Earth Engine collection filters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .filter_metadata import field_name
from .geometry_values import GEOMETRY_TYPES, own_geometry_bounded
from .ir import fail


_ARGUMENTS = frozenset({
    "leftField", "leftValue", "rightField", "rightValue", "maxError",
})
SPATIAL_FILTER_ARGUMENTS = {
    "Filter.intersects": (frozenset(), _ARGUMENTS),
}
_GEOMETRY_FIELDS = frozenset({".all", ".geo"})


@dataclass(frozen=True)
class _Operand:
    field: str | None
    value: Any = None


@dataclass(frozen=True)
class _IntersectsOperands:
    left: _Operand
    right: _Operand


def _validate_margin(translator, value):
    """Accept only a typed margin that proves no coordinate transformation."""
    if value is None:
        return
    from .error_margin import validate_no_reprojection_margin

    validate_no_reprojection_margin(
        translator, value, "Filter.intersects maxError",
    )


def _parse_operands(translator, arguments):
    if type(arguments) is not dict:
        fail("Filter.intersects arguments must be a dictionary")
    translator.allowed(arguments, _ARGUMENTS)
    if "maxError" in arguments:
        _validate_margin(translator, arguments["maxError"])

    operands = []
    for side in ("left", "right"):
        field_key, value_key = side + "Field", side + "Value"
        field_present = field_key in arguments and arguments[field_key] is not None
        value_present = value_key in arguments and arguments[value_key] is not None
        if field_present == value_present:
            fail(
                "Filter.intersects requires exactly one non-null field or value "
                "per operand"
            )
        if field_present:
            field = arguments[field_key]
            if not isinstance(field, str):
                fail("Filter.intersects requires nonempty flat metadata property names")
            if field in _GEOMETRY_FIELDS:
                translator.steps += max(1, len(field))
                if translator.steps > 50000:
                    fail("Earth Engine graph exceeds compilation limits")
                operands.append(_Operand(field=field))
            else:
                field = field_name(field, "Filter.intersects")
                translator.steps += max(1, len(field))
                if translator.steps > 50000:
                    fail("Earth Engine graph exceeds compilation limits")
                operands.append(_Operand(field=field))
        else:
            geometry = _literal_geometry(arguments[value_key])
            # Decode every literal during structural preflight, including when
            # the collection has no rows. Evaluation owns and validates it again
            # because the caller's input remains mutable.
            owned = own_geometry_bounded(translator, geometry)
            operands.append(_Operand(field=None, value=owned))

    parsed = _IntersectsOperands(*operands)
    if parsed.left.field is None and parsed.right.field is None:
        _common_edge_model(translator, (parsed.left.value, parsed.right.value))
    return parsed


def _common_edge_model(translator, geometries):
    """Resolve one model after charging the bounded scan over owned inputs."""
    from .geometry_preflight import measure_geometry

    work = 0
    for geometry in geometries:
        cost = measure_geometry(geometry)
        work += cost.nodes + cost.positions
    translator.steps += work
    if translator.steps > 50000:
        fail("Filter.intersects geometry model scan exceeds the shared 50000-step budget")
    from .geometry_topology import common_edge_model

    return common_edge_model(*geometries)


def _literal_geometry(value):
    """Unwrap an SDK Feature-valued ROI without dropping geometry metadata."""
    if not isinstance(value, dict):
        fail("Filter.intersects literal operands must be GeoJSON geometries or Features")
    if value.get("type") == "Feature":
        value = value.get("geometry")
        if value is None:
            fail("Filter.intersects Feature literal requires non-null geometry")
    if (not isinstance(value, dict) or type(value.get("type")) is not str
            or value["type"] not in GEOMETRY_TYPES):
        fail("Filter.intersects literal operands must be GeoJSON geometries")
    return value


def prepare_intersects_filter(translator, arguments):
    """Validate a complete Filter.intersects signature and all literal inputs."""
    _parse_operands(translator, arguments)


def _row_geometry(item, field):
    if field in _GEOMETRY_FIELDS:
        return item.get("geometry")
    properties = item.get("properties", {})
    if type(properties) is not dict:
        fail("Filter.intersects row properties must be a dictionary")
    return properties.get(field)


def _own_catalog_geometry(translator, geometry):
    """Keep catalog GeoJSON footprints planar unless the source says otherwise."""
    from .geometry_values import GeometryValue

    if isinstance(geometry, GeometryValue) or "geodesic" in geometry:
        return own_geometry_bounded(translator, geometry)

    from .geometry_preflight import precharge_geometry_copy

    cost = precharge_geometry_copy(
        translator, geometry, "Filter.intersects catalog geometry copy",
    )
    scan_work = cost.nodes + cost.geometries + cost.positions
    if translator.steps + scan_work > 50000:
        fail("Filter.intersects catalog model scan exceeds the shared 50000-step budget")
    translator.steps += scan_work
    if not _has_edges(geometry):
        # Edge-less values have no source curve model to preserve. Keeping the
        # SDK default lets a Point follow a curved operand without GEOS
        # validation of the point itself.
        return own_geometry_bounded(translator, geometry)
    planar = dict(geometry)
    planar["geodesic"] = False
    return own_geometry_bounded(translator, planar)


def _has_edges(value):
    """Check for any curve-bearing component after reserving a bounded scan."""
    kind = value["type"]
    if kind == "GeometryCollection":
        return any(_has_edges(child) for child in value["geometries"])
    if kind in {"Point", "MultiPoint"}:
        return False
    coordinates = value["coordinates"]
    if kind in {"LineString", "LinearRing"}:
        return len(coordinates) >= 2
    if kind == "MultiLineString":
        return any(len(line) >= 2 for line in coordinates)
    if kind == "Polygon":
        return any(len(ring) >= 2 for ring in coordinates)
    if kind == "MultiPolygon":
        return any(len(ring) >= 2 for polygon in coordinates for ring in polygon)
    return False


def _resolve(translator, operand, item, *, catalog_geometry):
    if operand.field is None:
        # _parse_operands just freshly decoded the literal from the mutable
        # filter. Reuse that owned value; the shared binary route performs its
        # own bounded decode before dispatch as well.
        return operand.value
    raw = _row_geometry(item, operand.field)
    if raw is None:
        return None
    if (not isinstance(raw, dict) or type(raw.get("type")) is not str
            or raw["type"] not in GEOMETRY_TYPES):
        fail("Filter.intersects field operands must contain GeoJSON geometries")
    if catalog_geometry and operand.field in _GEOMETRY_FIELDS:
        return _own_catalog_geometry(translator, raw)
    return own_geometry_bounded(translator, raw)


def evaluate_intersects_filter(
    translator, arguments, item, *, catalog_geometry=False,
):
    """Evaluate geometry-valued fields against actual row or literal geometry."""
    if type(item) is not dict:
        fail("Filter.intersects requires a finite collection row")
    parsed = _parse_operands(translator, arguments)
    left = _resolve(
        translator, parsed.left, item, catalog_geometry=catalog_geometry,
    )
    right = _resolve(
        translator, parsed.right, item, catalog_geometry=catalog_geometry,
    )
    if left is None or right is None:
        return False

    planar = not _common_edge_model(translator, (left, right))
    from .geometry_binary import invoke_geometry_binary

    binary_arguments = {"left": left, "right": right}
    if planar:
        binary_arguments["proj"] = "EPSG:4326"
    return invoke_geometry_binary(
        translator, "Geometry.intersects", binary_arguments,
    )
