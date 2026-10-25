"""Focused Geometry measure contracts with explicit native S2 mocks."""
from __future__ import annotations

import math

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_measures import (
    GEOMETRY_MEASURE_ARGUMENTS,
    _CENTROID_OUTPUT_WORK,
    invoke_geometry_measures,
)
from gee.compat.earthengine.geometry_preflight import MAX_GEOMETRY_WORK
from gee.compat.earthengine.spherical_measures import (
    centroid_lon_lat,
    decode_measure_record,
)
from gee.ee_translate import UnsupportedEEError


def translator(steps=0):
    value = Translator([], {}, {})
    value.steps = steps
    return value


def square(x0=0.0, y0=0.0, size=1.0, *, geodesic=False):
    return {
        "type": "Polygon",
        "coordinates": [[
            [x0, y0], [x0 + size, y0], [x0 + size, y0 + size],
            [x0, y0 + size], [x0, y0],
        ]],
        "geodesic": geodesic,
    }


def planar_call(method, geometry, **options):
    return invoke_geometry_measures(
        translator(), "Geometry." + method,
        {"geometry": geometry, "proj": "EPSG:4326", **options},
    )


def mock_ellipsoid(monkeypatch, value=123.0):
    from gee.compat.earthengine import spherical_native

    calls = []

    def run(geometry, method):
        calls.append((geometry, method))
        return 1.0, value

    monkeypatch.setattr(spherical_native, "run_ellipsoid_measure", run)
    return calls


def test_official_argument_names_defaults_and_exact_dispatch_contract():
    for method in ("area", "length", "perimeter", "centroid"):
        assert GEOMETRY_MEASURE_ARGUMENTS["Geometry." + method] == (
            frozenset({"geometry"}), frozenset({"maxError", "proj"}),
        )


@pytest.mark.parametrize("method, expected", [
    ("area", 2.0),
    ("length", 0.0),
    ("perimeter", 8.0),
])
def test_planar_multicomponent_measures_preserve_overlap_and_dimension(
        monkeypatch, method, expected):
    from gee.compat.earthengine import spherical_native

    monkeypatch.setattr(
        spherical_native, "run_ellipsoid_measure",
        lambda *_args: pytest.fail("explicit planar EPSG:4326 must use GEOS"),
    )
    multi = {
        "type": "MultiPolygon",
        "coordinates": [square(geodesic=False)["coordinates"]] * 2,
        "geodesic": False,
    }
    assert planar_call(method, multi) == expected


def test_planar_holes_component_perimeter_and_centroid_are_independent():
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
            [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]],
        ],
        "geodesic": False,
    }
    assert planar_call("area", polygon) == 12.0
    assert planar_call("perimeter", polygon) == 24.0
    assert planar_call("centroid", polygon)["coordinates"] == [2.0, 2.0]


def test_planar_mixed_dimensions_apply_method_specific_filters():
    geometry = {
        "type": "GeometryCollection",
        "geometries": [
            square(size=2, geodesic=False),
            {"type": "LineString", "coordinates": [[10, 0], [10, 3]],
             "geodesic": False},
            {"type": "Point", "coordinates": [30, 30]},
        ],
    }
    assert planar_call("area", geometry) == 4.0
    assert planar_call("length", geometry) == 3.0
    assert planar_call("perimeter", geometry) == 8.0
    assert planar_call("centroid", geometry)["coordinates"] == [1.0, 1.0]


def test_planar_duplicate_polygons_are_validated_atomically():
    duplicate = {
        "type": "MultiPolygon",
        "coordinates": [square(geodesic=False)["coordinates"]] * 2,
        "geodesic": False,
    }
    assert planar_call("area", duplicate) == 2.0

    invalid_ring = {
        "type": "MultiPolygon",
        "coordinates": [
            square(geodesic=False)["coordinates"],
            [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]],
        ],
        "geodesic": False,
    }
    with pytest.raises(UnsupportedEEError, match="invalid planar component"):
        planar_call("area", invalid_ring)


def test_default_geodesic_scalars_call_only_the_requested_ellipsoid_operation(monkeypatch):
    calls = mock_ellipsoid(monkeypatch)
    geometry = square(geodesic=True)
    for method in ("area", "length", "perimeter"):
        result = invoke_geometry_measures(
            translator(), "Geometry." + method, {"geometry": geometry},
        )
        assert result == 123.0
    assert [method for _, method in calls] == ["area", "length", "perimeter"]


