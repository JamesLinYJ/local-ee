"""Portable Python/JavaScript spatial selection through real synthetic CSV."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

from ee_spatial_selection_workflow_helpers import (
    compile_wires, invocation_calls, javascript_wires, load_python_example,
    python_wires, semantic,
)
from ee_spherical_workflow_helpers import _on_minor_arc, spherical_contains
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import USER, install, run_batch


def _region_geometry(ring):
    return {"type": "Polygon", "coordinates": [ring]}


def _reference_memberships(regions, points):
    return {
        point_id: [
            name for name, ring in regions.items()
            if spherical_contains(_region_geometry(ring), coordinates)
        ]
        for point_id, coordinates in points
    }


def _assert_nonboundary(regions, points):
    for point_id, coordinates in points:
        for region_name, ring in regions.items():
            assert not any(
                _on_minor_arc(coordinates, first, second)
                for first, second in zip(ring, ring[1:])
            ), (point_id, region_name)


def _resolve_scope(value, scope):
    if isinstance(value, dict) and value.get("type") == "ValueRef":
        return _resolve_scope(scope[value["value"]], scope)
    if type(value) is list:
        return [_resolve_scope(child, scope) for child in value]
    if type(value) is dict:
        return {key: _resolve_scope(child, scope) for key, child in value.items()}
    return value


def _root_call(wire, name):
    root = _resolve_scope(wire["value"], dict(wire.get("scope", [])))
    assert root["type"] == "Invocation" and root["functionName"] == name
    return root


def _selected_ids(value):
    return [feature["properties"]["point_id"] for feature in value["features"]]


def test_official_clients_compile_matching_spherical_selection_and_merge_defaults():
    example = load_python_example()
    python_regions = copy.deepcopy(example.REGIONS)
    python_points = copy.deepcopy(example.POINTS)
    input_snapshot = json.dumps(
        {"regions": example.REGIONS, "points": example.POINTS}, sort_keys=True,
    )

    py_wires = python_wires()
    js_wires, js_regions, js_points = javascript_wires()
    assert js_regions == python_regions and js_points == [list(row) for row in python_points]
    assert json.dumps(
        {"regions": example.REGIONS, "points": example.POINTS}, sort_keys=True,
    ) == input_snapshot
    py_wire_snapshot = json.dumps(py_wires, sort_keys=True)
    js_wire_snapshot = json.dumps(js_wires, sort_keys=True)

    memberships = _reference_memberships(python_regions, python_points)
    _assert_nonboundary(python_regions, python_points)
    dateline_expected = [
        name for name, matches in memberships.items() if "dateline" in matches
    ]
    polar_expected = [
        name for name, matches in memberships.items() if "polar" in matches
    ]
    high_expected = [
        name for name, matches in memberships.items()
        if "high_left" in matches or "high_right" in matches
    ]
    assert dateline_expected == ["dateline_inside"]
    assert polar_expected == ["polar_inside"]
    assert high_expected == [
        "high_left_only", "high_overlap", "high_right_only", "curved_inside",
    ]
    assert memberships["high_overlap"] == ["high_left", "high_right"]
    assert memberships["curved_planar_only"] == []
    high_point_ids = [
        name for name, _ in python_points if name.startswith(("high_", "curved_"))
    ]
    query_point_ids = ["high_overlap", "curved_inside", "curved_planar_only"]
    query_expected = [name for name in query_point_ids if name in high_expected]

    with OfflineGuard() as guard:
        py_outputs = compile_wires(py_wires)
        js_outputs = compile_wires(js_wires)
    assert guard.evidence()["attempt_count"] == 0
    assert json.dumps(py_wires, sort_keys=True) == py_wire_snapshot
    assert json.dumps(js_wires, sort_keys=True) == js_wire_snapshot
    assert semantic(py_outputs) == semantic(js_outputs)
    for outputs in (py_outputs, js_outputs):
        assert _selected_ids(outputs["dateline_selected"]) == dateline_expected
        assert _selected_ids(outputs["polar_selected"]) == polar_expected
        assert _selected_ids(outputs["selected"]) == query_expected
        assert _selected_ids(outputs["filter_results"]["field_value_numeric"]) == [
            "high_left_only", "high_overlap", "curved_inside",
        ]
        assert _selected_ids(outputs["filter_results"]["value_field_typed"]) == [
            "high_left_only", "high_overlap", "curved_inside",
        ]
        assert _selected_ids(outputs["filter_results"]["field_field_typed"]) == high_point_ids
        assert _selected_ids(outputs["filter_results"]["value_value_numeric"]) == high_point_ids
        assert len(outputs["table"]["features"]) == 2
        merged_outputs = [outputs[f"merge_{name}"] for name in ("omitted", "null", "typed")]
        assert merged_outputs[0] == merged_outputs[1] == merged_outputs[2]
        for point_id in (
            "high_left_only", "high_overlap", "high_right_only", "curved_inside",
        ):
            coordinates = dict(python_points)[point_id]
            assert spherical_contains(merged_outputs[0], coordinates), point_id
        for point_id in ("curved_planar_only", "high_below"):
            coordinates = dict(python_points)[point_id]
            assert not spherical_contains(merged_outputs[0], coordinates), point_id

    for merge_name in ("merge_omitted", "merge_null"):
        call = _root_call(py_wires[merge_name], "Collection.geometry")
        assert set(call["arguments"]) == {"collection"}
    typed_merge = _root_call(py_wires["merge_typed"], "Collection.geometry")
    assert set(typed_merge["arguments"]) == {"collection", "maxError"}
    assert not invocation_calls(py_wires["merge_typed"], "Geometry.transform")
    js_null_merge = _root_call(js_wires["merge_null"], "Collection.geometry")
    assert set(js_null_merge["arguments"]) == {"collection", "maxError"}
    assert js_null_merge["arguments"]["maxError"] is None
    assert not invocation_calls(js_wires["merge_typed"], "Geometry.transform")

    signatures = {
        name: _root_call(wire, "Filter.intersects")["arguments"]
        for name, wire in py_wires["filters"].items()
    }
    assert set(signatures["field_value_numeric"]) == {
        "leftField", "rightValue", "maxError",
    }
    assert signatures["field_value_numeric"]["leftField"] == ".geo"
    numeric_margin = invocation_calls(
        signatures["field_value_numeric"]["maxError"], "ErrorMargin",
    )
    assert len(numeric_margin) == 1
    assert numeric_margin[0]["arguments"] == {"value": 5}
    assert set(signatures["value_field_typed"]) == {
        "leftValue", "rightField", "maxError",
    }
    assert signatures["value_field_typed"]["rightField"] == ".geo"
    typed_margin = invocation_calls(
        signatures["value_field_typed"]["maxError"], "ErrorMargin",
    )
    assert len(typed_margin) == 1
    assert typed_margin[0]["arguments"] == {"value": 5, "unit": "projected"}
    assert set(signatures["field_field_typed"]) == {
        "leftField", "rightField", "maxError",
    }
    assert set(signatures["value_value_numeric"]) == {
        "leftValue", "rightValue", "maxError",
    }


def test_combined_sdk_export_dispatches_worker_csv_asset_and_official_readback(
        tmp_path, monkeypatch):
    example = load_python_example()
    input_snapshot = json.dumps(
        {"regions": example.REGIONS, "points": example.POINTS}, sort_keys=True,
    )
    with OfflineGuard() as guard:
        integration = install(monkeypatch, tmp_path)
        values = example.build_workflow(integration.ee)
        before = json.dumps(example.encode_workflow(integration.ee, values), sort_keys=True)
        task = integration.ee.batch.Export.table.toDrive(
            collection=values["table"], description="Spherical spatial selection",
            fileFormat="CSV", selectors=["row_kind", "point_id", ".geo"],
        )
        task.start()
        run = run_batch(integration, task.id)
        assert run.row["status"] == "finished"

        from gee.backend import Jobs
        assets = Jobs().get_result_assets(task.id, USER)
        assert len(assets) == 1
        asset = next(iter(assets.values()))
        path = Path(asset["href"])
        assert path.parent == run.job_dir / "out"
        with path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        assert [row["row_kind"] for row in rows] == ["filter_result", "regionGeometry"]
        assert rows[0]["point_id"] == "high_overlap"
        assert rows[1]["point_id"] == ""

        point_geojson, merged_geojson = (json.loads(row[".geo"]) for row in rows)
        assert point_geojson["type"] == "Point"
        assert point_geojson["coordinates"] == [45, 75]
        parsed_point = integration.ee.Geometry(point_geojson)
        assert parsed_point.toGeoJSON() == point_geojson
        assert merged_geojson["type"] in {"GeometryCollection", "Polygon", "MultiPolygon"}
        parsed_merged = integration.ee.Geometry(merged_geojson)
        assert parsed_merged.toGeoJSON() == merged_geojson
        for point_id in ("high_left_only", "high_overlap", "high_right_only", "curved_inside"):
            coordinates = dict(example.POINTS)[point_id]
            assert spherical_contains(merged_geojson, coordinates), point_id
        for point_id in ("curved_planar_only", "high_below"):
            coordinates = dict(example.POINTS)[point_id]
            assert not spherical_contains(merged_geojson, coordinates), point_id

        after = json.dumps(example.encode_workflow(integration.ee, values), sort_keys=True)
        assert after == before
        assert json.dumps(
            {"regions": example.REGIONS, "points": example.POINTS}, sort_keys=True,
        ) == input_snapshot
    assert guard.evidence()["attempt_count"] == 0
