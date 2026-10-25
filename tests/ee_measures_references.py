"""Independent references and the Wave71 Geometry/Feature measure workflow."""
from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-geometry-measures-wave71-v1.json"
WGS84 = ROOT / "audit/gee-python-wave71/review/frozen-ellipsoid-controls-v2.json"


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _fraction(value):
    return Fraction(str(value))


def _segment_length(left, right):
    with localcontext() as context:
        context.prec = 50
        dx = Decimal((right[0] - left[0]).numerator) / Decimal(
            (right[0] - left[0]).denominator)
        dy = Decimal((right[1] - left[1]).numerator) / Decimal(
            (right[1] - left[1]).denominator)
        return float((dx * dx + dy * dy).sqrt())


def _ring_stats(ring):
    """Return exact signed area and centroid for a planar ring."""
    points = [tuple(map(_fraction, position[:2])) for position in ring]
    twice_area = sum(
        x0 * y1 - x1 * y0
        for (x0, y0), (x1, y1) in zip(points, points[1:])
    )
    if twice_area == 0:
        return Fraction(0), (Fraction(0), Fraction(0))
    cx_numerator = sum(
        (x0 + x1) * (x0 * y1 - x1 * y0)
        for (x0, y0), (x1, y1) in zip(points, points[1:])
    )
    cy_numerator = sum(
        (y0 + y1) * (x0 * y1 - x1 * y0)
        for (x0, y0), (x1, y1) in zip(points, points[1:])
    )
    return (twice_area / 2,
            (cx_numerator / (3 * twice_area), cy_numerator / (3 * twice_area)))


def _polygon_stats(rings):
    if not rings:
        return Fraction(0), (Fraction(0), Fraction(0)), 0.0
    signed = [_ring_stats(ring) for ring in rings]
    # GeoJSON ring order defines the shell followed by holes. Absolute ring
    # areas make the reference independent of orientation; holes subtract.
    weights = [abs(area) if index == 0 else -abs(area)
               for index, (area, _) in enumerate(signed)]
    net_area = sum(weights, Fraction(0))
    if net_area:
        cx = sum(weight * centroid[0]
                 for weight, (_, centroid) in zip(weights, signed)) / net_area
        cy = sum(weight * centroid[1]
                 for weight, (_, centroid) in zip(weights, signed)) / net_area
    else:
        cx = cy = Fraction(0)
    perimeter = sum(
        _segment_length((x0, y0), (x1, y1))
        for ring in rings
        for (x0, y0), (x1, y1) in zip(
            [tuple(map(_fraction, p[:2])) for p in ring],
            [tuple(map(_fraction, p[:2])) for p in ring][1:]
        )
    )
    return net_area, (cx, cy), perimeter


def _planar_components(geometry):
    """Flatten a GeoJSON geometry into point, line and polygon components."""
    kind = geometry["type"]
    coordinates = geometry.get("coordinates")
    if kind == "GeometryCollection":
        for child in geometry.get("geometries", []):
            yield from _planar_components(child)
    elif kind == "Point":
        yield "Point", [coordinates]
    elif kind == "MultiPoint":
        for point in coordinates:
            yield "Point", [point]
    elif kind == "LineString":
        yield "LineString", coordinates
    elif kind == "MultiLineString":
        for line in coordinates:
            yield "LineString", line
    elif kind == "Polygon":
        yield "Polygon", coordinates
    elif kind == "MultiPolygon":
        for polygon in coordinates:
            yield "Polygon", polygon
    else:
        raise AssertionError(f"Unknown fixture geometry type: {kind}")


def planar_reference(geometry):
    """Exact shoelace/Fraction projection reference for EPSG:4326 coordinates."""
    components = list(_planar_components(geometry))
    area = Fraction(0)
    length = 0.0
    perimeter = 0.0
    dimensions = {"Point": 0, "LineString": 1, "Polygon": 2}
    centroids = []
    for kind, coordinates in components:
        if kind == "Point":
            point = tuple(map(_fraction, coordinates[0][:2]))
            centroids.append((0, Fraction(1), point))
        elif kind == "LineString":
            line_length = 0.0
            x_weight = y_weight = 0.0
            points = [tuple(map(_fraction, p[:2])) for p in coordinates]
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                segment = _segment_length((x0, y0), (x1, y1))
                line_length += segment
                x_weight += segment * float(x0 + x1) / 2
                y_weight += segment * float(y0 + y1) / 2
            length += line_length
            centroid = ((x_weight / line_length, y_weight / line_length)
                        if line_length else (0.0, 0.0))
            if line_length:
                centroids.append((1, line_length, centroid))
        else:
            component_area, centroid, component_perimeter = _polygon_stats(coordinates)
            area += component_area
            perimeter += component_perimeter
            if component_area:
                centroids.append((2, float(component_area),
                                  (float(centroid[0]), float(centroid[1]))))
    highest = max((dimension for dimension, _, _ in centroids), default=-1)
    highest_parts = [(weight, center) for dimension, weight, center in centroids
                     if dimension == highest]
    total_weight = sum(weight for weight, _ in highest_parts)
    if total_weight:
        center = [
            sum(weight * center[index] for weight, center in highest_parts) / total_weight
            for index in (0, 1)
        ]
    else:
        center = None
    return {
        "highest_dimension": highest,
        "area_square_degrees": area,
        "linear_length_degrees": length,
        "polygon_perimeter_degrees": perimeter,
        "centroid_lon_lat_degrees": center,
    }


