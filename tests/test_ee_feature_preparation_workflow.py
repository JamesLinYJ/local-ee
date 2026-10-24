"""Offline station and image-catalog preparation using both pinned SDKs."""
from __future__ import annotations

import csv
import copy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import tempfile
import uuid

import pytest

from ee_random_split_parity import semantic_wire
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs
from ee_feature_preparation_workflow_support import javascript_expressions
from table_export_support import USER, install, run_batch


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-feature-preparation-wave56-v1.json"
SCRATCH_ROOT = ROOT.parent.parent / "work/gee-python-wave56/workflow"
AUDIT_ROOT = ROOT / "audit/gee-python-wave56/workflow-verified"


def _fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _configure():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def _compile_outputs(ee, values, metadata, items):
    return {
        mode: {
            name: compile_expression(
                ee.serializer.encode(value, for_cloud_api=False), [metadata], items,
            )
            for name, value in outputs.items()
        }
        for mode, outputs in values.items()
    }


def test_python_javascript_station_and_catalog_graphs_match_independent_rows():
    fixture = _fixture()
    metadata, items, _ = synthetic_inputs()
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location(
        "feature_preparation_example",
        ROOT / "examples/61_GEE_python_feature_preparation.py",
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    javascript = javascript_expressions(fixture)

    with OfflineGuard() as guard:
        ee = _configure()
        outputs = {
            "stations": module.build_station_workflow(ee, fixture),
            "catalog": module.build_catalog_workflow(ee, fixture),
        }
        python_compiled = _compile_outputs(ee, outputs, metadata, items)
        javascript_compiled = {
            mode: {
                name: compile_expression(expression, [metadata], items)
                for name, expression in values.items()
            }
            for mode, values in javascript.items()
        }
    assert guard.evidence()["attempt_count"] == 0
    assert semantic_wire(python_compiled) == semantic_wire(javascript_compiled)

    stations = python_compiled["stations"]
    assert stations["metadata_ids"]["value"] == fixture["metadata_expected_ids"]
    assert stations["metadata_count"]["value"] == len(fixture["metadata_expected_ids"])
    assert stations["station_ids"]["value"] == fixture["expected_ids"]
    assert stations["station_count"]["value"] == len(fixture["expected"])
    assert stations["null_geometry_control"]["value"]["geometry"] is None
    features = stations["stations"]["value"]["features"]
    assert [feature["id"] for feature in features] == fixture["expected_ids"]
    for feature, expected in zip(features, fixture["expected"]):
        properties = feature["properties"]
        assert properties["source_id"] == expected["id"]
        assert properties["site_code"] == expected["site_code"]
        assert properties["station_name"] == expected["station_name"]
        assert properties["quality_flag"] == expected["quality_flag"]
        assert properties["source_geometry_type"] == expected["source_geometry_type"]
        assert properties["source_geometry_coordinates"] == expected["source_geometry_coordinates"]
        assert properties["source_fields"] == expected["source_fields"]
        assert feature["geometry"] == {
            "type": "Point", "coordinates": expected["replacement_geometry_coordinates"],
        }
        assert properties["samples"] == expected["samples"]
        assert properties["typed_samples"] == expected["samples"]
        assert properties["reading_vector"] == [expected["reading"], expected["height_m"]]
        assert properties["typed_reading"] == expected["reading"]
        exact_score = Fraction(str(expected["reading"])) + Fraction(expected["height_m"], 8)
        independent_score = Fraction(expected["score"]["numerator"], expected["score"]["denominator"])
        assert exact_score == independent_score
        assert Fraction(str(properties["score"])) == independent_score

    catalog = python_compiled["catalog"]
    assert catalog["image_ids"]["value"] == fixture["catalog_expected_ids"]
    assert catalog["cloud_values"]["value"] == fixture["catalog_expected_clouds"]
    assert catalog["typed_cloud"]["value"] == fixture["catalog_expected_clouds"][0]
    assert catalog["typed_scene_id"]["value"] == fixture["catalog_expected_ids"][0]
    assert catalog["mapped_typed_clouds"]["value"] == fixture["catalog_expected_clouds"]


def test_feature_preparation_bad_types_null_missing_empty_and_large_work():
    fixture = _fixture()
    with OfflineGuard() as guard:
        ee = _configure()

        def compile_value(value):
            encoded = ee.serializer.encode(value, for_cloud_api=False)
            return compile_expression(encoded, [], {})["value"]

        with pytest.raises((UnsupportedEEError, TypeError, ValueError)):
            compile_value(ee.Feature(None, {"station_code": "CN-A-QA"}).getNumber("station_code"))
        with pytest.raises((UnsupportedEEError, TypeError, ValueError)):
            compile_value(ee.Feature(None, {"reading": 5}).getArray("reading"))
        with pytest.raises((UnsupportedEEError, TypeError, ValueError)):
            compile_value(ee.Feature(None, {"reading": 5}).toArray(["reading", "absent"]))
        with pytest.raises((UnsupportedEEError, TypeError, ValueError)):
            compile_value(ee.Feature(None, {"reading": 5}).select(["^reading$"], ["a", "b"]))

        sparse = ee.Feature(None, {
            "system:index": "sparse-getter-control",
            "null_number": None,
            "null_array": None,
            "kept": "present",
        })
        assert compile_value(sparse.getNumber("null_number")) is None
        assert compile_value(sparse.getArray("null_array")) is None
        assert compile_value(sparse.getString("missing_string")) is None
        assert compile_value(sparse.toDictionary(["kept", "missing_key"])) == {
            "kept": "present",
        }

        empty = ee.FeatureCollection([])
        mapped_empty = empty.map(
            lambda feature: feature.select(["^reading$"], ["measurement"])
        )
        assert compile_value(mapped_empty) == {"type": "FeatureCollection", "features": []}
        invalid_empty_callback = ee.serializer.encode(
            empty.map(lambda feature: feature.toArray(["reading"])),
            for_cloud_api=False,
        )

        def inject_unknown_argument(value):
            if isinstance(value, (list, tuple)):
                return any(inject_unknown_argument(child) for child in value)
            if isinstance(value, dict):
                if value.get("functionName") == "Feature.toArray":
                    value["arguments"]["wave56_unknown"] = 1
                    return True
                return any(inject_unknown_argument(child) for child in value.values())
            return False

        invalid_empty_callback = copy.deepcopy(invalid_empty_callback)
        assert inject_unknown_argument(invalid_empty_callback)
        with pytest.raises((UnsupportedEEError, TypeError, ValueError)):
            compile_expression(invalid_empty_callback, [], {})

        wide_values = ee.Array(list(range(64)))
        wide = ee.FeatureCollection([
            ee.Feature(None, {"system:index": f"wide-{index}", "samples": wide_values})
            for index in range(800)
        ]).map(lambda feature: feature.set("typed_samples", feature.getArray("samples")))
        with pytest.raises(UnsupportedEEError, match="limits|budget|work"):
            compile_value(wide.size())
    assert guard.evidence()["attempt_count"] == 0


def test_compiled_prepared_features_run_through_real_csv_dispatch_and_readback(monkeypatch):
    fixture = _fixture()
    scratch_root_created = not SCRATCH_ROOT.exists()
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    assert not SCRATCH_ROOT.is_symlink()
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="feature-prep-", dir=SCRATCH_ROOT) as scratch:
        with OfflineGuard() as guard:
            integration = install(monkeypatch, Path(scratch))
            from importlib.util import module_from_spec, spec_from_file_location

            spec = spec_from_file_location(
                "feature_preparation_export_example",
                ROOT / "examples/61_GEE_python_feature_preparation.py",
            )
            module = module_from_spec(spec)
            spec.loader.exec_module(module)
            workflow = module.build_station_workflow(integration.ee, fixture)
            task = integration.ee.batch.Export.table.toDrive(
                collection=workflow["stations"],
                description="wave56 station preparation",
                fileNamePrefix="wave56-stations",
                fileFormat="CSV",
                selectors=fixture["csv_selectors"],
            )
            task.start()
            job_id = task.id
            row = integration.store.job(job_id, USER)
            assert row["context"]["result_kind"] == "export"
            run = run_batch(integration, job_id)
            physical = Path(scratch) / "jobs" / job_id / "out" / "wave56-stations.csv"
            assert physical.is_file()
            assert run.row["status"] == "finished"
            from gee.backend import Jobs

            asset = Jobs().get_result_assets(job_id, USER)["wave56-stations.csv"]
            assert Path(asset["href"]) == physical
            with physical.open(encoding="utf-8", newline="") as stream:
                records = list(csv.DictReader(stream))
            assert len(records) == 3
            assert list(records[0]) == fixture["csv_selectors"]
            for record, expected in zip(records, fixture["expected"]):
                assert record["system:index"] == expected["id"]
                assert record["source_id"] == expected["id"]
                assert record["site_code"] == expected["site_code"]
                assert record["station_name"] == expected["station_name"]
                assert json.loads(record["samples"]) == expected["samples"]
                assert json.loads(record["typed_samples"]) == expected["samples"]
                assert json.loads(record["reading_vector"]) == [expected["reading"], expected["height_m"]]
                assert json.loads(record["source_fields"]) == expected["source_fields"]
                assert record["source_geometry_type"] == expected["source_geometry_type"]
                assert json.loads(record["source_geometry_coordinates"]) == expected["source_geometry_coordinates"]
                assert json.loads(record[".geo"]) == {
                    "type": "Point", "coordinates": expected["replacement_geometry_coordinates"],
                }
                independent_score = Fraction(
                    expected["score"]["numerator"], expected["score"]["denominator"]
                )
                assert Fraction(record["score"]) == independent_score
                assert Fraction(record["typed_reading"]) == Fraction(str(expected["reading"]))
            assert guard.evidence()["attempt_count"] == 0

        raw = physical.read_bytes()
        output_hash = hashlib.sha256(raw).hexdigest()
        scratch_bytes = sum(path.stat().st_size for path in Path(scratch).rglob("*") if path.is_file())
        evidence = {
            "fixture": fixture["schema"], "job_id": job_id,
            "fixture_sha256": hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(),
            "rows": len(records), "row_ids": [record["system:index"] for record in records],
            "columns": fixture["csv_selectors"],
            "csv_sha256": output_hash, "csv_bytes": len(raw),
            "scratch_bytes_before_cleanup": scratch_bytes,
            "dispatch": "real ee_service.dispatch -> worker.prepare -> native_run CSV -> worker.finish -> Jobs result reader",
            "network_attempts": 0, "external_account_or_service": False,
            "native_sandbox_google_and_production_acceptance": False,
        }
    assert not Path(scratch).exists()
    if scratch_root_created:
        SCRATCH_ROOT.rmdir()
    report = AUDIT_ROOT / f"feature-preparation-{uuid.uuid4().hex}.json"
    report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
