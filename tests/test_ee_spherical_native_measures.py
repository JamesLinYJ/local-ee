"""Bounded direct ABI checks for native S2 geometry measures."""
from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import sys

import pytest

from gee.compat.earthengine import spherical_native as native
from gee.compat.earthengine.spherical_wire import FULL_SPHERE, encode_geometry


EMPTY = {"type": "GeometryCollection", "geometries": []}


@pytest.fixture(autouse=True)
def use_explicit_test_artifact(monkeypatch):
    override = os.environ.get("LOCAL_EE_TEST_S2_MEASURES_ARTIFACT")
    if override is None:
        return
    artifact = Path(override).expanduser()
    if not artifact.is_absolute():
        artifact = Path.cwd() / artifact
    library = "liblocal_ee_s2.dylib" if sys.platform == "darwin" else "liblocal_ee_s2.so"
    if (artifact.is_symlink() or not artifact.is_dir()
            or (artifact / "manifest.json").is_symlink()
            or not (artifact / "manifest.json").is_file()
            or (artifact / library).is_symlink()
            or not (artifact / library).is_file()):
        pytest.fail("LOCAL_EE_TEST_S2_MEASURES_ARTIFACT is not a complete artifact directory")
    if native._LOADED is not None:
        loaded_library = next((path for path in native._LOADED[0]
                               if path.name == library), None)
        if loaded_library is None or loaded_library.parent != artifact:
            pytest.fail("Run S2 measure tests in a fresh process for the explicit artifact")
    monkeypatch.setattr(native, "ARTIFACT_DIR", artifact)


def point(longitude, latitude):
    return {"type": "Point", "coordinates": [longitude, latitude]}


def line(*positions):
    return {"type": "LineString", "coordinates": [list(position) for position in positions]}


def polygon(rings, *, even_odd=True):
    return {"type": "Polygon", "coordinates": rings, "evenOdd": even_odd}


OCTANT_RING = [[0, 0], [90, 0], [0, 90], [0, 0]]
OCTANT = polygon([OCTANT_RING])
WGS84_A = 6_378_137.0
WGS84_F = 1 / 298.257223563


def raw_call_wire(wire, *, operation=10, capacity=8):
    function = native._load()
    left = (ctypes.c_double * len(wire))(*wire)
    empty = (ctypes.c_double * 2)(1, 0)
    output = (ctypes.c_double * (capacity + 2))()
    output[capacity], output[capacity + 1] = 7654.0, 8765.0
    size = ctypes.c_size_t(999)
    error = ctypes.create_string_buffer(256)
    code = function(operation, left, len(wire), empty, 2, output, capacity,
                    ctypes.byref(size), error, len(error))
    assert (output[capacity], output[capacity + 1]) == (7654.0, 8765.0)
    return code, size.value, list(output[:capacity]), error.value.decode()


def measure(geometry):
    code, size, output, error = raw_call_wire(encode_geometry(geometry))
    assert code == 0, error
    assert size == 8
    assert output[0] == 1
    return output


def measure_wgs84(geometry, *, operation):
    code, size, output, error = raw_call_wire(
        encode_geometry(geometry), operation=operation,
    )
    assert code == 0, error
    assert size == 2
    assert output[0] == 1
    return output[:size]


def _unit(longitude, latitude):
    longitude, latitude = map(math.radians, (longitude, latitude))
    return (math.cos(latitude) * math.cos(longitude),
            math.cos(latitude) * math.sin(longitude), math.sin(latitude))


def _dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def _cross(left, right):
    return (left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0])


def _triangle_area(vertices):
    first, second, third = map(lambda position: _unit(*position), vertices)
    determinant = abs(_dot(first, _cross(second, third)))
    denominator = 1 + _dot(first, second) + _dot(second, third) + _dot(third, first)
    return 2 * math.atan2(determinant, denominator)


def _triangle_perimeter(vertices):
    points = [tuple(_unit(*position)) for position in vertices]
    return sum(math.atan2(
        math.hypot(*_cross(points[i], points[(i + 1) % 3])),
        _dot(points[i], points[(i + 1) % 3]),
    ) for i in range(3))


def _wgs84_surface_area():
    eccentricity = math.sqrt(WGS84_F * (2 - WGS84_F))
    return 2 * math.pi * WGS84_A**2 * (
        1 + (1 - eccentricity**2) / eccentricity * math.atanh(eccentricity)
    )


def _wgs84_meridian_quadrant():
    eccentricity_squared = WGS84_F * (2 - WGS84_F)
    series = 1.0
    for n in range(1, 12):
        central_binomial = math.comb(2 * n, n) / (4**n)
        series -= (central_binomial**2 * eccentricity_squared**n
                   / (2 * n - 1))
    return WGS84_A * math.pi / 2 * series


