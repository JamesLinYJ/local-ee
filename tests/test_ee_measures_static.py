"""Offline SDK serialization and independent numeric-reference checks."""
from __future__ import annotations

import hashlib
import json
import math

import pytest

from ee_measures_references import (
    load_fixture,
    planar_reference,
    spherical_arc_angle,
    spherical_centroid_coordinates,
    spherical_centroid_vector,
    spherical_triangle_area,
    verify_frozen_wgs84_reference,
)
from ee_measures_workflow import (
    ROOT,
    load_feature_only_workflows_fixture,
    load_geometrycollection_workflow_fixture,
    metric_output_collection,
    physical_measurement_collection,
)
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard


def _encoded(ee, value):
    return json.loads(json.dumps(ee.serializer.encode(value, for_cloud_api=False)))


def _compiled_value(ee, value):
    result = compile_expression(_encoded(ee, value), [], {})
    assert result["kind"] == "value"
    return result["value"]


def test_independent_unit_sphere_vector_and_planar_fraction_references_are_self_consistent():
    fixture = load_fixture()
    cases = fixture["cases"]
    octant = cases["octant_triangle"]["geometry"]
    octant_vertices = octant["coordinates"][0][:3]
    assert spherical_triangle_area(*octant_vertices) == pytest.approx(
        math.pi / 2, rel=2e-14, abs=2e-15,
    )
    dimension, vector = spherical_centroid_vector(octant)
    assert dimension == 2
    assert vector == pytest.approx((math.pi / 4,) * 3, rel=2e-14, abs=2e-15)
    assert spherical_centroid_coordinates(octant) == pytest.approx(
        [45.0, math.degrees(math.asin(1 / math.sqrt(3)))], rel=0, abs=2e-13,
    )

    arc = cases["equatorial_arc"]["geometry"]
    assert spherical_arc_angle(*arc["coordinates"]) == pytest.approx(
        math.pi / 2, rel=2e-14, abs=2e-15,
    )
    dimension, arc_vector = spherical_centroid_vector(arc)
    assert dimension == 1
    assert arc_vector == pytest.approx((1.0, 1.0, 0.0))
    point = cases["point"]["geometry"]
    assert spherical_centroid_coordinates(point) == pytest.approx([30.0, 0.0])
    mixed = cases["mixed_highest_dimension"]["geometry"]
    assert spherical_centroid_coordinates(mixed) == pytest.approx(
        spherical_centroid_coordinates(octant), rel=0, abs=2e-13,
    )

    planar_expected = {
        "point": (0, 0, 0, [30, 0]),
        "equatorial_arc": (0, 90, 0, [45, 0]),
        "octant_triangle": (4050, 0, 180 + 90 * math.sqrt(2), [30, 30]),
        "mixed_highest_dimension": (4050, 90, 180 + 90 * math.sqrt(2), [30, 30]),
        "planar_hole": (22, 0, 26, [34 / 11, 45 / 22]),
        "planar_overlapping_multipolygon": (32, 0, 32, [3, 2]),
    }
    for name, (area, length, perimeter, centroid) in planar_expected.items():
        expected = planar_reference(cases[name]["geometry"])
        assert float(expected["area_square_degrees"]) == pytest.approx(area, abs=1e-12)
        assert expected["linear_length_degrees"] == pytest.approx(length, abs=1e-12)
        assert expected["polygon_perimeter_degrees"] == pytest.approx(perimeter, abs=1e-12)
        assert expected["centroid_lon_lat_degrees"] == pytest.approx(centroid, abs=1e-12)

    controls = verify_frozen_wgs84_reference()
    by_id = {record["id"]: record for record in controls}
    assert len(controls) == 23
    assert by_id["equator-quarter"]["expected_decimal"].startswith("10018754.171394621")
    assert by_id["oblique-line"]["expected_decimal"].startswith("15697375.254833570506")
    assert by_id["octant-hole-area"]["geometry"]["coordinates"][1][0] == [10, 10]
    assert fixture["metric_models"]["public_default_wgs84_ellipsoid_edge_v1"]["abi_operations"] == {
        "area": 11, "linear_length": 12, "polygon_perimeter": 13,
    }
    assert fixture["workflow"]["input_features"] == [
        "octant_triangle", "equatorial_arc", "point", "mixed_highest_dimension",
        "planar_hole", "planar_overlapping_multipolygon",
    ]
    physical = fixture["physical_workflow_v2"]
    assert physical["version"] == "wave71-physical-workflow-v2"
    assert len(physical["default_wgs84"]["input_features"]) == 4
    assert len(physical["explicit_epsg4326_planar"]["input_features"]) == 6
    assert "not a new API compatibility result" in physical["change_from_v1"]
    assert physical["explicit_epsg4326_planar"]["input_features"][-1] == (
        "planar_overlapping_multipolygon"
    )


def test_geometrycollection_addendum_preserves_the_two_atomic_polygons_without_multipolygon_gain():
    fixture = load_geometrycollection_workflow_fixture(load_fixture())
    addendum = fixture["geometrycollection_addendum"]
    source_geometry = fixture["cases"]["planar_overlapping_multipolygon"]["geometry"]
    collection_geometry = fixture["cases"]["planar_overlapping_geometrycollection"]["geometry"]
    assert collection_geometry["type"] == "GeometryCollection"
    assert [child["coordinates"] for child in collection_geometry["geometries"]] == (
        source_geometry["coordinates"]
    )
    assert all(child["geodesic"] is False for child in collection_geometry["geometries"])
    assert addendum["physical_workflow_v3"]["route"] == (
        "explicit_epsg4326_planar_geometrycollection_v3"
    )
    assert "not a MultiPolygon compatibility gain" in addendum["scope"]
    assert "not a compatibility gain for MultiPolygon" in (
        addendum["physical_workflow_v3"]["change_from_v2"]
    )
    composed_expected = planar_reference(collection_geometry)
    assert float(composed_expected["area_square_degrees"]) == 32
    assert composed_expected["linear_length_degrees"] == 0
    assert composed_expected["polygon_perimeter_degrees"] == 32
    assert composed_expected["centroid_lon_lat_degrees"] == [3.0, 2.0]
    assert fixture["physical_workflow_v2"]["explicit_epsg4326_planar"][
        "input_features"
    ][-1] == "planar_overlapping_multipolygon"


