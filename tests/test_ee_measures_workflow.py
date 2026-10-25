"""Native-backed geometry/feature measure compilation and physical CSV readback."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from ee_measures_workflow import (
    METHOD_FOR_OPERATION,
    ROOT,
    expected_feature_id,
    load_fixture,
    load_feature_only_workflows_fixture,
    load_geometrycollection_workflow_fixture,
    planar_reference,
    physical_measurement_collection,
    require_exact_measure_artifact,
    spherical_centroid_coordinates,
    verify_frozen_wgs84_reference,
)
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import USER, install, run_batch
from ee_measure_reuse_reference import assert_full_value
from ee_measure_reuse_sdk import fixture as reuse_fixture


def _encoded(ee, value):
    return json.loads(json.dumps(ee.serializer.encode(value, for_cloud_api=False)))


def _value(ee, value):
    result = compile_expression(_encoded(ee, value), [], {})
    assert result["kind"] == "value"
    return result["value"]


def _assert_control(actual, expected, record):
    absolute = record["absolute_tolerance"]
    relative = record["relative_tolerance"]
    bound = max(absolute, relative * abs(expected))
    assert math.isfinite(float(actual))
    assert abs(float(actual) - expected) <= bound, (
        f"{record['id']}: expected {expected:.17g} within {bound:.9g}, got {actual!r}"
    )


def _point_geometry(value):
    if isinstance(value, dict):
        if value.get("type") == "Feature":
            return _point_geometry(value.get("geometry"))
        if value.get("type") == "Point":
            return value["coordinates"]
    raise AssertionError(f"Expected a computed point geometry, got {value!r}")


def _coordinates_property(record, name):
    value = json.loads(record[name])
    assert isinstance(value, list) and len(value) == 2
    return [float(value[0]), float(value[1])]


def _assert_coords(actual, expected, *, absolute=1e-11):
    assert actual == pytest.approx(expected, rel=0, abs=absolute)


def _export_and_read_csv(integration, collection, config, selectors):
    task = integration.ee.batch.Export.table.toDrive(
        collection=collection,
        description=config["description"],
        fileFormat="CSV",
        selectors=selectors,
    )
    task.start()
    result = run_batch(integration, task.id)
    assert result.row["status"] == "finished"

    from gee.backend import Jobs

    assets = Jobs().get_result_assets(task.id, USER)
    filename = config["description"] + ".csv"
    assert set(assets) == {filename}
    csv_path = Path(assets[filename]["href"])
    assert csv_path == result.job_dir / "out" / filename
    assert csv_path.is_file()
    with csv_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return rows


def test_frozen_wgs84_controls_match_compiled_geometry_measurements(monkeypatch):
    require_exact_measure_artifact(monkeypatch)
    controls = verify_frozen_wgs84_reference()
    from gee.ee_python_client import configure_local_ee

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        for record in controls:
            operation = record["operation"]
            method = METHOD_FOR_OPERATION[operation]
            geometry = ee.Geometry(record["geometry"])
            actual = _value(ee, getattr(geometry, method)())
            _assert_control(actual, record["expected"], record)
    assert guard.evidence()["attempt_count"] == 0


def test_empty_scalars_and_centroid_undefined_cases_are_independent(monkeypatch):
    require_exact_measure_artifact(monkeypatch)
    fixture = load_fixture()
    from gee.ee_python_client import configure_local_ee

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        empty_json = fixture["cases"]["empty"]["geometry"]
        empty_geometry = ee.Geometry(empty_json)
        empty_feature = ee.Feature({
            "type": "Feature", "id": "wave71-empty",
            "properties": {"label": "empty"}, "geometry": empty_json,
        })
        projection = ee.Projection("EPSG:4326")
        for owner in (empty_geometry, empty_feature):
            for method in ("area", "length", "perimeter"):
                values = (
                    getattr(owner, method)(),
                    getattr(owner, method)(maxError=None, proj=None),
                    getattr(owner, method)(proj=projection),
                )
                assert [_value(ee, value) for value in values] == [0, 0, 0]
        with pytest.raises(UnsupportedEEError, match="centroid"):
            _value(ee, empty_geometry.centroid())
        with pytest.raises(UnsupportedEEError, match="centroid"):
            _value(ee, empty_feature.centroid())

        antipodal_json = fixture["cases"]["antipodal_points_zero_centroid"]["geometry"]
        antipodal = ee.Geometry(antipodal_json)
        antipodal_feature = ee.Feature({
            "type": "Feature", "id": "wave71-antipodal",
            "properties": {}, "geometry": antipodal_json,
        })
        with pytest.raises(UnsupportedEEError, match="centroid"):
            _value(ee, antipodal.centroid())
        with pytest.raises(UnsupportedEEError, match="centroid"):
            _value(ee, antipodal_feature.centroid())

        near_json = fixture["cases"]["near_antipodal_points_nonzero_centroid"]["geometry"]
        near = ee.Geometry(near_json)
        near_result = _point_geometry(_value(ee, near.centroid()))
        near_expected = spherical_centroid_coordinates(near_json)
        _assert_coords(near_result, near_expected, absolute=2e-7)
        near_feature = ee.Feature({
            "type": "Feature", "id": "wave71-near-antipodal",
            "properties": {}, "geometry": near_json,
        })
        near_feature_result = _point_geometry(_value(ee, near_feature.centroid()))
        _assert_coords(near_feature_result, near_expected, absolute=2e-7)
    assert guard.evidence()["attempt_count"] == 0


@pytest.mark.parametrize(
    ("route", "fixture_variant"),
    [
        ("default_wgs84", "v2"),
        ("explicit_epsg4326_planar_geometrycollection_v3", "v3"),
    ],
    ids=("original-wgs84-full-formula", "planar-geometrycollection-full-formula"),
)
def test_preserved_full_metric_formulas_match_all_original_references(
        route, fixture_variant, monkeypatch):
    require_exact_measure_artifact(monkeypatch)
    fixture = load_feature_only_workflows_fixture(load_fixture())
    config = (
        fixture["physical_workflow_v2"][route]
        if fixture_variant == "v2"
        else fixture["physical_workflow_v3"]
    )
    if fixture_variant == "v3":
        assert route == config["route"]
    from gee.ee_python_client import configure_local_ee

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        collection = physical_measurement_collection(
            ee, fixture, route,
        )
        wire = _encoded(ee, collection)
        frozen = reuse_fixture()
        original = next(record for record in frozen["workflows"].values()
                        if record["route"] == route)
        assert wire == original["wire"]
        assert config["rows"] == original["config"]["rows"]
        assert_full_value(frozen, original, compile_expression(wire, [], {})["value"])

    assert guard.evidence()["attempt_count"] == 0


@pytest.mark.parametrize(
    "route_key",
    [
        "default_wgs84_feature_only",
        "explicit_epsg4326_planar_geometrycollection_feature_only",
    ],
    ids=("wgs84-feature-only", "planar-geometrycollection-feature-only"),
)
def test_feature_only_measure_map_reaches_physical_csv_and_worker_readback(
        route_key, tmp_path, monkeypatch):
    require_exact_measure_artifact(monkeypatch)
    fixture = load_feature_only_workflows_fixture(load_fixture())
    cases = fixture["cases"]
    config = fixture["physical_workflows_v4"][route_key]
    route = config["route"]
    selectors = config["csv_selectors"]

    with OfflineGuard() as guard:
        integration = install(monkeypatch, tmp_path)
        collection = physical_measurement_collection(
            integration.ee, fixture, route,
        )
        rows = _export_and_read_csv(integration, collection, config, selectors)

        names = config["input_features"]
        assert len(rows) == config["rows"] == len(names)
        assert list(rows[0]) == selectors
        assert [row["label"] for row in rows] == names
        for rank, (name, row) in enumerate(zip(names, rows, strict=True)):
            feature_id = expected_feature_id(name)
            assert row["system:index"] == feature_id
            assert row["feature_id"] == feature_id
            assert int(row["source_rank"]) == rank

            if config["metric_model"] == "default_wgs84":
                controls = {
                    record["id"]: record
                    for record in verify_frozen_wgs84_reference()
                }
                control_by_case = {
                    "octant_triangle": {
                        "area": "octant-area",
                        "perimeter": "octant-perimeter",
                    },
                    "equatorial_arc": {"length": "equator-quarter"},
                    "point": {},
                    "mixed_highest_dimension": {
                        "area": "octant-area",
                        "length": "equator-quarter",
                        "perimeter": "octant-perimeter",
                    },
                }
                expected = {method: 0.0 for method in (
                    "area", "length", "perimeter",
                )}
                for method, control_id in control_by_case[name].items():
                    record = controls[control_id]
                    expected[method] = record["expected"]
                suffix = "default"
            else:
                reference = planar_reference(cases[name]["geometry"])
                expected = {
                    "area": float(reference["area_square_degrees"]),
                    "length": float(reference["linear_length_degrees"]),
                    "perimeter": float(reference["polygon_perimeter_degrees"]),
                }
                suffix = "epsg4326"

            for method, reference_value in expected.items():
                actual = float(row[f"feature_{method}_{suffix}"])
                if config["metric_model"] == "default_wgs84" and reference_value:
                    _assert_control(
                        actual, reference_value,
                        controls[control_by_case[name][method]],
                    )
                else:
                    assert actual == pytest.approx(
                        reference_value, rel=1e-12, abs=1e-12,
                    ), (name, method, config["metric_model"])

            centroid_property = _coordinates_property(
                row, f"feature_centroid_{suffix}",
            )
            if config["metric_model"] == "default_wgs84":
                expected_centroid = spherical_centroid_coordinates(
                    cases[name]["geometry"],
                )
            else:
                expected_centroid = planar_reference(cases[name]["geometry"])[
                    "centroid_lon_lat_degrees"
                ]
            _assert_coords(centroid_property, expected_centroid, absolute=2e-10)
            output_geometry = json.loads(row[".geo"])
            assert output_geometry["type"] == "Point"
            _assert_coords(output_geometry["coordinates"], expected_centroid)

    assert guard.evidence()["attempt_count"] == 0