def _unit(longitude, latitude):
    longitude, latitude = map(math.radians, (longitude, latitude))
    return (math.cos(latitude) * math.cos(longitude),
            math.cos(latitude) * math.sin(longitude), math.sin(latitude))


def spherical_arc_angle(a, b):
    left, right = _unit(*a), _unit(*b)
    cross = (left[1] * right[2] - left[2] * right[1],
             left[2] * right[0] - left[0] * right[2],
             left[0] * right[1] - left[1] * right[0])
    norm = math.sqrt(sum(value * value for value in cross))
    dot = sum(x * y for x, y in zip(left, right))
    return math.atan2(norm, dot)


def spherical_triangle_area(a, b, c):
    first, second, third = map(lambda p: _unit(*p), (a, b, c))
    cross = (second[1] * third[2] - second[2] * third[1],
             second[2] * third[0] - second[0] * third[2],
             second[0] * third[1] - second[1] * third[0])
    determinant = abs(sum(x * y for x, y in zip(first, cross)))
    denominator = (1 + sum(x * y for x, y in zip(first, second))
                   + sum(x * y for x, y in zip(second, third))
                   + sum(x * y for x, y in zip(third, first)))
    return 2 * math.atan2(determinant, denominator)


def _dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def _cross(left, right):
    return (left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0])


def spherical_centroid_vector(geometry):
    """Independent unnormalized vector integral for highest-dimension parts."""
    components = list(_planar_components(geometry))
    dimensions = {"Point": 0, "LineString": 1, "Polygon": 2}
    highest = max((dimensions[kind] for kind, _ in components), default=-1)
    vector = [0.0, 0.0, 0.0]
    for kind, coordinates in components:
        if dimensions[kind] != highest:
            continue
        if kind == "Point":
            part = _unit(*coordinates[0][:2])
            for axis in range(3):
                vector[axis] += part[axis]
        elif kind == "LineString":
            points = [_unit(*position[:2]) for position in coordinates]
            for left, right in zip(points, points[1:]):
                angle = math.atan2(math.sqrt(_dot(_cross(left, right),
                                                   _cross(left, right))),
                                   _dot(left, right))
                weight = math.tan(angle / 2)
                for axis in range(3):
                    vector[axis] += weight * (left[axis] + right[axis])
        else:
            for ring in coordinates:
                points = [_unit(*position[:2]) for position in ring]
                for left, right in zip(points, points[1:]):
                    cross = _cross(left, right)
                    norm = math.sqrt(_dot(cross, cross))
                    if norm == 0:
                        continue
                    angle = math.atan2(norm, _dot(left, right))
                    for axis in range(3):
                        vector[axis] += 0.5 * angle * cross[axis] / norm
    return highest, tuple(vector)


def spherical_centroid_coordinates(geometry):
    dimension, vector = spherical_centroid_vector(geometry)
    norm = math.sqrt(_dot(vector, vector))
    if dimension < 0 or norm == 0:
        return None
    x, y, z = (value / norm for value in vector)
    return [math.degrees(math.atan2(y, x)),
            math.degrees(math.atan2(z, math.hypot(x, y)))]


def verify_frozen_wgs84_reference():
    """Verify the reviewed high-precision controls before using expected values."""
    fixture = load_fixture()
    model = fixture["metric_models"]["public_default_wgs84_ellipsoid_edge_v1"]
    source = model["independent_control_source"]
    if len(model["numeric_controls"]) != 23:
        raise AssertionError("WGS84 control inventory changed")
    canonical = json.dumps(
        model["numeric_controls"], ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != source["records_sha256"]:
        raise AssertionError("Embedded WGS84 control inventory hash changed")
    if WGS84.exists():
        raw = WGS84.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise AssertionError("Frozen independent WGS84 reference hash changed")
        reference = json.loads(raw)
        if model["numeric_controls"] != reference["records"]:
            raise AssertionError("Fixture controls differ from frozen WGS84 references")
    return model["numeric_controls"]
