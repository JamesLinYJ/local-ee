"""Independent rational/Decimal planar measures, without geometry libraries."""
from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction


def _fraction(value):
    if isinstance(value, str):
        return Fraction(value)
    return Fraction(value)


def _decimal(value):
    value = _fraction(value)
    return Decimal(value.numerator) / Decimal(value.denominator)


def _points(coordinates):
    return [tuple(_fraction(value) for value in point) for point in coordinates]


def _segments(points, closed=False):
    if closed and points and points[-1] != points[0]:
        points = [*points, points[0]]
    return zip(points, points[1:])


def _lengths(points, closed=False):
    for left, right in _segments(points, closed):
        dx, dy = right[0] - left[0], right[1] - left[1]
        yield (_decimal(dx * dx + dy * dy).sqrt(), left, right)


def _ring(coordinates):
    """Exact shoelace area and first moments with explicit orientation removal."""
    points = _points(coordinates)
    twice_area = x_moment = y_moment = Fraction(0)
    for left, right in _segments(points, closed=True):
        cross = left[0] * right[1] - right[0] * left[1]
        twice_area += cross
        x_moment += (left[0] + right[0]) * cross
        y_moment += (left[1] + right[1]) * cross
    if twice_area == 0:
        raise ValueError("Independent reference requires a nondegenerate ring")
    orientation = 1 if twice_area > 0 else -1
    return (abs(twice_area) / 2, orientation * x_moment / 6,
            orientation * y_moment / 6,
            sum((length for length, _, _ in _lengths(points, True)), Decimal(0)))


def _atoms(geometry):
    """Walk original atoms; deliberately perform no dissolve or union."""
    kind = geometry["type"]
    if kind == "GeometryCollection":
        for child in geometry["geometries"]:
            yield from _atoms(child)
    elif kind in {"MultiPolygon", "MultiLineString", "MultiPoint"}:
        atom_kind = {"MultiPolygon": "Polygon", "MultiLineString": "LineString",
                     "MultiPoint": "Point"}[kind]
        for coordinates in geometry["coordinates"]:
            yield atom_kind, coordinates
    else:
        yield kind, geometry["coordinates"]


def reference(geometry):
    """Return decimal scalar strings and a highest-dimension centroid.

    Integer/binary-rational shoelace arithmetic is exact. Segment square roots
    and line-centroid weights use 70-digit Decimal arithmetic. Empty centroids
    are represented by None rather than an invented coordinate.
    """
    with localcontext() as context:
        context.prec = 70
        area = x_area = y_area = Fraction(0)
        length = perimeter = x_line = y_line = Decimal(0)
        points = []
        for kind, coordinates in _atoms(geometry):
            if kind == "Point":
                if coordinates:
                    points.append(tuple(_fraction(value) for value in coordinates))
            elif kind == "LineString":
                for segment, left, right in _lengths(_points(coordinates)):
                    length += segment
                    x_line += segment * _decimal((left[0] + right[0]) / 2)
                    y_line += segment * _decimal((left[1] + right[1]) / 2)
            elif kind == "Polygon":
                for index, ring in enumerate(coordinates):
                    ring_area, ring_x, ring_y, ring_length = _ring(ring)
                    sign = 1 if index == 0 else -1
                    area += sign * ring_area
                    x_area += sign * ring_x
                    y_area += sign * ring_y
                    perimeter += ring_length
            else:
                raise ValueError(f"Unsupported independent reference atom {kind}")
        if area:
            centroid = [_decimal(x_area / area), _decimal(y_area / area)]
            dimension = 2
        elif length:
            centroid = [x_line / length, y_line / length]
            dimension = 1
        elif points:
            centroid = [_decimal(sum(point[axis] for point in points) / len(points))
                        for axis in (0, 1)]
            dimension = 0
        else:
            centroid, dimension = None, -1
        return {"area": str(_decimal(area)), "length": str(length),
                "perimeter": str(perimeter), "highest_dimension": dimension,
                "centroid": None if centroid is None else [str(v) for v in centroid]}


def numeric_expected(record, method):
    value = record[method]
    return ([float(Decimal(item)) for item in value]
            if isinstance(value, list) else None if value is None
            else float(Decimal(value)))