def test_empty_and_full_sphere_have_explicit_dimension_and_measures():
    empty = measure(EMPTY)
    assert empty == [1.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    full = measure(FULL_SPHERE)
    assert full[1] == 2
    assert full[2:5] == pytest.approx([4 * math.pi, 0.0, 0.0], abs=1e-14)
    assert full[5:] == [0.0, 0.0, 0.0]


def test_point_centroid_counts_repeated_original_positions():
    result = measure({"type": "MultiPoint", "coordinates": [[0, 0], [90, 0], [90, 0]]})
    assert result[1:5] == [0, 0.0, 0.0, 0.0]
    assert result[5:] == pytest.approx([1.0, 2.0, 0.0], abs=2e-15)


def test_exact_antipodal_points_cancel_without_an_epsilon():
    result = measure({"type": "MultiPoint", "coordinates": [[0, 0], [180, 0]]})
    assert result[1] == 0
    assert result[5:] == [0.0, 0.0, 0.0]


def test_exact_antipodal_lines_cancel_and_still_sum_length():
    result = measure({"type": "GeometryCollection", "geometries": [
        line((0, 0), (90, 0)),
        line((180, 0), (-90, 0)),
    ]})
    assert result[1] == 1
    assert result[3] == pytest.approx(math.pi, abs=2e-15)
    assert result[5:] == pytest.approx([0.0, 0.0, 0.0], abs=2e-14)


def test_opposite_oriented_polygon_pair_cancels_centroid_without_union():
    complement = polygon([list(reversed(OCTANT_RING))], even_odd=False)
    result = measure({"type": "GeometryCollection", "geometries": [
        OCTANT, complement,
    ]})
    assert result[1] == 2
    assert result[2] == pytest.approx(4 * math.pi, abs=2e-14)
    assert result[4] == pytest.approx(3 * math.pi, abs=2e-14)
    assert result[5:] == pytest.approx([0.0, 0.0, 0.0], abs=2e-14)


def test_near_antipodal_points_keep_their_small_nonzero_centroid():
    result = measure({
        "type": "MultiPoint",
        "coordinates": [[0, 0], [180 - 1e-10, 0]],
    })
    centroid = result[5:]
    assert math.isfinite(math.hypot(*centroid[:2]))
    assert 0 < math.hypot(*centroid[:2]) < 1e-10


def test_line_uses_great_circle_length_and_length_weighted_centroid():
    result = measure(line((-10, 0), (10, 0)))
    assert result[1] == 1
    assert result[2] == 0
    assert result[3] == pytest.approx(math.radians(20), abs=2e-15)
    assert result[4] == 0
    assert result[5:] == pytest.approx([2 * math.sin(math.radians(10)), 0.0, 0.0],
                                        abs=2e-15)


@pytest.mark.parametrize("vertices", [
    [(0, 0), (90, 0), (0, 90)],
    [(179, 0), (-179, 0), (180, 2)],
    [(0, 80), (120, 80), (-120, 80)],
])
def test_triangle_area_and_perimeter_match_independent_spherical_reference(vertices):
    ring = [*vertices, vertices[0]]
    result = measure(polygon([ring]))
    assert result[1] == 2
    assert result[2] == pytest.approx(_triangle_area(vertices), rel=2e-14, abs=2e-15)
    assert result[3] == 0
    assert result[4] == pytest.approx(_triangle_perimeter(vertices), rel=2e-14, abs=2e-15)


def test_reversed_oriented_loop_preserves_large_spherical_interior():
    reversed_ring = list(reversed(OCTANT_RING))
    result = measure(polygon([reversed_ring], even_odd=False))
    assert result[1] == 2
    assert result[2] == pytest.approx(4 * math.pi - math.pi / 2, abs=2e-14)
    assert result[4] == pytest.approx(3 * math.pi / 2, abs=2e-14)
    # The full sphere contributes zero, so the oriented complement has the
    # negated octant centroid integral (each component is -pi/4).
    assert result[5:] == pytest.approx([-math.pi / 4] * 3, abs=2e-14)


def test_hole_subtracts_area_and_centroid_but_adds_boundary_perimeter():
    outer = OCTANT_RING
    inner = [[10, 10], [20, 10], [10, 20]]
    result = measure(polygon([outer, [*inner, inner[0]]]))
    inner_area = _triangle_area(inner)
    inner_perimeter = _triangle_perimeter(inner)
    assert result[1] == 2
    assert result[2] == pytest.approx(math.pi / 2 - inner_area, abs=2e-14)
    assert result[4] == pytest.approx(3 * math.pi / 2 + inner_perimeter, abs=2e-14)
    assert result[5:] == pytest.approx(
        [math.pi / 4 - value for value in measure(polygon([[*inner, inner[0]]]))[5:]],
        abs=2e-14,
    )


def test_overlapping_polygon_records_are_summed_without_union():
    result = measure({"type": "GeometryCollection", "geometries": [OCTANT, OCTANT]})
    assert result[1] == 2
    assert result[2:5] == pytest.approx([math.pi, 0.0, 3 * math.pi], abs=2e-14)
    assert result[5:] == pytest.approx([math.pi / 2] * 3, abs=2e-14)


def test_centroid_uses_only_highest_dimension_but_other_measures_still_accumulate():
    result = measure({"type": "GeometryCollection", "geometries": [
        point(35, 20), line((0, 0), (10, 0)), OCTANT,
    ]})
    assert result[1] == 2
    assert result[2:5] == pytest.approx([math.pi / 2, math.radians(10), 3 * math.pi / 2],
                                         abs=2e-14)
    assert result[5:] == pytest.approx([math.pi / 4] * 3, abs=2e-14)


def test_polygon_centroid_cancellation_does_not_fail_scalar_measures():
    result = measure(FULL_SPHERE)
    assert result[2] == pytest.approx(4 * math.pi, abs=1e-14)
    assert result[4] == 0
    assert result[5:] == [0.0, 0.0, 0.0]


def test_invalid_component_and_native_work_overflow_fail_without_output():
    invalid = polygon([[[0, 0], [0, 0], [1, 1], [0, 0]]])
    code, size, _, error = raw_call_wire(encode_geometry(invalid))
    assert code != 0 and size == 0 and error
    for operation in (11, 12, 13):
        code, size, _, error = raw_call_wire(
            encode_geometry(invalid), operation=operation, capacity=2,
        )
        assert code != 0 and size == 0 and error

    points = {"type": "MultiPoint", "coordinates": [[i / 100, 0] for i in range(200)]}
    code, size, _, error = raw_call_wire(encode_geometry(points))
    assert code != 0 and size == 0 and "50000" in error


def test_measure_output_capacity_is_preflighted_and_canary_is_preserved():
    code, size, output, error = raw_call_wire([1, 1001], operation=10, capacity=7)
    assert code != 0 and size == 0
    assert output == [0.0] * 7
    assert "eight output doubles" in error


def test_wgs84_line_length_uses_meters_and_keeps_the_fixed_record():
    geometry = line((-10, 0), (10, 0))
    result = measure_wgs84(geometry, operation=12)
    assert result == pytest.approx(
        [1.0, 6_378_137.0 * math.radians(20)], rel=2e-14,
    )
    assert measure_wgs84(geometry, operation=11) == [1.0, 0.0]
    assert measure_wgs84(geometry, operation=13) == [1.0, 0.0]


@pytest.mark.parametrize("geometry", [EMPTY, point(0, 0)])
@pytest.mark.parametrize("operation", [11, 12, 13])
def test_wgs84_metrics_are_zero_for_empty_and_point_only_inputs(geometry, operation):
    assert measure_wgs84(geometry, operation=operation) == [1.0, 0.0]


def test_wgs84_full_component_multiplicity_and_cancellation():
    full_collection = {"type": "GeometryCollection", "geometries": [
        FULL_SPHERE, FULL_SPHERE,
    ]}
    result = measure_wgs84(full_collection, operation=11)
    assert result == pytest.approx([1.0, 2 * _wgs84_surface_area()], rel=2e-14)
    assert measure_wgs84(full_collection, operation=12) == [1.0, 0.0]
    assert measure_wgs84(full_collection, operation=13) == [1.0, 0.0]


def test_wgs84_octant_area_and_meridian_boundary_perimeter():
    geometry = polygon([[[0, 0], [90, 0], [90, 90], [0, 0]]])
    assert measure_wgs84(geometry, operation=11) == pytest.approx(
        [1.0, _wgs84_surface_area() / 8], rel=3e-13,
    )
    assert measure_wgs84(geometry, operation=12) == [1.0, 0.0]
    expected_perimeter = math.pi * WGS84_A / 2 + 2 * _wgs84_meridian_quadrant()
    assert measure_wgs84(geometry, operation=13) == pytest.approx(
        [1.0, expected_perimeter], rel=3e-13,
    )


@pytest.mark.parametrize("operation", [11, 12, 13])
def test_wgs84_measure_output_capacity_is_preflighted_and_canary_is_preserved(
    operation,
):
    code, size, output, error = raw_call_wire(
        [1, 1001], operation=operation, capacity=1,
    )
    assert code != 0 and size == 0
    assert output == [0.0]
    assert "two output doubles" in error


def test_wgs84_quadrature_work_is_reserved_before_geometry_construction():
    ring = [[-180 + 5 * index, 0] for index in range(72)]
    code, size, _, error = raw_call_wire(
        encode_geometry(polygon([ring])), operation=13, capacity=2,
    )
    assert code != 0 and size == 0
    assert "50000-work" in error
