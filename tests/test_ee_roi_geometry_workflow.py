"""Actual ROI overlays, two-scene pixel checks, and Feature CSV readback."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from ee_roi_geometry_workflow_helpers import (
    OPERATIONS,
    OVERLAYS,
    REGIONS,
    baseline_expressions,
    baseline_is_intact,
    compile_outputs,
    evaluate_image,
    independent_ndvi,
    javascript_expressions,
    json_wire,
    load_example,
    load_fixture,
    python_expressions,
    root_invocation,
    semantic,
)
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import USER, install, run_batch


ROOT = Path(__file__).resolve().parents[1]


def test_pinned_sdks_compile_all_roi_methods_and_match_independent_scene_pixels():
    fixture = load_fixture()
    python = python_expressions(fixture)
    javascript = javascript_expressions(fixture)
    assert semantic(python) == semantic(javascript)
    if baseline_is_intact():
        baseline = json.loads(
            (ROOT / "audit/gee-python-wave60/workflow/before.json")
            .read_text(encoding="utf-8")
        )
        with OfflineGuard() as guard:
            ee = configure_local_ee(
                "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
            )
            assert baseline_expressions(ee, baseline) == baseline["expressions"]
        assert guard.evidence()["attempt_count"] == 0

    for expressions in (python, javascript):
        assert set(expressions["geometry"]) == set(OPERATIONS)
        assert set(expressions["feature"]) == set(OPERATIONS)
        assert set(expressions["images"]) == {scene["id"] for scene in fixture["scenes"]}
        for family in ("geometry", "feature"):
            for operation in OPERATIONS:
                invocation = root_invocation(expressions[family][operation])
                assert invocation["functionName"] == f"{family.capitalize()}.{operation}"
                assert "proj" in invocation["arguments"]
                assert "maxError" not in invocation["arguments"]
                scope = dict(expressions[family][operation].get("scope", []))

                def resolve(value):
                    while isinstance(value, dict) and value.get("type") == "ValueRef":
                        value = scope[value["value"]]
                    return value

                projection_call = resolve(invocation["arguments"]["proj"])
                assert projection_call["functionName"] == "Projection"
                assert resolve(projection_call["arguments"]["crs"]) == "EPSG:4326"
                rectangles = [
                    call for _key, call in expressions[family][operation]["scope"]
                    if isinstance(call, dict)
                    and call.get("functionName") == "GeometryConstructors.Rectangle"
                ]
                assert rectangles and all(
                    call["arguments"]["geodesic"] is False for call in rectangles
                )

    python_compiled = compile_outputs(python, fixture)
    javascript_compiled = compile_outputs(javascript, fixture)
    assert semantic(python_compiled) == semantic(javascript_compiled)
    assert {name: value["value"] for name, value in python_compiled["geometry"].items()
            if name in {"contains", "containedIn", "disjoint", "intersects"}} == {
                "contains": True, "containedIn": False, "disjoint": False, "intersects": True,
            }
    assert {name: value["value"] for name, value in python_compiled["feature"].items()
            if name in {"contains", "containedIn", "disjoint", "intersects"}} == {
                "contains": True, "containedIn": False, "disjoint": False, "intersects": True,
            }
    assert {name: value["value"] for name, value in python_compiled["boundary"].items()} == {
        "study_contains_corner": True,
        "exclusion_contains_corner": False,
        "exclusion_intersects_corner": True,
    }
    assert python_compiled["feature_overlays"]["kind"] == "value"
    assert len(python_compiled["feature_overlays"]["value"]["features"]) == 4

    for scene in fixture["scenes"]:
        outputs = python_compiled["images"][scene["id"]]
        assert set(outputs) == set(REGIONS)
        for name, graph in outputs.items():
            assert graph["kind"] == "image"
            assert graph["bands"] == ["NDVI"]
            assert graph["source_item_ids"] == [scene["id"]]
            validate(graph["process_graph"])
            actual, bands, timed = evaluate_image(graph, scene, fixture)
            expected, expected_valid = independent_ndvi(
                scene, fixture["expected_pixel_indices"][name],
            )
            assert not timed and bands == ["NDVI"]
            np.testing.assert_array_equal(np.isfinite(actual), expected_valid)
            np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-14, equal_nan=True)


def test_planar_edges_with_spherical_default_non4326_and_non_null_error_remain_gaps():
    fixture = load_fixture()
    example = load_example()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        projection = ee.Projection("EPSG:4326")
        left = example.geometry(ee, fixture["regions"]["study"], projection)
        right = example.geometry(ee, fixture["regions"]["exclusion"], projection)
        left_feature = ee.Feature(left, {"roi": "study"})
        right_feature = ee.Feature(right, {"roi": "exclusion"})
        for family, first, second in (
            ("Geometry", left, right), ("Feature", left_feature, right_feature),
        ):
            for operation in OPERATIONS:
                for kwargs in ({}, {"proj": None}):
                    expression = ee.serializer.encode(
                        getattr(first, operation)(second, **kwargs),
                        for_cloud_api=False,
                    )
                    with pytest.raises(UnsupportedEEError):
                        compile_expression(expression, [], {})

                expression = ee.serializer.encode(
                    getattr(first, operation)(second, proj=ee.Projection("EPSG:3857")),
                    for_cloud_api=False,
                )
                with pytest.raises(UnsupportedEEError):
                    compile_expression(expression, [], {})

                expression = ee.serializer.encode(
                    getattr(first, operation)(second, maxError=1, proj=projection),
                    for_cloud_api=False,
                )
                with pytest.raises(UnsupportedEEError):
                    compile_expression(expression, [], {})

        default_polygon = ee.Geometry(fixture["regions"]["study"])
        expression = ee.serializer.encode(
            default_polygon.intersects(right, proj=projection), for_cloud_api=False,
        )
        with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
            compile_expression(expression, [], {})
    assert guard.evidence()["attempt_count"] == 0


def test_empty_and_lower_dimension_overlays_do_not_fabricate_image_pixels():
    fixture = load_fixture()
    example = load_example()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        projection = ee.Projection("EPSG:4326")
        study = example.geometry(ee, fixture["regions"]["study"], projection)
        empty_region = ee.Geometry.Rectangle(
            [10, 10, 11, 11], proj=projection, geodesic=False,
        )
        line = ee.Geometry.LineString(
            [[0, 2], [4, 2]], proj=projection, geodesic=False,
        )
        empty = ee.serializer.encode(
            study.intersection(empty_region, proj=projection), for_cloud_api=False,
        )
        line_result = ee.serializer.encode(
            study.intersection(line, proj=projection), for_cloud_api=False,
        )
        empty_value = compile_expression(empty, [], {})["value"]
        line_value = compile_expression(line_result, [], {})["value"]
        assert empty_value == {
            "type": "GeometryCollection", "geometries": [], "geodesic": False,
        }
        assert line_value["type"] == "LineString"
        assert line_value["geodesic"] is False

        image = ee.ImageCollection("sentinel-2-l2a").first()
        for region in (ee.Geometry(empty_value), ee.Geometry(line_value)):
            with pytest.raises(
                    UnsupportedEEError,
                    match=r"clip supports Polygon/MultiPolygon only"):
                compile_expression(ee.serializer.encode(
                    ee.Image(image).select(["B04", "B08"]).toDouble().select("B08").clip(region),
                    for_cloud_api=False,
                ), *example.local_sources(fixture))
    assert guard.evidence()["attempt_count"] == 0


def test_feature_overlays_keep_left_identity_and_properties_through_csv(
        tmp_path, monkeypatch):
    fixture = load_fixture()
    example = load_example()
    with OfflineGuard() as guard:
        integration = install(monkeypatch, tmp_path)
        overlay = example.build_geometry_workflow(integration.ee, fixture)
        task = integration.ee.batch.Export.table.toDrive(
            collection=overlay["feature_overlays"],
            description="Wave60 ROI feature overlays",
            fileFormat="CSV",
            selectors=["system:index", "roi", "priority", ".geo"],
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
            f"roi-left-{name}" for name in OVERLAYS
        ]
        assert all(row["roi"] == "study" and row["priority"] == "7" for row in rows)
        for row, name in zip(rows, OVERLAYS, strict=True):
            geometry = json.loads(row[".geo"])
            assert geometry["type"] == "Polygon"
            assert len(geometry["coordinates"]) == (
                2 if name in {"difference", "symmetricDifference"} else 1
            )
    assert guard.evidence()["attempt_count"] == 0
