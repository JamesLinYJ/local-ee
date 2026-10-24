"""Direct ABI and bridge checks for bounded native S2 envelopes."""
from __future__ import annotations

import ctypes
from itertools import permutations
import os
from pathlib import Path
import sys

import pytest

from gee.compat.earthengine import spherical_native as native
from gee.compat.earthengine.spherical_envelope import Envelope, decode_envelope
from gee.compat.earthengine.spherical_wire import FULL_SPHERE, encode_geometry


EMPTY = {"type": "GeometryCollection", "geometries": []}


@pytest.fixture(autouse=True)
def use_explicit_test_artifact(monkeypatch):
    override = os.environ.get("LOCAL_EE_TEST_S2_BOUNDS_ARTIFACT")
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
        pytest.fail("LOCAL_EE_TEST_S2_BOUNDS_ARTIFACT is not a complete artifact directory")
    if native._LOADED is not None:
        loaded_library = next((path for path in native._LOADED[0]
                               if path.name == library), None)
        if loaded_library is None or loaded_library.parent != artifact:
            pytest.fail("Run S2 bounds tests in a fresh process for the explicit artifact")
    monkeypatch.setattr(native, "ARTIFACT_DIR", artifact)


def point(longitude, latitude):
    return {"type": "Point", "coordinates": [longitude, latitude]}


def line(*positions):
    return {"type": "LineString", "coordinates": [list(p) for p in positions]}


def longitude_width(envelope):
    if envelope.full_longitude:
        return 360.0
    return (360.0 - envelope.west + envelope.east
            if envelope.wrapped else envelope.east - envelope.west)


def polygon(ring):
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def unit(longitude, latitude):
    from math import cos, radians, sin

    longitude, latitude = radians(longitude), radians(latitude)
    return (cos(latitude) * cos(longitude), cos(latitude) * sin(longitude),
            sin(latitude))


def slerp_samples(first, second, steps=256):
    from math import acos, cos, sin, sqrt

    a, b = unit(*first), unit(*second)
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))
    angle = acos(dot)
    sine = sin(angle)
    for step in range(steps + 1):
        t = step / steps
        if sine == 0:
            vector = a
        else:
            left, right = sin((1 - t) * angle) / sine, sin(t * angle) / sine
            vector = tuple(left * x + right * y for x, y in zip(a, b))
        norm = sqrt(sum(value * value for value in vector))
        yield tuple(value / norm for value in vector)


def assert_contains(envelope, point3):
    from math import atan2, degrees, hypot

    longitude = degrees(atan2(point3[1], point3[0]))
    latitude = degrees(atan2(point3[2], hypot(point3[0], point3[1])))
    if not envelope.full_longitude:
        if envelope.wrapped:
            assert longitude >= envelope.west - 1e-11 or longitude <= envelope.east + 1e-11
        else:
            assert envelope.west - 1e-11 <= longitude <= envelope.east + 1e-11
    assert envelope.south - 1e-11 <= latitude <= envelope.north + 1e-11


def raw_call(value, *, capacity=8):
    function = native._load()
    wire = encode_geometry(value)
    left = (ctypes.c_double * len(wire))(*wire)
    empty = (ctypes.c_double * 2)(1, 0)
    output = (ctypes.c_double * (capacity + 1))()
    output[capacity] = 918273.0
    size = ctypes.c_size_t(999)
    error = ctypes.create_string_buffer(256)
    code = function(9, left, len(wire), empty, 2, output, capacity,
                    ctypes.byref(size), error, len(error))
    assert output[capacity] == 918273.0
    return code, size.value, list(output[:capacity]), error.value.decode()


def test_bounds_opcode_returns_fixed_eight_double_abi_record():
    code, size, output, error = raw_call(point(12.5, -6.25))
    assert code == 0, error
    assert size == 8
    assert output[0:4] == [1.0, 0.0, 0.0, 0.0]
    assert output[4:] == pytest.approx([12.5, -6.25, 12.5, -6.25], abs=1e-13)


