"""The native S2 work equation, independently enforced on both sides of its ABI."""
from __future__ import annotations

from .spherical_wire import FullSphere


def geometry_counts(value):
    """Count a freshly structurally validated geometry without copying positions.

    Counts match the numeric ABI, including repeated ring closure positions.
    Empty multi-geometries have no native shapes. This function is only used
    after the ordinary finite geometry tree preflight/normalization.
    """
    if isinstance(value, FullSphere):
        return 0, 0, 1, 1
    kind = value["type"]
    if kind == "GeometryCollection":
        counts = [geometry_counts(child) for child in value["geometries"]]
        return tuple(sum(item[index] for item in counts) for index in range(4))
    coordinates = value["coordinates"]
    if kind == "Point":
        return 1, 0, 1, 1
    if kind == "MultiPoint":
        size = len(coordinates)
        return size, 0, int(bool(size)), int(bool(size))
    if kind in {"LineString", "LinearRing"}:
        return len(coordinates), max(0, len(coordinates) - 1), 1, 1
    if kind == "MultiLineString":
        return (sum(map(len, coordinates)),
                sum(max(0, len(line) - 1) for line in coordinates),
                len(coordinates), len(coordinates))
    polygons = [coordinates] if kind == "Polygon" else coordinates
    positions = sum(len(ring) for polygon in polygons for ring in polygon)
    return (positions, positions, sum(bool(polygon) for polygon in polygons),
            sum(len(polygon) for polygon in polygons))


def native_work(left, right=None):
    """Match native CheckCallBudget before native construction/normalization."""
    counts = geometry_counts(left)
    if right is not None:
        counts = tuple(a + b for a, b in zip(counts, geometry_counts(right)))
    positions, edges, active, parts = counts
    return ((positions + edges + 1) ** 2 * (active + 1) + positions ** 2
            + 4 * edges + 4 * active + parts)