def test_physical_workflow_v2_wires_and_v3_v4_formulas_serialize_offline():
    fixture = load_feature_only_workflows_fixture(load_fixture())
    preserved = fixture["geometrycollection_addendum"]["preserved_v2_wires"]
    v4_routes = {
        item["route"]: item
        for item in fixture["physical_workflows_v4"].values()
    }
    from gee.ee_python_client import configure_local_ee

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        v3_route = fixture["physical_workflow_v3"]["route"]
        routes = (
            "default_wgs84", "explicit_epsg4326_planar", v3_route,
            *v4_routes,
        )
        for route in routes:
            wire = _encoded(
                ee, physical_measurement_collection(ee, fixture, route),
            )
            function_names = set()
            invocations = []

            def visit(value):
                if isinstance(value, dict):
                    if value.get("type") == "Invocation":
                        function_names.add(value["functionName"])
                        invocations.append(value)
                    for child in value.values():
                        visit(child)
                elif isinstance(value, list):
                    for child in value:
                        visit(child)

            visit(wire)
            assert "Collection.map" in function_names
            is_feature_only = route in v4_routes
            owners = ("Feature",) if is_feature_only else ("Geometry", "Feature")
            for owner in owners:
                assert {f"{owner}.{method}" for method in (
                    "area", "length", "perimeter", "centroid",
                )} <= function_names
            if is_feature_only:
                assert not any(
                    name.startswith("Geometry.")
                    and name.rsplit(".", 1)[-1] in {
                        "area", "length", "perimeter", "centroid",
                    }
                    for name in function_names
                )
                for method in ("area", "length", "perimeter", "centroid"):
                    assert sum(
                        call["functionName"] == f"Feature.{method}"
                        for call in invocations
                    ) == 1
                config = v4_routes[route]
                if route.startswith("default_wgs84"):
                    assert config["input_features"] == fixture[
                        "physical_workflow_v2"]["default_wgs84"]["input_features"]
                else:
                    assert config["input_features"] == fixture[
                        "physical_workflow_v3"]["input_features"]
            has_projection = "Projection" in function_names
            assert has_projection is (not route.startswith("default_wgs84"))
            if route in preserved:
                canonical = json.dumps(
                    wire, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")
                assert len(canonical) == preserved[route]["bytes"]
                assert hashlib.sha256(canonical).hexdigest() == preserved[route]["sha256"]
    assert guard.evidence()["attempt_count"] == 0


def test_preserved_v2_overlapping_multipolygon_wire_remains_a_compile_rejection():
    fixture = load_fixture()
    addendum = load_geometrycollection_workflow_fixture(fixture)[
        "geometrycollection_addendum"
    ]
    preserved = addendum["preserved_v2_wires"]["explicit_epsg4326_planar"]
    from gee.ee_python_client import configure_local_ee

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        wire = _encoded(
            ee, physical_measurement_collection(
                ee, fixture, "explicit_epsg4326_planar",
            ),
        )
        canonical = json.dumps(
            wire, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        assert len(canonical) == preserved["bytes"]
        assert hashlib.sha256(canonical).hexdigest() == preserved["sha256"]
        geometry = ee.Geometry(
            fixture["cases"]["planar_overlapping_multipolygon"]["geometry"]
        )
        projection = ee.Projection("EPSG:4326")
        expression = _encoded(ee, geometry.area(proj=projection))
        with pytest.raises(UnsupportedEEError, match="Invalid planar GeoJSON geometry topology"):
            compile_expression(expression, [], {})
    assert guard.evidence()["attempt_count"] == 0


def test_additive_planar_geometrycollection_components_compile_against_fraction_reference():
    fixture = load_geometrycollection_workflow_fixture(load_fixture())
    geometry_json = fixture["cases"]["planar_overlapping_geometrycollection"]["geometry"]
    reference = planar_reference(geometry_json)
    from gee.ee_python_client import configure_local_ee

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        geometry = ee.Geometry(geometry_json)
        projection = ee.Projection("EPSG:4326")
        for method, reference_key in (
            ("area", "area_square_degrees"),
            ("length", "linear_length_degrees"),
            ("perimeter", "polygon_perimeter_degrees"),
        ):
            actual = _compiled_value(ee, getattr(geometry, method)(proj=projection))
            expected = float(reference[reference_key])
            assert actual == pytest.approx(expected, rel=0, abs=1e-12), method
    assert guard.evidence()["attempt_count"] == 0


def test_original_v1_mixed_route_sdk_map_wire_is_preserved():
    fixture = load_fixture()
    from gee.ee_python_client import configure_local_ee

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        wire = _encoded(ee, metric_output_collection(ee, fixture))
        canonical = json.dumps(
            wire, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    workflow = fixture["workflow"]
    assert len(canonical) == workflow["historical_python_sdk_map_wire_bytes"]
    assert hashlib.sha256(canonical).hexdigest() == workflow[
        "historical_python_sdk_map_wire_sha256"
    ]
    assert "SDK serialization evidence only" in workflow["historical_wire_scope"]
    assert guard.evidence()["attempt_count"] == 0