def test_bounds_reply_rejects_short_capacity_without_writing_past_it():
    code, size, output, error = raw_call(point(1, 2), capacity=7)
    assert code != 0 and size == 0 and error
    assert output == [0.0] * 7


def test_small_polygon_bound_is_tight_instead_of_an_s2_cell_cover():
    result = native.run("bounds", polygon([[0, 0], [0.001, 0], [0.001, 0.001], [0, 0.001]]))
    assert isinstance(result, Envelope)
    assert result.empty is False
    assert result.full_longitude is False
    assert result.wrapped is False
    assert -0.01 < result.west <= 0.0
    assert 0.001 <= result.east < 0.01
    assert -0.01 < result.south <= 0.0
    assert 0.001 <= result.north < 0.01


def test_dateline_arc_uses_wrapped_longitude_interval():
    result = native.run("bounds", line((170, 0), (-170, 0)))
    assert result.wrapped is True
    assert result.full_longitude is False
    assert result.west == pytest.approx(170, abs=1e-13)
    assert result.east == pytest.approx(-170, abs=1e-13)
    assert result.south == pytest.approx(0, abs=1e-13)
    assert result.north == pytest.approx(0, abs=1e-13)


def test_great_circle_arc_bound_includes_interior_latitude_extremum():
    result = native.run("bounds", line((0, 80), (90, 80)))
    assert result.north > 80
    assert result.north < 84
    for sample in slerp_samples((0, 80), (90, 80)):
        assert_contains(result, sample)


def test_dateline_envelope_contains_independent_slerp_samples():
    endpoints = (170, 10), (-160, 30)
    result = native.run("bounds", line(*endpoints))
    assert result.wrapped is True
    for sample in slerp_samples(*endpoints):
        assert_contains(result, sample)


@pytest.mark.parametrize("kind", ["MultiLineString", "GeometryCollection"])
def test_component_bounds_use_global_minimum_longitude_interval_in_any_order(kind):
    longitudes = (-100, 0, 100)
    envelopes = []
    for order in permutations(longitudes):
        lines = [line((longitude, 0), (longitude, 1))
                 for longitude in order]
        if kind == "MultiLineString":
            geometry = {"type": kind, "coordinates": [
                component["coordinates"] for component in lines
            ]}
        else:
            geometry = {"type": kind, "geometries": lines}
        envelopes.append(native.run("bounds", geometry))

    for result in envelopes:
        assert result.full_longitude is False
        assert result.wrapped is False
        assert result.west == pytest.approx(-100, abs=1e-10)
        assert result.east == pytest.approx(100, abs=1e-10)
        assert longitude_width(result) == pytest.approx(200, abs=1e-10)
    assert all(result.west == envelopes[0].west
               and result.east == envelopes[0].east for result in envelopes)


def test_multipoint_bounds_use_global_circular_interval_in_any_order():
    coordinates = {0: [0, 0], 170: [170, 1], -100: [-100, 2]}
    envelopes = [native.run("bounds", {"type": "MultiPoint", "coordinates": [
        coordinates[longitude] for longitude in order
    ]}) for order in permutations(coordinates)]

    for result in envelopes:
        assert result.full_longitude is False
        assert result.wrapped is True
        assert result.west == pytest.approx(170, abs=1e-10)
        assert result.east == pytest.approx(0, abs=1e-10)
        assert longitude_width(result) == pytest.approx(190, abs=1e-10)
    assert all(result.west == envelopes[0].west
               and result.east == envelopes[0].east for result in envelopes)


@pytest.mark.parametrize("longitudes", [
    (0.0, 1e-15),
    (-1e-15, 0.0, 1e-15),
    (0.0, 1e-14),
])
def test_tight_multipoint_bounds_preserve_sub_pi_ulp_longitude_differences(
        longitudes):
    result = native.run("bounds", {"type": "MultiPoint", "coordinates": [
        [longitude, 0] for longitude in longitudes
    ]})

    assert result.west == pytest.approx(min(longitudes), abs=1e-20)
    assert result.east == pytest.approx(max(longitudes), abs=1e-20)
    assert result.east > result.west


