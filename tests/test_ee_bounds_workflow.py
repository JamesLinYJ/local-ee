"""Official SDK bounds workflows, analytic references, and real CSV readback."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import sys

import pytest

from ee_bounds_workflow import (
    analytic_geometry_bounds,
    canonical_bytes,
    javascript_capture,
    load_fixture,
    local_sources,
    python_capture,
    root_invocation,
    sha256,
)
from gee.ee_translate import compile_expression
from gee.compat.earthengine import spherical_native
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import USER, install, run_batch


ROOT = Path(__file__).resolve().parents[1]
FLOAT_NAMES = ("west", "south", "east", "north")
V1_FIXTURE_SHA256 = "ef5a2a9d7cde732793b4cdd966556ca2c73558fa70c9d6f8ba92a0df1d34116b"
EXPECTED_WIRE_HASHES = {
    "workflow": {
        "image_bounds_default": "264373729bb06b5dcfa9e744c9aa4e0bbc23b668822ef9cc403736ff8b64ec27",
        "feature_bounds_default": "2b000ea5212bd615f88b0d5d867e426409acb32b3c02f82ad13e198045f5e849",
        "image_bounds_projected": "6d9eb12663d8bb960897f68857f63d63fd36e5413a1d2bb745613e5c0a21bdd6",
        "feature_bounds_projected": "d2311a4f66ba0513a7546331aa7c083389af617b79c2c39903e5a57768a255ab",
        "filter_bounds": "e2f767d6d55974a0408cd2b5141156fc74808bc7773a724d3a43eeef9ec79690",
        "clipped_image": "4b32c4d752afa301dad522e1d97a447dafae83528cd5f46e568faf14dfce5e42",
        "sample_regions": "67342ac134d5809e1420f32abb7e9a379774670557e2ec17b643c1215d1fd835",
        "bounds_table": "b26e2d3a276492c96701bddc7b4d0fdd366393f9cf892f7018c0936daffaec5d",
    },
    "numeric_references": {
        "planar_rectangle": "3a68190bdf6600ce0d6f931cfd479b74441787553e4eeded196c38857f5428a5",
        "high_latitude_line": "82ea0144811b7e44f29b75be255f1e74700c7211da945f0b146284c652e46a1e",
        "high_latitude_polygon": "33c43facea51bce18b23a08d81d0120bea5f37c97dceafec1c1a9ae13e29a56d",
    },
}


@pytest.fixture(autouse=True)
def use_explicit_test_s2_bounds_artifact(monkeypatch):
    """Allow an isolated artifact in one fresh test process, never by default."""
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
    if spherical_native._LOADED is not None:
        loaded_library = next((path for path in spherical_native._LOADED[0]
                               if path.name == library), None)
        if loaded_library is None or loaded_library.parent != artifact:
            pytest.fail("Run bounds workflow tests in a fresh process for the explicit artifact")
    monkeypatch.setattr(spherical_native, "ARTIFACT_DIR", artifact)


def _bbox(geometry):
    coordinates = geometry["coordinates"]
    values = []

    def visit(value):
        if (isinstance(value, list) and len(value) == 2
                and all(type(number) in (int, float) for number in value)):
            values.append(value)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(coordinates)
    return [min(point[0] for point in values), min(point[1] for point in values),
            max(point[0] for point in values), max(point[1] for point in values)]


def _compare_bbox(actual, expected, tolerance):
    assert len(actual) == len(expected) == len(FLOAT_NAMES)
    for label, value, reference in zip(FLOAT_NAMES, actual, expected, strict=True):
        assert value == pytest.approx(reference, abs=tolerance), label


def _forbid_native_bounds(monkeypatch):
    def unexpected(*_args, **_kwargs):
        pytest.fail("Planar catalog workflow unexpectedly invoked the native bounds opcode")

    monkeypatch.setattr(spherical_native, "run", unexpected)


def _compile_all(snapshot, fixture, families=("workflow", "explicit_null_controls", "numeric_references")):
    catalog, items = local_sources(fixture)
    expressions = snapshot["expressions"]
    outputs = {}
    for family in families:
        outputs[family] = {
            name: compile_expression(wire, catalog, items)
            for name, wire in expressions[family].items()
        }
    return outputs


def test_official_clients_emit_frozen_default_and_explicit_null_wires():
    fixture = load_fixture()
    python = python_capture(fixture)
    javascript = javascript_capture(fixture)
    assert python["network_guard"]["attempt_count"] == 0
    assert javascript["network_guard"]["attempt_count"] == 0
    assert python["sdk"]["source_commit"] == javascript["sdk"]["source_commit"]
    assert python["expressions"]["workflow"] == javascript["expressions"]["workflow"]
    assert python["expressions"]["numeric_references"] == javascript["expressions"]["numeric_references"]
    assert python["sdk"]["version"] == javascript["sdk"]["version"] == "1.7.49"
    assert sha256((ROOT / "tests/fixtures/ee-bounds-wave69-v1.json").read_bytes()) == V1_FIXTURE_SHA256
    assert fixture["catalog"]["id"] == "sentinel-2-l2a"
    for snapshot in (python, javascript):
        for family, expected in EXPECTED_WIRE_HASHES.items():
            actual = {name: sha256(canonical_bytes(wire))
                      for name, wire in snapshot["expressions"][family].items()}
            assert actual == expected
    feature_bounds = root_invocation(python["expressions"]["workflow"]["feature_bounds_default"])
    assert feature_bounds["functionName"] == "Feature.bounds"
    image_bounds = python["expressions"]["workflow"]["image_bounds_default"]
    assert '"functionName": "Image.geometry"' in json.dumps(image_bounds)
    assert root_invocation(image_bounds)["functionName"] == "Geometry.bounds"


def test_null_controls_keep_the_known_sdk_serialization_difference():
    python, javascript = python_capture(), javascript_capture()
    for name in ("geometry", "feature", "image"):
        left = python["expressions"]["explicit_null_controls"][name]
        right = javascript["expressions"]["explicit_null_controls"][name]
        assert canonical_bytes(left) != canonical_bytes(right)
        assert "null" not in canonical_bytes(left).decode("utf-8")
        assert "null" in canonical_bytes(right).decode("utf-8")


def test_manual_planar_and_analytic_great_circle_references_are_tight():
    fixture = load_fixture()
    references = fixture["numeric_references"]
    tolerance = fixture["numeric_references"]["roundoff_tolerance_degrees"]
    for name in ("planar_rectangle", "high_latitude_line", "high_latitude_polygon"):
        reference = references[name]
        actual = analytic_geometry_bounds(reference)
        _compare_bbox(actual, reference["expected_bounds"], tolerance)
        for point in reference["coordinates"][0] if reference["type"] == "Polygon" else reference["coordinates"]:
            assert actual[0] - tolerance <= point[0] <= actual[2] + tolerance
            assert actual[1] - tolerance <= point[1] <= actual[3] + tolerance

    line_bounds = analytic_geometry_bounds(references["high_latitude_line"])
    vertex_north = max(point[1] for point in references["high_latitude_line"]["coordinates"])
    assert line_bounds[3] > vertex_north + 7.0
    assert line_bounds[3] == pytest.approx(82.36925978756994, abs=tolerance)
    polygon_bounds = analytic_geometry_bounds(references["high_latitude_polygon"])
    assert polygon_bounds[3] == pytest.approx(line_bounds[3], abs=tolerance)


def test_bounds_workflow_compiles_filters_clips_and_uses_bounded_sample_geometry(monkeypatch):
    _forbid_native_bounds(monkeypatch)
    fixture = load_fixture()
    python = python_capture(fixture)
    javascript = javascript_capture(fixture)
    families = ("workflow", "explicit_null_controls")
    python_compiled = _compile_all(python, fixture, families)
    javascript_compiled = _compile_all(javascript, fixture, families)

    tolerance = fixture["tolerances"]["coordinate_absolute_degrees"]
    image_expected = fixture["image"]["expected_bounds"]
    feature_expected = fixture["feature"]["expected_bounds"]
    for compiled in (python_compiled, javascript_compiled):
        image_bounds = compiled["workflow"]["image_bounds_default"]["value"]
        feature = compiled["workflow"]["feature_bounds_default"]["value"]
        _compare_bbox(_bbox(image_bounds), image_expected, tolerance)
        _compare_bbox(_bbox(feature["geometry"]), feature_expected, tolerance)
        _compare_bbox(
            _bbox(compiled["workflow"]["image_bounds_projected"]["value"]),
            image_expected, tolerance,
        )
        _compare_bbox(
            _bbox(compiled["workflow"]["feature_bounds_projected"]["value"]["geometry"]),
            feature_expected, tolerance,
        )
        assert image_bounds["geodesic"] is False
        assert feature["type"] == "Feature"
        assert feature["properties"] == fixture["feature"]["properties"]
        assert feature["geometry"]["geodesic"] is False
        assert compiled["workflow"]["filter_bounds"]["source_item_ids"] == [fixture["image"]["id"]]
        clipped = compiled["workflow"]["clipped_image"]
        assert clipped["kind"] == "image"
        masks = [node["arguments"]["mask"] for node in clipped["process_graph"].values()
                 if node["process_id"] == "mask_polygon"]
        assert masks
        for mask in masks:
            _compare_bbox(_bbox(mask), image_expected, tolerance)
            assert mask["geodesic"] is False
        sampled = compiled["workflow"]["sample_regions"]
        assert sampled["kind"] == "sample_table"
        sample_spec = json.loads(sampled["sample_spec"])
        regions = sample_spec["regions"]["features"]
        assert len(regions) == 1
        _compare_bbox(_bbox(regions[0]["geometry"]), feature_expected, tolerance)
        assert regions[0]["geometry"]["geodesic"] is False



def test_numeric_reference_bounds_compile_against_independent_analytic_values():
    fixture = load_fixture()
    python = python_capture(fixture)
    javascript = javascript_capture(fixture)
    compiled = [
        _compile_all(snapshot, fixture, ("numeric_references",))
        for snapshot in (python, javascript)
    ]
    tolerance = fixture["numeric_references"]["roundoff_tolerance_degrees"]
    for name in ("planar_rectangle", "high_latitude_line", "high_latitude_polygon"):
        expected = fixture["numeric_references"][name]["expected_bounds"]
        for result in (output["numeric_references"][name]["value"] for output in compiled):
            _compare_bbox(_bbox(result), expected, tolerance)
            assert result["geodesic"] is False


def test_bounds_features_write_through_trusted_worker_to_physical_csv(
        tmp_path, monkeypatch):
    _forbid_native_bounds(monkeypatch)
    fixture = load_fixture()
    with OfflineGuard() as guard:
        integration = install(monkeypatch, tmp_path)
        import gee.services.ee as ee_service

        catalog, items = local_sources(fixture)
        monkeypatch.setattr(ee_service, "catalog_snapshot", lambda: (catalog, items))
        from ee_bounds_workflow import load_example
        workflow = load_example().build_workflow(integration.ee, fixture)
        task = integration.ee.batch.Export.table.toDrive(
            collection=workflow["bounds_table"],
            description="Wave69 geometry bounds",
            fileFormat="CSV",
            selectors=["name", "rank", ".geo"],
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
        assert [row["name"] for row in rows] == [
            "image-geometry-bounds", "feature-bounds",
        ]
        assert [row["rank"] for row in rows] == ["8", "7"]
        _compare_bbox(_bbox(json.loads(rows[0][".geo"])), fixture["image"]["expected_bounds"],
                      fixture["tolerances"]["coordinate_absolute_degrees"])
        _compare_bbox(_bbox(json.loads(rows[1][".geo"])), fixture["feature"]["expected_bounds"],
                      fixture["tolerances"]["coordinate_absolute_degrees"])
    assert guard.evidence()["attempt_count"] == 0
