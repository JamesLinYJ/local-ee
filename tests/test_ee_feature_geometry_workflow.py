"""Official extraction defaults through local computation and real CSV files."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ee_random_split_parity import JAVASCRIPT, semantic_wire
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression, UnsupportedEEError
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import USER, install, run_batch


ROOT = Path(__file__).resolve().parents[1]
RING = [[170, -5], [-170, -5], [-170, 5], [170, 5], [170, -5]]


def _workflow(ee):
    spherical = ee.Feature(ee.Geometry.Polygon([RING]), {"name": "dateline"})
    planar = ee.Feature(ee.Geometry.Polygon(
        [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]], geodesic=False,
    ))
    return {
        "default": spherical.geometry().contains(ee.Geometry.Point([180, 0])),
        "ignored_true": spherical.geometry(geodesics=True).contains(ee.Geometry.Point([180, 0])),
        "ignored_false": spherical.geometry(geodesics=False).contains(ee.Geometry.Point([0, 0])),
        "planar": planar.geometry(geodesics=True).contains(
            ee.Geometry.Point([2, 2]), proj="EPSG:4326",
        ),
        "output": ee.FeatureCollection([
            ee.Feature(spherical.geometry(geodesics=False), {"name": "dateline"}),
            ee.Feature(planar.geometry(geodesics=True), {"name": "planar"}),
        ]),
    }


def _python_wires():
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        wires = {name: ee.serializer.encode(value, for_cloud_api=False)
                 for name, value in _workflow(ee).items()}
    assert guard.evidence()["attempt_count"] == 0
    return json.loads(json.dumps(wires))


def _javascript_wires():
    node = shutil.which("node")
    assert node is not None
    script = JAVASCRIPT.split("const config = JSON.parse", 1)[0] + r"""
const ring = JSON.parse(fs.readFileSync(0, 'utf8'));
const spherical = ee.Feature(ee.Geometry.Polygon([ring]), {name: 'dateline'});
const planar = ee.Feature(ee.Geometry.Polygon(
  [[[0,0],[4,0],[4,4],[0,4],[0,0]]], null, false));
const values = {
  default: spherical.geometry().contains(ee.Geometry.Point([180,0])),
  ignored_true: spherical.geometry(null, null, true).contains(ee.Geometry.Point([180,0])),
  ignored_false: spherical.geometry(null, null, false).contains(ee.Geometry.Point([0,0])),
  planar: planar.geometry(null, null, true).contains(ee.Geometry.Point([2,2]), null, 'EPSG:4326'),
  output: ee.FeatureCollection([
    ee.Feature(spherical.geometry(null, null, false), {name:'dateline'}),
    ee.Feature(planar.geometry(null, null, true), {name:'planar'})
  ])
};
const outputs = Object.fromEntries(Object.entries(values).map(
  ([name, value]) => [name, ee.Serializer.encode(value)]));
if (attempts) throw Error('unexpected networking');
process.stdout.write(JSON.stringify(outputs));
"""
    result = subprocess.run([node, "-e", script], cwd=ROOT, input=json.dumps(RING),
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_official_clients_preserve_spherical_and_planar_models_after_extraction():
    # Hand-authored nonboundary points: the short dateline region includes
    # longitude 180 and excludes 0; the explicit planar square includes (2,2).
    expected = {"default": True, "ignored_true": True,
                "ignored_false": False, "planar": True}
    all_outputs = []
    with OfflineGuard() as guard:
        for wires in (_python_wires(), _javascript_wires()):
            snapshot = json.dumps(wires, sort_keys=True)
            outputs = {name: compile_expression(
                wire, [], {}, for_table_export=name == "output",
            )["value"]
                       for name, wire in wires.items()}
            assert {key: outputs[key] for key in expected} == expected
            assert json.dumps(wires, sort_keys=True) == snapshot
            all_outputs.append(outputs)
    assert semantic_wire(all_outputs[0]) == semantic_wire(all_outputs[1])
    assert guard.evidence()["attempt_count"] == 0


def test_extracted_models_reach_actual_synthetic_csv_and_official_sdk_roundtrip(
        tmp_path, monkeypatch):
    with OfflineGuard() as guard:
        integration = install(monkeypatch, tmp_path)
        task = integration.ee.batch.Export.table.toDrive(
            collection=_workflow(integration.ee)["output"],
            description="Extracted geometry models", fileFormat="CSV",
            selectors=["name", ".geo"],
        )
        task.start()
        run = run_batch(integration, task.id)
        assert run.row["status"] == "finished"
        from gee.backend import Jobs
        assets = Jobs().get_result_assets(task.id, USER)
        asset = next(iter(assets.values()))
        path = Path(asset["href"])
        assert path.parent == run.job_dir / "out"
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert [row["name"] for row in rows] == ["dateline", "planar"]
        for row, expected_model in zip(rows, (True, False), strict=True):
            geometry = json.loads(row[".geo"])
            assert geometry["geodesic"] is expected_model
            parsed = integration.ee.Geometry(geometry)
            assert parsed.toGeoJSON() == geometry
            encoded = integration.ee.serializer.encode(parsed.geodesic(), for_cloud_api=False)
            assert compile_expression(encoded, [], {})["value"] is expected_model
    assert guard.evidence()["attempt_count"] == 0


def test_measurement_probe_fixture_records_gaps_without_inventing_spherical_defaults():
    fixture = json.loads((ROOT / "tests/fixtures/ee-measurement-wave62-before-v1.json").read_text())
    assert len(fixture["records"]) == 6
    for record in fixture["records"]:
        assert record["before"]["supported"] is False
        with pytest.raises(UnsupportedEEError) as error:
            compile_expression(record["wire"], [], {})
        assert str(error.value) == record["before"]["error"]


def test_empty_feature_map_validates_geometry_argument_names_without_inventing_rows():
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        mapped = ee.FeatureCollection([]).map(lambda f: ee.Feature(f.geometry()))
        wire = json.loads(json.dumps(ee.serializer.encode(mapped, for_cloud_api=False)))
        assert compile_expression(wire, [], {})["value"]["features"] == []

        def corrupt(value):
            count = 0
            if isinstance(value, dict):
                if value.get("functionName") == "Feature.geometry":
                    value["arguments"]["geodesic"] = False
                    count += 1
                for child in value.values():
                    count += corrupt(child)
            elif isinstance(value, list):
                for child in value:
                    count += corrupt(child)
            return count

        assert corrupt(wire) == 1
        with pytest.raises(UnsupportedEEError, match="geodesic"):
            compile_expression(wire, [], {})
    assert guard.evidence()["attempt_count"] == 0