def test_polygon_quadrature_precharge_matches_native_closed_ring_edge_count():
    from gee.compat.earthengine.ellipsoid_preflight import metric_native_work
    from gee.compat.earthengine.geometry_preflight import measure_geometry
    from gee.compat.earthengine.spherical_preflight import geometry_counts

    geometry = square(geodesic=True)
    positions, edges, active, parts = geometry_counts(geometry)
    base = ((positions + edges + 1) ** 2 * (active + 1)
            + positions ** 2 + 4 * edges + 4 * active + parts)
    assert measure_geometry(geometry).positions == 5
    assert metric_native_work(geometry, "area") == base + 56 * 4

    canonical_duplicate = {
        "type": "Polygon",
        "coordinates": [[[180, 0], [170, 1], [170, -1], [-180, 0]]],
        "geodesic": True,
    }
    positions, edges, active, parts = geometry_counts(canonical_duplicate)
    base = ((positions + edges + 1) ** 2 * (active + 1)
            + positions ** 2 + 4 * edges + 4 * active + parts)
    assert metric_native_work(canonical_duplicate, "perimeter") == base + 56 * 3

    from gee.compat.earthengine.spherical_wire import FULL_SPHERE

    assert metric_native_work(FULL_SPHERE, "area") == 7


def test_metric_operation_failure_or_malformed_record_does_not_fall_back(monkeypatch):
    from gee.compat.earthengine import spherical_native

    geometry = square(geodesic=True)
    calls = []

    def failed(_geometry, metric):
        calls.append(metric)
        raise UnsupportedEEError("native area integration failed")

    monkeypatch.setattr(spherical_native, "run_ellipsoid_measure", failed)
    with pytest.raises(UnsupportedEEError, match="native area integration failed"):
        invoke_geometry_measures(translator(), "Geometry.area", {"geometry": geometry})
    assert calls == ["area"]

    monkeypatch.setattr(spherical_native, "run_ellipsoid_measure",
                        lambda *_args: (1.0, math.nan))
    with pytest.raises(UnsupportedEEError, match="non-finite or negative"):
        invoke_geometry_measures(translator(), "Geometry.length", {"geometry": geometry})


@pytest.mark.parametrize("geometry, options, message", [
    (square(geodesic=False), {}, "cannot transform planar edges"),
    (square(geodesic=True), {"proj": "EPSG:4326"}, "cannot transform geodesic edges"),
    (square(geodesic=False), {"proj": "EPSG:3857"}, "other projections"),
])
def test_edge_model_changes_and_unproved_projections_reject(geometry, options, message):
    arguments = {"geometry": geometry, **options}
    with pytest.raises(UnsupportedEEError, match=message):
        invoke_geometry_measures(translator(), "Geometry.area", arguments)


def test_default_point_centroid_preserves_exact_coordinate_identity(monkeypatch):
    from gee.compat.earthengine import spherical_native

    monkeypatch.setattr(
        spherical_native, "run_measures",
        lambda *_args: pytest.fail("a Point centroid is its exact source point"),
    )
    source = {"type": "Point", "coordinates": [0.1, -0.2]}
    result = invoke_geometry_measures(
        translator(), "Geometry.centroid", {"geometry": source},
    )
    assert result["coordinates"] == [0.1, -0.2]
    assert result["coordinates"] is not source["coordinates"]
    source["coordinates"][0] = 90
    assert result["coordinates"] == [0.1, -0.2]


def test_default_all_identical_multipoint_centroid_uses_exact_source_value(monkeypatch):
    from gee.compat.earthengine import spherical_native

    monkeypatch.setattr(
        spherical_native, "run_measures",
        lambda *_args: pytest.fail("identical points have an exact source centroid"),
    )
    geometry = {"type": "MultiPoint", "coordinates": [[0.1, 0.2]] * 4}
    result = invoke_geometry_measures(
        translator(), "Geometry.centroid", {"geometry": geometry},
    )
    assert result["coordinates"] == [0.1, 0.2]


