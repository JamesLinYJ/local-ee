"""Default spherical and explicit planar semantics for Filter.intersects."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.feature_filters import validate_filter_structure
from gee.compat.earthengine.filtering import matches_filter
from gee.compat.earthengine.filter_metadata import matches_filter as matches_catalog_filter
from gee.compat.earthengine.geometry_values import decode_geometry_bounded
from gee.compat.earthengine.ir import Filter, UnsupportedEEError
from gee.ee_translate import compile_expression


def _translator(steps=0):
    result = Translator([], {}, {})
    result.steps = steps
    return result


def _feature_filter(arguments):
    return Filter("intersects", arguments)


def _point(longitude, latitude):
    return {"type": "Point", "coordinates": [longitude, latitude]}


def _matches(arguments, geometry, properties=None, translator=None):
    return matches_filter(
        translator or _translator(), _feature_filter(arguments),
        {"geometry": geometry, "properties": properties or {}},
    )


def test_default_dateline_and_polar_footprints_use_spherical_intersection():
    dateline = {
        "type": "Polygon",
        "coordinates": [[[170, -10], [-170, -10], [-170, 10],
                         [170, 10], [170, -10]]],
    }
    polar = {
        "type": "Polygon",
        "coordinates": [[[-135, 80], [-45, 80], [45, 80],
                         [135, 80], [-135, 80]]],
    }
    assert _matches({"leftField": ".all", "rightValue": dateline}, _point(179, 0))
    assert not _matches({"leftField": ".all", "rightValue": dateline}, _point(0, 0))
    assert _matches({"leftField": ".geo", "rightValue": polar}, _point(0, 90))
    assert not _matches({"leftField": ".geo", "rightValue": polar}, _point(0, 0))


def test_first_three_pinned_sdk_filter_bounds_wire_records_match_expected_rows():
    fixture_path = Path(__file__).parent / "fixtures/ee-spatial-consumers-wave63-before-v1.json"
    records = json.loads(fixture_path.read_text(encoding="utf-8"))["records"][:3]
    for record in records:
        result = compile_expression(record["wire"], [], {})["value"]
        assert result == record["expected"], record["name"]


def test_sdk_feature_literal_roi_preserves_its_geometry_and_rejects_null_geometry():
    row = _point(1, 1)
    roi = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon", "geodesic": False,
            "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
        },
        "properties": {},
    }
    assert _matches({"leftField": ".all", "rightValue": roi}, row)
    with pytest.raises(UnsupportedEEError, match="non-null geometry"):
        validate_filter_structure(_translator(), _feature_filter({
            "leftField": ".all", "rightValue": {"type": "Feature", "geometry": None,
                                                        "properties": {}},
        }))


def test_default_geodesic_edge_bows_while_explicit_planar_edge_stays_planar():
    polygon = {
        "type": "Polygon",
        "coordinates": [[[-60, 60], [60, 60], [60, 0], [-60, 0], [-60, 60]]],
    }
    probe = _point(0, 70)
    assert _matches({"leftValue": polygon, "rightField": ".geo"}, probe)
    planar = {**polygon, "geodesic": False}
    assert not _matches({"leftValue": planar, "rightField": ".geo"}, probe)


def test_property_geometry_and_swapped_operands_are_supported():
    row_geometry = _point(1, 2)
    roi = {"type": "Polygon", "geodesic": False,
           "coordinates": [[[0, 0], [2, 0], [2, 3], [0, 3], [0, 0]]]}
    assert _matches(
        {"leftValue": roi, "rightField": "site_geometry"}, None,
        {"site_geometry": row_geometry},
    )
    assert _matches({"leftField": ".geo", "rightValue": roi}, row_geometry)


def test_null_and_empty_geometry_rows_are_nonmatches_after_literal_preflight():
    roi = {"type": "Point", "coordinates": [0, 0]}
    filt = _feature_filter({"leftField": ".all", "rightValue": roi})
    for geometry in (None,):
        validate_filter_structure(_translator(), filt)
        assert not matches_filter(
            _translator(), filt, {"geometry": geometry, "properties": {}},
        )
    empty = {"type": "GeometryCollection", "geometries": []}
    assert not _matches({"leftField": ".all", "rightValue": roi}, empty)
    with pytest.raises(UnsupportedEEError, match="coordinates|GeoJSON|nonempty"):
        validate_filter_structure(
            _translator(), _feature_filter({
                "leftField": ".all", "rightValue": {"type": "LineString", "coordinates": []},
            }),
        )


@pytest.mark.parametrize("margin", [None, 0, 1, 1.0])
def test_official_static_max_error_margin_does_not_force_a_planar_route(margin):
    arguments = {"leftField": ".all", "rightValue": _point(0, 0), "maxError": margin}
    assert _matches(arguments, _point(0, 0))


@pytest.mark.parametrize("arguments", [
    {"leftField": ".all", "rightValue": {"type": "Point", "coordinates": [0, 0]},
     "unexpected": True},
    {"leftField": ".all", "leftValue": {"type": "Point", "coordinates": [0, 0]},
     "rightValue": {"type": "Point", "coordinates": [0, 0]}},
    {"leftField": ".all"},
    {"leftField": ".all", "rightValue": {"type": "Point", "coordinates": [0, 0]},
     "maxError": True},
])
def test_invalid_signature_or_reprojection_margin_fails_before_missing_row(arguments):
    with pytest.raises(UnsupportedEEError):
        _matches(arguments, None)


def test_missing_or_null_geometry_property_is_false_but_non_geometry_value_fails():
    roi = _point(0, 0)
    arguments = {"leftField": "site_geometry", "rightValue": roi}
    assert not _matches(arguments, None, {})
    assert not _matches(arguments, None, {"site_geometry": None})
    with pytest.raises(UnsupportedEEError, match="GeoJSON"):
        _matches(arguments, None, {"site_geometry": "not geometry"})


def test_spherical_filter_path_does_not_call_geos(monkeypatch):
    import shapely.geometry

    from gee.compat.earthengine import geometry_binary

    calls = []

    def reject_geos(value):
        calls.append(value)
        raise AssertionError("spherical Filter.intersects reached GEOS")

    monkeypatch.setattr(shapely.geometry, "shape", reject_geos)
    monkeypatch.setattr(geometry_binary, "shape", reject_geos)
    dateline = {
        "type": "Polygon",
        "coordinates": [[[170, -10], [-170, -10], [-170, 10],
                         [170, 10], [170, -10]]],
    }
    assert _matches({"leftField": ".geo", "rightValue": dateline}, _point(179, 0))
    assert calls == []


def test_explicit_planar_filter_uses_geos_after_preflight(monkeypatch):
    import shapely.geometry

    calls = []
    original = shapely.geometry.shape
    monkeypatch.setattr(shapely.geometry, "shape", lambda value: calls.append(value) or original(value))
    rectangle = {
        "type": "Polygon", "geodesic": False,
        "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
    }
    assert _matches({"leftField": ".geo", "rightValue": rectangle}, _point(1, 1))
    assert calls


def test_raw_catalog_geojson_footprints_keep_their_planar_model_without_mutation():
    footprint = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
    }
    original = json.loads(json.dumps(footprint))
    item = {"geometry": footprint, "properties": {}}
    planar_roi = {
        "type": "Polygon", "geodesic": False,
        "coordinates": [[[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]],
    }
    assert matches_catalog_filter(
        _translator(), _feature_filter({"leftField": ".all", "rightValue": planar_roi}), item,
    )
    assert footprint == original
    with pytest.raises(UnsupportedEEError, match="[Mm]ixed geodesic.*reprojection"):
        matches_catalog_filter(
            _translator(), _feature_filter({
                "leftField": ".all",
                "rightValue": {
                    "type": "Polygon",
                    "coordinates": [[[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]],
                },
            }),
            item,
        )


def test_catalog_point_roi_can_match_planar_catalog_polygon():
    footprint = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
    }
    item = {"geometry": footprint, "properties": {}}
    assert matches_catalog_filter(
        _translator(), _feature_filter({
            "leftField": ".all", "rightValue": _point(1, 1),
        }), item,
    )


def test_mixed_models_mutated_geometry_and_cyclic_literals_fail_closed():
    mixed = {
        "type": "GeometryCollection", "geometries": [
            {"type": "LineString", "geodesic": True,
             "coordinates": [[0, 0], [1, 1]]},
            {"type": "LineString", "geodesic": False,
             "coordinates": [[2, 2], [3, 3]]},
        ],
    }
    with pytest.raises(UnsupportedEEError, match="mixed|reprojection"):
        validate_filter_structure(
            _translator(), _feature_filter({"leftValue": mixed, "rightValue": _point(0, 0)}),
        )

    mutable = decode_geometry_bounded(_translator(), _point(0, 0))
    mutable["coordinates"][0] = 181
    with pytest.raises(UnsupportedEEError, match="longitude|bounds"):
        validate_filter_structure(
            _translator(), _feature_filter({"leftField": ".geo", "rightValue": mutable}),
        )

    cycle = {"type": "GeometryCollection", "geometries": []}
    cycle["geometries"].append(cycle)
    with pytest.raises(UnsupportedEEError, match="cycle|nesting"):
        validate_filter_structure(
            _translator(), _feature_filter({"leftField": ".geo", "rightValue": cycle}),
        )


def test_geometry_work_budget_is_reserved_before_spherical_validation(monkeypatch):
    from gee.compat.earthengine import spherical_native

    calls = []
    monkeypatch.setattr(spherical_native, "validate", lambda value: calls.append(value))
    filt = _feature_filter({
        "leftValue": {
            "type": "LineString",
            "coordinates": [[index / 100, 0] for index in range(2000)],
        },
        "rightValue": _point(0, 0),
    })
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        validate_filter_structure(_translator(48_000), filt)
    assert calls == []