def test_equal_gap_tie_is_deterministic_for_permuted_multipoints():
    longitudes = (-120, 0, 120)
    envelopes = [native.run("bounds", {"type": "MultiPoint", "coordinates": [
        [longitude, 0] for longitude in order
    ]}) for order in permutations(longitudes)]
    first = envelopes[0]

    assert longitude_width(first) == pytest.approx(240, abs=1e-10)
    assert all(result == first for result in envelopes)


def test_antimeridian_endpoint_canonicalization_preserves_small_intervals():
    from_east = native.run("bounds", {"type": "MultiPoint", "coordinates": [
        [100, 0], [180, 0],
    ]})
    from_west = native.run("bounds", {"type": "MultiPoint", "coordinates": [
        [-100, 0], [180, 0],
    ]})
    boundary_point = native.run("bounds", point(180, 0))

    assert from_east.wrapped is False
    assert from_east.west == pytest.approx(100, abs=1e-10)
    assert from_east.east == 180
    assert longitude_width(from_east) == pytest.approx(80, abs=1e-10)
    assert from_west.wrapped is False
    assert from_west.west == -180
    assert from_west.east == pytest.approx(-100, abs=1e-10)
    assert longitude_width(from_west) == pytest.approx(80, abs=1e-10)
    assert (boundary_point.west, boundary_point.east,
            longitude_width(boundary_point)) == (-180, -180, 0)


def test_pole_containment_expands_to_full_longitude():
    north_cap = polygon([[-135, 80], [-45, 80], [45, 80], [135, 80]])
    result = native.run("bounds", north_cap)
    assert result.full_longitude is True
    assert result.wrapped is False
    assert result.west == -180
    assert result.east == 180
    assert result.north == pytest.approx(90, abs=1e-13)
    assert result.south > 70


def test_envelope_uses_normalized_union_of_polygon_and_point_components():
    collection = {"type": "GeometryCollection", "geometries": [
        polygon([[0, 0], [1, 0], [1, 1], [0, 1]]), point(20, 20),
    ]}
    result = native.run("bounds", collection)
    assert result.west < 0.01
    assert result.east > 19.99
    assert result.south < 0.01
    assert result.north > 19.99


def test_empty_and_full_sphere_have_explicit_raw_envelope_records():
    empty_code, empty_size, empty, error = raw_call(EMPTY)
    assert empty_code == 0, error
    assert empty_size == 8
    assert empty == [1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert native.run("bounds", EMPTY) == Envelope(True, False, False, 0, 0, 0, 0)

    result = native.run("bounds", FULL_SPHERE)
    assert result.empty is False
    assert result.full_longitude is True
    assert result.wrapped is False
    assert (result.west, result.south, result.east, result.north) == (-180, -90, 180, 90)


@pytest.mark.parametrize("values", [
    [1, 0, 0, 0, 0, 0, 0],
    [2, 0, 0, 0, 0, 0, 0, 0],
    ["1", 0, 0, 0, 0, 0, 0, 0],
    [True, 0, 0, 0, 0, 0, 0, 0],
    [1, 0, 0.5, 0, 0, 0, 0, 0],
    [1, 0, 1, 1, -180, -90, 180, 90],
    [1, 1, 0, 0, 0, 1, 0, 0],
    [1, 0, 0, 1, 5, -90, 10, 90],
    [1, 0, 1, 0, -179, -90, 179, 90],
    [1, 0, 0, 0, -180, -90, 180, 90],
    [1, 0, 0, 0, -90, -90, 90, 0],
])
def test_envelope_decoder_rejects_malformed_flags_and_coordinates(values):
    with pytest.raises(Exception):
        decode_envelope(values)