def test_spherical_centroid_uses_highest_dimension_and_exact_cancellation_fails(monkeypatch):
    from gee.compat.earthengine import spherical_native

    geometry = {
        "type": "GeometryCollection",
        "geometries": [
            square(geodesic=True),
            {"type": "Point", "coordinates": [150, 70]},
        ],
    }
    monkeypatch.setattr(
        spherical_native, "run_measures",
        lambda _geometry: (1.0, 2.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0),
    )
    result = invoke_geometry_measures(
        translator(), "Geometry.centroid", {"geometry": geometry},
    )
    assert result["coordinates"] == [0.0, 0.0]

    canceling = {
        "type": "MultiPoint", "coordinates": [[0, 0], [180, 0]],
    }
    monkeypatch.setattr(
        spherical_native, "run_measures",
        lambda _geometry: (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )
    with pytest.raises(UnsupportedEEError, match="weighted centroid cancels"):
        invoke_geometry_measures(
            translator(), "Geometry.centroid", {"geometry": canceling},
        )


def test_spherical_centroid_rejects_threefold_rounding_residual_but_keeps_resolved_vector(
        monkeypatch):
    from gee.compat.earthengine import spherical_native

    geometry = {
        "type": "MultiPoint", "coordinates": [[0, 0], [120, 0], [-120, 0]],
    }
    monkeypatch.setattr(
        spherical_native, "run_measures",
        lambda _geometry: (1.0, 0.0, 0.0, 0.0, 0.0, 4.4e-16, 0.0, 0.0),
    )
    with pytest.raises(UnsupportedEEError, match="numerically indeterminate"):
        invoke_geometry_measures(
            translator(), "Geometry.centroid", {"geometry": geometry},
        )

    monkeypatch.setattr(
        spherical_native, "run_measures",
        lambda _geometry: (1.0, 0.0, 0.0, 0.0, 0.0, 1e-8, 0.0, 0.0),
    )
    point = invoke_geometry_measures(
        translator(), "Geometry.centroid", {"geometry": geometry},
    )
    assert point["coordinates"] == [0.0, 0.0]


def test_zero_metrics_and_empty_centroid_have_explicit_results(monkeypatch):
    from gee.compat.earthengine import spherical_native

    monkeypatch.setattr(
        spherical_native, "run_ellipsoid_measure",
        lambda *_args: pytest.fail("point-only scalar measures are exactly zero"),
    )
    point = {"type": "Point", "coordinates": [1, 2]}
    for method in ("area", "length", "perimeter"):
        assert invoke_geometry_measures(
            translator(), "Geometry." + method, {"geometry": point},
        ) == 0.0
    empty = {"type": "GeometryCollection", "geometries": []}
    assert invoke_geometry_measures(
        translator(), "Geometry.area", {"geometry": empty},
    ) == 0.0
    with pytest.raises(UnsupportedEEError, match="highest-dimension component"):
        invoke_geometry_measures(
            translator(), "Geometry.centroid", {"geometry": empty},
        )


def test_exact_work_boundary_reaches_native_only_after_all_work_is_reserved(monkeypatch):
    from gee.compat.earthengine import spherical_native

    geometry = square(geodesic=True)
    baseline = translator()
    baseline_calls = []
    monkeypatch.setattr(
        spherical_native, "run_ellipsoid_measure",
        lambda _geometry, method: baseline_calls.append((method, baseline.steps)) or (1.0, 5.0),
    )
    assert invoke_geometry_measures(
        baseline, "Geometry.area", {"geometry": geometry},
    ) == 5.0
    required = baseline.steps
    assert baseline_calls == [("area", required)]

    exact = translator(MAX_GEOMETRY_WORK - required)
    exact_calls = []
    monkeypatch.setattr(
        spherical_native, "run_ellipsoid_measure",
        lambda _geometry, method: exact_calls.append((method, exact.steps)) or (1.0, 5.0),
    )
    assert invoke_geometry_measures(
        exact, "Geometry.area", {"geometry": geometry},
    ) == 5.0
    assert exact_calls == [("area", MAX_GEOMETRY_WORK)]
    assert exact.steps == MAX_GEOMETRY_WORK

    over = translator(MAX_GEOMETRY_WORK - required + 1)
    over_calls = []
    monkeypatch.setattr(
        spherical_native, "run_ellipsoid_measure",
        lambda *_args: over_calls.append(True) or (1.0, 5.0),
    )
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_geometry_measures(over, "Geometry.area", {"geometry": geometry})
    assert over_calls == []


@pytest.mark.parametrize("arguments, message", [
    ({}, "requires arguments"),
    ({"geometry": {"type": "Point", "coordinates": [0, 0]}, "other": 1},
     "Unsupported algorithm arguments"),
    ({"geometry": {"type": "Point", "coordinates": [0, 0]}, "maxError": True},
     "static ErrorMargin"),
])
def test_exact_argument_rejections_remain_visible(arguments, message):
    with pytest.raises(UnsupportedEEError, match=message):
        invoke_geometry_measures(translator(), "Geometry.area", arguments)


def test_op10_record_validation_allows_scalar_independent_canceling_centroid():
    record = decode_measure_record((1.0, 2.0, 3.0, 4.0, 0.0, 0.0, 0.0, 0.0))
    assert record.area_steradians == 3.0
    with pytest.raises(UnsupportedEEError, match="weighted centroid cancels"):
        centroid_lon_lat(record, dimension_positions=12, dimension_components=2)


def test_centroid_resolution_guard_rejects_cancellation_residual_without_snapping():
    indistinguishable = decode_measure_record(
        (1.0, 0.0, 0.0, 0.0, 0.0, 4.4e-16, 0.0, 0.0),
    )
    with pytest.raises(UnsupportedEEError, match="numerically indeterminate"):
        centroid_lon_lat(
            indistinguishable, dimension_positions=3, dimension_components=1,
        )

    resolved = decode_measure_record(
        (1.0, 0.0, 0.0, 0.0, 0.0, 1e-8, 0.0, 0.0),
    )
    assert centroid_lon_lat(
        resolved, dimension_positions=2, dimension_components=1,
    ) == (0.0, 0.0)


def test_fixed_centroid_output_reservation_is_a_static_point_shape():
    assert _CENTROID_OUTPUT_WORK == 115
