"""Actual S2 ABI and independent great-circle controls; build required first."""
from __future__ import annotations

import ctypes
import math

import pytest

from gee.compat.earthengine import spherical_native as native
from gee.compat.earthengine.spherical_wire import FULL_SPHERE, encode_geometry


EMPTY = {"type": "GeometryCollection", "geometries": []}


def point(x, y):
    return {"type": "Point", "coordinates": [x, y]}


def line(*points):
    return {"type": "LineString", "coordinates": [list(p) for p in points]}


def square(x1, y1, x2, y2):
    return {"type": "Polygon", "coordinates": [
        [[x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]],
    ]}


def overlay(operation, left, right):
    return native.run(operation, left, right, output_positions=100,
                      output_children=100)


def call_raw(wire, *, operation=8, capacity=64):
    function = native._load()
    left = (ctypes.c_double * len(wire))(*wire)
    empty = (ctypes.c_double * 2)(1, 0)
    # Two canaries sit outside the capacity advertised to the C ABI.
    output = (ctypes.c_double * (min(capacity, 64) + 2))()
    output[-1], output[-2] = 4567, 1234
    size = ctypes.c_size_t(999)
    error = ctypes.create_string_buffer(256)
    code = function(operation, left, len(wire), empty, 2, output, capacity,
                    ctypes.byref(size), error, len(error))
    assert (output[-2], output[-1]) == (1234, 4567)
    return code, size.value, error.value.decode()


@pytest.mark.parametrize("wire", [
    [], [1], [0, 0], [math.nan, 0], [1, math.inf], [1, -1], [1, .5],
    [1, 1001], [1, 1], [1, 1, 3, 0, 1, 1, 0, 0],
    [1, 1, 0, 1, 1, 1, 0, 0],  # Polygon-only evenOdd on points.
    [1, 1, 0, 0, 2, 0, 0], [1, 1, 0, 0, 1, 10001],
    [1, 1, 0, 0, 1, 2, 0, 0], [1, 0, 2],
    [1, 1, 0, 0, 1, 1, math.nan, 0],
    [1, 1, 0, 0, 1, 1, 181, 0], [1, 1, 0, 0, 1, 1, 0, 91],
])
def test_malformed_numeric_input_fails_with_no_output_or_buffer_overwrite(wire):
    code, size, error = call_raw(wire)
    assert code != 0 and size == 0 and error


@pytest.mark.parametrize("operation,capacity", [(-1, 64), (14, 64), (8, 0), (8, 65537)])
def test_invalid_abi_call_is_rejected(operation, capacity):
    code, size, error = call_raw([1, 0], operation=operation, capacity=capacity)
    assert code != 0 and size == 0 and error


@pytest.mark.parametrize("coordinates", [
    [45, 45], [123.4567, -22.3344], [.1, .2], [-123.9, 52.7],
    [179.1, -31], [-179.1, 31], [0, 0], [90, 0],
])
def test_unchanged_vertex_retains_input_coordinate_and_identity(coordinates):
    original = point(*coordinates)
    result = overlay("union", original, EMPTY)
    assert result["coordinates"] == coordinates
    assert native.run("intersects", original, result) is True
    assert native.run("contains", result, original) is True


def test_nearby_distinct_points_are_never_merged_by_a_distance_tolerance():
    original = point(0, 0)
    for delta in (1e-14, 1e-13, 1.1e-13, 1e-12):
        nearby = point(delta, 0)
        assert native.run("intersects", original, nearby) is False
        assert native.run("disjoint", original, nearby) is True


@pytest.mark.parametrize("right,dimension", [
    (square(4, 0, 8, 4), "LineString"),
    (square(4, 4, 8, 8), "Point"),
])
def test_closed_polygon_contacts_keep_their_lower_dimension(right, dimension):
    left = square(0, 0, 4, 4)
    assert native.run("intersects", left, right) is True
    assert native.run("disjoint", left, right) is False
    result = overlay("intersection", left, right)
    assert result["type"] == dimension
    native.validate(result)


def _cross(left, right):
    return (left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0])


def _unit(longitude, latitude):
    longitude, latitude = map(math.radians, (longitude, latitude))
    return (math.cos(latitude) * math.cos(longitude),
            math.cos(latitude) * math.sin(longitude), math.sin(latitude))


def test_generated_crossing_matches_independent_spherical_plane_intersection():
    first, second = line((0, 10), (20, 30)), line((0, 30), (20, 10))
    result = overlay("intersection", first, second)
    assert result["type"] == "Point"
    axis = _cross(_cross(_unit(0, 10), _unit(20, 30)),
                  _cross(_unit(0, 30), _unit(20, 10)))
    if axis[0] < 0:
        axis = tuple(-item for item in axis)
    expected = [math.degrees(math.atan2(axis[1], axis[0])),
                math.degrees(math.atan2(axis[2], math.hypot(axis[0], axis[1])))]
    assert result["coordinates"] == pytest.approx(expected, abs=2e-14)
    # This is a measured representability limitation, not a compatibility pass:
    # constructive S2/lat-lon rounding can move a generated point off an exact
    # original edge. Never hide it by epsilon-merging distinct input points.
    assert native.run("intersects", result, first) is False
    assert native.run("intersects", result, second) is False


def test_empty_and_boundaryless_full_sphere_remain_distinct_internal_values():
    assert native.run("contains", FULL_SPHERE, point(33, 44)) is True
    assert native.run("disjoint", FULL_SPHERE, EMPTY) is True
    assert overlay("intersection", FULL_SPHERE, EMPTY)["type"] == "GeometryCollection"
    assert overlay("union", FULL_SPHERE, EMPTY) is FULL_SPHERE


def test_antipodal_edges_reject_before_ambiguous_arc_construction():
    code, size, error = call_raw(encode_geometry(line((0, 0), (180, 0))))
    assert code != 0 and size == 0 and "antipodal" in error


def test_single_call_cannot_exceed_the_native_work_limit():
    raw = {"type": "MultiPoint", "coordinates": [[index / 100, 0] for index in range(200)]}
    code, size, error = call_raw(encode_geometry(raw))
    assert code != 0 and size == 0 and "50000" in error
