"""Default spherical Geometry/Feature behavior through both official SDKs."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from ee_spherical_workflow_helpers import (
    OPERATIONS,
    OVERLAYS,
    ROOT,
    compile_outputs,
    json_wire,
    load_example,
    load_fixture,
    python_expressions,
    javascript_expressions,
    javascript_roundtrip,
    max_coordinate_error_degrees,
    root_invocation,
    semantic,
    spherical_contains,
    spherical_ring_area,
    verify_baseline_rejects,
)
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.compat.earthengine.ir import UnsupportedEEError
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import USER, install, run_batch


def _output(compiled, family, name):
    value = compiled[family][name]
    assert value["kind"] == "value"
    return value["value"]


def _point(region, coordinates):
    return spherical_contains(region, coordinates)


def _boolean_algebra(name, left, right):
    if name == "intersection":
        return left and right
    if name == "union":
        return left or right
    if name == "difference":
        return left and not right
    if name == "symmetricDifference":
        return left != right
    raise AssertionError(name)


def _root_argument_maps(expressions):
    for family in ("geometry", "feature"):
        assert set(expressions[family]) == set(OPERATIONS)
        for name, expression in expressions[family].items():
            invocation = root_invocation(expression)
            assert invocation["functionName"] == f"{family.capitalize()}.{name}"
            assert set(invocation["arguments"]) == {"left", "right"}
    for family in ("geometry", "feature"):
        for name, expression in expressions[family].items():
            # Both SDKs serialize omitted proj and explicit proj=None as the
            # actual default call. Neither inserts a CRS or edge rewrite.
            invocation = root_invocation(expression)
            assert "proj" not in invocation["arguments"]
            assert "maxError" not in invocation["arguments"]


def _root_null_argument_maps(expressions):
    for family in ("geometry", "feature"):
        for name, expression in expressions[family].items():
            invocation = root_invocation(expression)
            assert invocation["functionName"] == f"{family.capitalize()}.{name}"
            assert set(invocation["arguments"]) in (
                {"left", "right"}, {"left", "right", "proj"},
            )
            if "proj" in invocation["arguments"]:
                assert invocation["arguments"]["proj"] is None
            assert "maxError" not in invocation["arguments"]


def _assert_default_polygon_wire(expressions):
    for expression in (
        *expressions["geometry"].values(), *expressions["feature"].values(),
        *expressions["probes"].values(), *expressions["boundary"].values(),
    ):
        for _key, value in expression.get("scope", []):
            if isinstance(value, dict) and value.get("type") == "Polygon":
                assert "crs" not in value
                assert "geodesic" not in value
                assert value.get("evenOdd") is True or value.get("evenOdd") is False


def test_pinned_python_and_javascript_default_workflows_serialize_the_same_16_methods():
    fixture = load_fixture()
    baseline_digest = verify_baseline_rejects()
    assert baseline_digest == "913eeb8527b350550ca680db6569f10b6b5e9ecfbea561a7bcdf7976e6461541"
    python = python_expressions(fixture)
    javascript = javascript_expressions(fixture)
    for client in (python, javascript):
        _root_argument_maps(client["omitted"])
        _root_null_argument_maps(client["null"])
        _assert_default_polygon_wire(client["omitted"])

    assert semantic(python["omitted"]) == semantic(javascript["omitted"])


def test_omitted_and_null_projection_compile_to_same_16_default_results():
    fixture = load_fixture()
    python = python_expressions(fixture)
    javascript = javascript_expressions(fixture)
    python_outputs = compile_outputs(python["omitted"])
    javascript_outputs = compile_outputs(javascript["omitted"])
    assert semantic(python_outputs) == semantic(javascript_outputs)
    # Null is a real supported default wire form too; compile every geometry
    # and Feature operation through each SDK's serializer output.
    for client in (python, javascript):
        null_outputs = compile_outputs(client["null"])
        assert semantic(null_outputs) == semantic(python_outputs)

    assert {name: _output(python_outputs, "geometry", name) for name in
            ("contains", "containedIn", "disjoint", "intersects")} == fixture["expected"]["binary"]
    assert {name: _output(python_outputs, "feature", name) for name in
            ("contains", "containedIn", "disjoint", "intersects")} == fixture["expected"]["feature_binary"]


def test_independent_unit_vector_winding_checks_dateline_polar_holes_and_orientation():
    fixture = load_fixture()
    regions = fixture["regions"]
    region_by_probe = {
        "dateline_inside": "dateline_left", "dateline_other_side": "dateline_left",
        "polar_cap_inside": "polar_cap", "polar_cap_outside": "polar_cap",
        "hole_shell_inside": "with_hole", "hole_center_outside": "with_hole",
        "oriented_left_inside": "oriented_left",
        "oriented_reversed_outside": "oriented_reversed",
        "oriented_reversed_complement": "oriented_reversed",
    }
    for name, probe in fixture["probes"].items():
        expected = probe["expected"]
        geometry_name = region_by_probe[name]
        assert _point(regions[geometry_name], probe["point"]) is expected


def test_compiler_probe_outputs_match_independent_spherical_membership():
    fixture = load_fixture()
    outputs = compile_outputs(python_expressions(fixture)["omitted"])
    for name, probe in fixture["probes"].items():
        assert _output(outputs, "probes", name) is probe["expected"]


def test_independent_triangle_excess_reference_matches_an_octant():
    # Three quarter-circle great-circle arcs bound exactly one eighth of a
    # unit sphere. This sanity-checks the reference without S2 or GEOS.
    octant = [[0, 0], [90, 0], [0, 90], [0, 0]]
    assert spherical_ring_area(octant) == pytest.approx(math.pi / 2)
    assert spherical_ring_area(list(reversed(octant))) == pytest.approx(-math.pi / 2)


def test_overlay_results_obey_independent_spherical_probe_set_algebra_and_keep_features():
    fixture = load_fixture()
    python = python_expressions(fixture)["omitted"]
    outputs = compile_outputs(python)
    regions = fixture["regions"]
    probes = {"dateline_inner": [179, 0], "outside_inner": [172, 0], "opposite": [0, 0]}

    for name in OVERLAYS:
        geometry = _output(outputs, "geometry", name)
        feature = _output(outputs, "feature", name)
        assert feature["type"] == "Feature"
        assert feature["properties"] == {
            **fixture["features"]["left_properties"],
            "system:index": fixture["features"]["left_id"],
        }
        for label, point in probes.items():
            left = _point(regions["dateline_left"], point)
            right = _point(regions["dateline_right"], point)
            expected = _boolean_algebra(name, left, right)
            assert _point(geometry, point) is expected
            assert _point(feature, point) is expected
            assert fixture["expected"]["overlay_probes"][name][label] is expected

    assert outputs["feature_overlays"]["kind"] == "value"
    rows = outputs["feature_overlays"]["value"]["features"]
    assert len(rows) == len(OVERLAYS)
    for row, name in zip(rows, OVERLAYS, strict=True):
        assert row["properties"]["system:index"] == f"{fixture['features']['left_id']}-{name}"
        assert row["properties"]["owner"] == "left"
        assert row["properties"]["priority"] == 7
        assert "id" not in row or row["id"] == fixture["features"]["left_id"] + "-" + name


def test_exact_boundary_point_line_and_empty_results_keep_their_actual_dimensions():
    fixture = load_fixture()
    outputs = compile_outputs(python_expressions(fixture)["omitted"])
    expected = fixture["expected"]["boundary"]
    boundary = {name: _output(outputs, "boundary", name) for name in outputs["boundary"]}
    assert boundary["point_intersects"] is expected["point_intersects"]
    assert boundary["line_intersects"] is expected["line_intersects"]
    assert boundary["intersection_line"]["type"] == expected["intersection_line_type"]
    line = boundary["intersection_line"]["coordinates"]
    # Exact meridian geometry gives endpoints [2,0] and [2,2]. S2's binary64
    # XYZ conversion may perturb this newly generated crossing by a few ulps.
    reference = [[2.0, 0.0], [2.0, 2.0]]
    tolerance = 2e-14
    assert len(line) == 2 and all(len(point) == 2 for point in line)
    assert all(math.isfinite(value) for point in line for value in point)
    assert all(abs(point[0] - 2) <= tolerance for point in line)
    assert all(-tolerance <= point[1] <= 2 + tolerance for point in line)
    max_error = min(
        max_coordinate_error_degrees(line, reference),
        max_coordinate_error_degrees(line, list(reversed(reference))),
    )
    assert max_error <= tolerance
    assert boundary["intersection_point"]["type"] == expected["intersection_point_type"]
    assert boundary["intersection_point"]["coordinates"] == fixture["regions"]["boundary_point"]["coordinates"]
    assert boundary["empty_intersection"]["type"] == "GeometryCollection"
    assert boundary["empty_intersection"]["geometries"] == []
    # This implementation's local point-membership policy is CLOSED at the
    # boundary. Google boundary parity remains unverified.
    assert boundary["point_contains"] is True


def test_explicit_spherical_reprojection_parameters_and_planar_edges_stay_visible_gaps():
    fixture = load_fixture()
    coordinates = fixture["regions"]["touch_polygon"]["coordinates"]
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        spherical = ee.Geometry.Polygon(coordinates)
        point = ee.Geometry.Point([1, 1])
        planar = ee.Geometry.Polygon(
            coordinates, proj="EPSG:4326", geodesic=False,
        )
        # SDK serialization wraps a positive maxError in the unsupported
        # ErrorMargin algorithm, so the compiler must reject it explicitly.
        with pytest.raises(UnsupportedEEError, match="ErrorMargin"):
            compile_expression(ee.serializer.encode(
                spherical.intersection(point, maxError=1), for_cloud_api=False,
            ), [], {})
        with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
            compile_expression(ee.serializer.encode(
                spherical.intersection(point, proj=ee.Projection("EPSG:4326")),
                for_cloud_api=False,
            ), [], {})
        with pytest.raises(UnsupportedEEError,
                           match="planar edges require bounded reprojection"):
            compile_expression(ee.serializer.encode(
                planar.intersects(point), for_cloud_api=False,
            ), [], {})
    assert guard.evidence()["attempt_count"] == 0


@pytest.mark.parametrize("client_name", ["python", "javascript"])
def test_default_spherical_outputs_roundtrip_through_each_official_sdk(client_name):
    fixture = load_fixture()
    outputs = compile_outputs(python_expressions(fixture)["omitted"])
    if client_name == "javascript":
        expressions = javascript_roundtrip(outputs, fixture)
        for name, expression in expressions["geometry"].items():
            assert compile_expression(expression, [], {})["value"] is \
                spherical_contains(_output(outputs, "geometry", name),
                                   {"intersection": [179, 0], "union": [172, 0],
                                    "difference": [172, 0],
                                    "symmetricDifference": [172, 0]}[name])
        for name, expression in expressions["feature_ids"].items():
            assert compile_expression(expression, [], {})["value"] == fixture["features"]["left_id"]
        return

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        geometry_results = {
            name: json_wire(_output(outputs, "geometry", name)) for name in OVERLAYS
        }
        feature_results = {
            name: json_wire(_output(outputs, "feature", name)) for name in OVERLAYS
        }
        point_values = {"intersection": [179, 0], "union": [172, 0],
                        "difference": [172, 0], "symmetricDifference": [172, 0]}
        for name in OVERLAYS:
            geometry = ee.Geometry(geometry_results[name])
            expression = ee.serializer.encode(
                geometry.contains(ee.Geometry.Point(point_values[name])),
                for_cloud_api=False,
            )
            actual = compile_expression(expression, [], {})["value"]
            expected = spherical_contains(geometry_results[name], point_values[name])
            assert actual is expected

            feature = ee.Feature(feature_results[name])
            identity = compile_expression(
                ee.serializer.encode(feature.id(), for_cloud_api=False), [], {},
            )["value"]
            assert identity == fixture["features"]["left_id"]
    assert guard.evidence()["attempt_count"] == 0


def test_spherical_feature_overlays_flow_through_trusted_synthetic_csv(
        tmp_path, monkeypatch):
    fixture = load_fixture()
    example = load_example()
    with OfflineGuard() as guard:
        integration = install(monkeypatch, tmp_path)
        values = example.build_workflow(integration.ee, fixture)
        task = integration.ee.batch.Export.table.toDrive(
            collection=values["feature_overlays"],
            description="Wave61 spherical feature overlays",
            fileFormat="CSV",
            selectors=["system:index", "owner", "priority", ".geo"],
        )
        task.start()
        run = run_batch(integration, task.id)
        assert run.row["status"] == "finished"
        from gee.backend import Jobs
        assets = Jobs().get_result_assets(task.id, USER)
        csv_path = Path(assets[next(iter(assets))]["href"])
        assert csv_path.parent == run.job_dir / "out"
        with csv_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert [row["system:index"] for row in rows] == [
            f"{fixture['features']['left_id']}-{name}" for name in OVERLAYS
        ]
        assert all(row["owner"] == "left" and row["priority"] == "7" for row in rows)
        for row, name in zip(rows, OVERLAYS, strict=True):
            geometry = json.loads(row[".geo"])
            assert geometry["type"] in {"Polygon", "MultiPolygon", "GeometryCollection"}
            for point in ([179, 0], [172, 0], [0, 0]):
                assert spherical_contains(geometry, point) is _boolean_algebra(
                    name,
                    spherical_contains(fixture["regions"]["dateline_left"], point),
                    spherical_contains(fixture["regions"]["dateline_right"], point),
                )
    assert guard.evidence()["attempt_count"] == 0
