"""Checked caller-side work reservation for native WGS84 scalar measures."""
from __future__ import annotations

from .geometry_preflight import MAX_GEOMETRY_WORK
from .spherical_preflight import geometry_counts
from .spherical_wire import FullSphere
from .ir import fail


_QUADRATURE_EVALUATIONS_PER_EDGE = 56  # GL8 at 1, 2 and 4 equal-panel levels.
_METRICS = frozenset({"area", "length", "perimeter"})


def _canonical_coordinate(point):
    longitude, latitude = point
    if latitude in (-90, 90):
        longitude = 0
    if longitude == 180:
        longitude = -180
    if longitude == 0:
        longitude = 0.0
    if latitude == 0:
        latitude = 0.0
    return longitude, latitude


def _polygon_edges(ring):
    # Match BuildPolygon's exact canonical SamePoint rule. ShapeView/W0 still
    # counts every wire position; only quadrature skips the implicit closing
    # edge when GeoJSON repeated its first position.
    if (len(ring) > 3
            and _canonical_coordinate(ring[0]) == _canonical_coordinate(ring[-1])):
        return len(ring) - 1
    return len(ring)


def _selected_edge_count(value, metric):
    if isinstance(value, FullSphere):
        return 0
    kind = value["type"]
    if kind == "GeometryCollection":
        return sum(_selected_edge_count(child, metric)
                   for child in value["geometries"])
    if metric in {"area", "perimeter"}:
        if kind == "Polygon":
            return sum(_polygon_edges(ring) for ring in value["coordinates"])
        if kind == "MultiPolygon":
            return sum(_polygon_edges(ring) for polygon in value["coordinates"]
                       for ring in polygon)
        return 0
    if kind in {"LineString", "LinearRing"}:
        return max(0, len(value["coordinates"]) - 1)
    if kind == "MultiLineString":
        return sum(max(0, len(line) - 1) for line in value["coordinates"])
    return 0


def metric_native_work(geometry, metric):
    """Match native W0 plus the selected metric's 56 evaluations per edge."""
    if metric not in _METRICS:
        fail("Unsupported WGS84 geometry metric work estimate")
    positions, edges, active, parts = geometry_counts(geometry)
    base = ((positions + edges + 1) ** 2 * (active + 1)
            + positions ** 2 + 4 * edges + 4 * active + parts)
    if base > MAX_GEOMETRY_WORK:
        fail("WGS84 measure base work exceeds the shared 50000-step budget")
    selected = _selected_edge_count(geometry, metric)
    if selected > (MAX_GEOMETRY_WORK - base) // _QUADRATURE_EVALUATIONS_PER_EDGE:
        fail("WGS84 quadrature work exceeds the shared 50000-step budget")
    return base + _QUADRATURE_EVALUATIONS_PER_EDGE * selected
