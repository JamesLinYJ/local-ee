"""Conservative pre-GEOS work and output bounds for binary geometries."""
from __future__ import annotations

from .geometry_preflight import MAX_GEOMETRY_CHILDREN, MAX_GEOMETRY_COORDINATES
from .ir import fail


_PREDICATES = frozenset({"Geometry.contains", "Geometry.containedIn",
                         "Geometry.intersects", "Geometry.disjoint"})


def reserve_geometry_binary(name, left, right):
    """Return operation/output reservations before decoding or calling GEOS.

    Cross-input and within-input candidate counts include edge/edge,
    edge/vertex, and vertex/vertex comparisons. Only edge/edge candidates can
    insert new output vertices; each candidate is allowed to split both sides.
    This deliberately overestimates simple cases to bound multipart noding,
    point contacts, and mixed-dimensional collection results uniformly.
    """
    left_edges, right_edges = left["segments"], right["segments"]
    left_points, right_points = left["positions"], right["positions"]
    cross_pairs = (left_edges * right_edges + left_edges * right_points
                   + right_edges * left_points + left_points * right_points)
    internal_pairs = sum(
        edges * (edges - 1) // 2 + edges * points + points * (points - 1) // 2
        for edges, points in ((left_edges, left_points),
                              (right_edges, right_points))
    )
    operation_work = (1 + left_edges + right_edges + left_points + right_points
                      + cross_pairs + internal_pairs)
    if name in _PREDICATES:
        return operation_work, 0, 0, 0

    split_pairs = (left_edges * right_edges
                   + left_edges * (left_edges - 1) // 2
                   + right_edges * (right_edges - 1) // 2)
    output_positions = left_points + right_points + 2 * split_pairs
    if 2 in left["dimensions"] | right["dimensions"]:
        # Each output ring needs one closure position and at least four total.
        ring_bound = min(left["rings"] + right["rings"] + split_pairs,
                         output_positions // 4)
        output_positions += ring_bound
    else:
        ring_bound = 0
    if output_positions > MAX_GEOMETRY_COORDINATES:
        fail("Geometry binary result may exceed 10000 coordinate positions")

    # Any overlay may produce a mixed-dimensional GeometryCollection. Count
    # input components and vertices for point contacts, plus inserted splits.
    output_children = (left["components"] + right["components"]
                       + left_points + right_points + 2 * split_pairs + ring_bound)
    if output_children > MAX_GEOMETRY_CHILDREN:
        fail("Geometry binary result may exceed 1000 GeometryCollection children")
    # The reservation includes GEOS output mapping, bounded result measurement,
    # metadata exposure, and the decoder's validation/copy. It stays charged;
    # no unused worst-case allowance is refunded after the result is known.
    output_work = 14 * output_positions + 20 * output_children + 256
    return operation_work, output_work, output_positions, output_children
