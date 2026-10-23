"""Synthetic DEM normalization -> official EE compiler -> GeoTrellis GeoTIFF readback."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
import uuid

import numpy as np
import pytest

from ee_dem_workflow_helpers import (
    PROBE_SHA256, assert_geotiff_reference, assert_normalized,
    compile_products, local_asset_path, reference_case,
)
from dem_workflow_fixture import (
    assert_source_geotiff, fixture_sha256, source_cases, source_item,
    write_source_geotiff,
)
from ee_kernel_subprocess import run_bounded
from gee.dem_contract import COLLECTION_ID
from gee.ee_python_client import configure_local_ee
from scripts.build_integer_adapter import ROOT, _engine_paths, sha256
from scripts.ee_python_api.offline import OfflineGuard


PROBE = ROOT / "tests/fixtures/ee-dem-workflow-probe.scala"
TERRAIN_SOURCES = (
    "engine/ee_terrain_spec.scala", "engine/ee_terrain_budget.scala",
    "engine/ee_terrain_metric.scala", "engine/ee_terrain_numeric.scala",
    "engine/ee_terrain_adapter.scala",
)
WORKFLOW_SOURCES = (
    # The input passes through the actual DEM route and collection admission.
    "gee/ingest.py", "gee/dem_ingest.py", "gee/dem_ingest_helpers.py",
    "gee/dem_contract.py", "gee/compat/earthengine/catalog.py",
    "tests/ee_dem_catalog_helpers.py", "tests/test_ee_dem_catalog.py",
    "tests/test_dem_ingest.py", "tests/dem_workflow_fixture.py",
    # The official-client expression, compiler binding, and canonical spec.
    "gee/ee_python_client.py", "gee/ee_translate.py",
    "gee/compat/earthengine/image_terrain.py",
    "gee/compat/earthengine/terrain_graph.py", "gee/terrain_spec.py",
    "scripts/ee_python_api/offline.py",
    # Synthetic ingest contract and independent readback oracle.
    "tests/dem_ingest_helpers.py", "tests/ee_terrain_kernel_helpers.py",
)


def test_dem_workflow_fixture_and_trusted_probe_hash_contracts():
    assert sha256(PROBE) == PROBE_SHA256
    assert fixture_sha256() == "32a48fe1bb5a1a9db30f33fba7b3bcc426bc4a57bd6876bbfcb30c5615637a5b"
    probe = PROBE.read_text(encoding="utf-8")
    for token in (
        "GeoTiffReader.readSingleband(inputPath)",
        "LocalEeTerrainNumeric.applyBufferedTile(",
        "SinglebandGeoTiff(result.tile, extent, source.crs).write(outputPath)",
        "GeoTiffReader.readSingleband(outputPath)",
        "selected_source_item_id",
        "DEM_GEO_TIFF_TERRAIN_OK",
    ):
        assert token in probe


def test_dem_workflow_reference_fixture_has_masks_borders_and_hillshade_range():
    case = source_cases()[0]
    elevation = case["raw"].astype(np.float64) * case["scale"] + case["offset"]
    slope = reference_case(elevation, case["valid"], case["transform"], case["crs"], "slope")
    aspect = reference_case(elevation, case["valid"], case["transform"], case["crs"], "aspect")
    shade = reference_case(elevation, case["valid"], case["transform"], case["crs"], "hillshade")
    assert slope[8 * case["width"] + 2] == 0.0  # valid flat aspect/slope zone
    assert aspect[8 * case["width"] + 2] == 0.0
    assert slope[0] is None and slope[7 * case["width"] + 4] is None
    assert shade[8 * case["width"] + 6] == 255.0
    assert shade[8 * case["width"] + 10] == 0.0


def test_actual_dem_to_terrain_geo_tiff_workflow():
    if os.environ.get("LOCAL_EE_RUN_DEM_WORKFLOW_TEST") != "1":
        pytest.skip("opt-in trusted synthetic DEM file workflow; no SparkContext, service, or user data")

    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:10]}"
    scratch_base = ROOT.parents[1] / "work/gee-python-wave46-dem-unique"
    scratch = scratch_base / run_id
    scratch.mkdir(parents=True, exist_ok=False)
    audit = ROOT / "audit/gee-python-wave46/native/dem" / run_id
    audit.mkdir(parents=True, exist_ok=False)
    data_root = scratch / "data"
    input_root = scratch / "inputs"
    output_root = scratch / "outputs"
    for folder in (data_root, input_root, output_root):
        folder.mkdir(parents=True)
    successful = False
    records = []

    def save(name, value):
        path = audit / name
        if isinstance(value, str):
            path.write_text(value, encoding="utf-8")
        else:
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                       sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")

    try:
        tracked = [ROOT / path for path in TERRAIN_SOURCES + WORKFLOW_SOURCES]
        tracked += [PROBE, ROOT / "scripts/build_integer_adapter.py",
                    ROOT / "vendor/earthengine-js/algorithms.json",
                    ROOT / "tests/ee_dem_workflow_helpers.py", Path(__file__).resolve()]
        source_hashes = {path.relative_to(ROOT).as_posix(): sha256(path)
                         for path in tracked}
        save("source-hashes.json", source_hashes)
        from gee import dem_ingest, ingest

        registered = []
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(dem_ingest, "ROOT", data_root)
        monkeypatch.setattr(dem_ingest.db, "query", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(dem_ingest, "register",
                            lambda cid, meta, item, budget=None:
                            registered.append((cid, json.loads(json.dumps(meta)),
                                               json.loads(json.dumps(item)))))
        budget = ingest.IngestBudget(root=scratch, max_bytes=32 * 1024 * 1024, min_free=0)
        cases = source_cases()
        for case in cases:
            source_path = input_root / f"{case['name']}.tif"
            write_source_geotiff(source_path, case)
            assert_source_geotiff(source_path, case)
            source = source_item(source_path, case)
            item_id = ingest.optical_item(
                source, COLLECTION_ID, case["request_bbox"], sign=lambda href: href, budget=budget,
            )
            assert len(registered) == len(records) + 1
            cid, metadata, item = registered[-1]
            assert cid == COLLECTION_ID and item["id"] == item_id
            cog = local_asset_path(data_root, item["assets"]["elevation"]["href"])
            values, valid = assert_normalized(case, metadata, item, cog)
            source_metadata = local_asset_path(data_root, item["properties"]["gee:source_metadata"])
            source_bytes = source_metadata.read_bytes()
            assert hashlib.sha256(source_bytes).hexdigest() == item["properties"]["gee:source_metadata_sha256"]
            save(f"{case['name']}-inputs.json", {
                "synthetic_source_sha256": sha256(source_path),
                "normalized_cog_sha256": sha256(cog),
                "source_metadata_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "source_metadata": source,
                "catalog_metadata": metadata,
                "catalog_item": item,
                "normalized_valid_cells": int(valid.sum()),
                "normalized_nodata_cells": int((~valid).sum()),
                "normalized_min": float(np.nanmin(values)),
                "normalized_max": float(np.nanmax(values)),
            })

            with OfflineGuard() as guard:
                ee = configure_local_ee(
                    "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                    signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
                )
                compiled, specs = compile_products(ee, metadata, item)
            assert guard.evidence()["attempt_count"] == 0
            save(f"{case['name']}-compiled-graph.json", compiled["process_graph"])

            java, _, compiler_tools, runtime_jars, _ = _engine_paths()
            adapter_jar = scratch / "local-ee-integer-adapter.jar"
            if not adapter_jar.exists():
                build = run_bounded(
                    [sys.executable, str(ROOT / "scripts/build_integer_adapter.py"),
                     "--output", str(adapter_jar)], cwd=str(ROOT), timeout=300,
                )
                save("adapter-build.stdout.txt", build.stdout)
                save("adapter-build.stderr.txt", build.stderr)
                assert build.returncode == 0, build.stderr
                manifest = json.loads(build.stdout)
                assert manifest["jar_sha256"] == sha256(adapter_jar)
                assert all(source in manifest["sources"] for source in TERRAIN_SOURCES)
                save("adapter-manifest.json", manifest)
            classpath = os.pathsep.join(map(str, [adapter_jar, *runtime_jars]))
            classes = scratch / "probe-classes"
            if not classes.exists():
                classes.mkdir()
                compile_probe = run_bounded(
                    [str(java), "-cp", os.pathsep.join(map(str, compiler_tools)),
                     "scala.tools.nsc.Main", "-classpath", classpath,
                     "-d", str(classes), str(PROBE)], cwd=str(ROOT), timeout=150,
                )
                save("probe-compile.stdout.txt", compile_probe.stdout)
                save("probe-compile.stderr.txt", compile_probe.stderr)
                assert compile_probe.returncode == 0, compile_probe.stderr

            case_record = {"name": case["name"], "source_item_id": item_id,
                           "source_crs": case["crs"], "operations": {}}
            records.append(case_record)
            for operation, spec in specs.items():
                output = output_root / f"{case['name']}-{operation}.tif"
                result = run_bounded(
                    [str(java), "-cp", str(classes) + os.pathsep + classpath,
                     "local.ee.reduce.EeDemWorkflowProbe", str(cog), str(output), spec, item_id],
                    cwd=str(ROOT), timeout=180,
                )
                save(f"{case['name']}-{operation}.stdout.txt", result.stdout)
                save(f"{case['name']}-{operation}.stderr.txt", result.stderr)
                assert result.returncode == 0, result.stderr
                line = next((line for line in result.stdout.splitlines()
                             if line.startswith("DEM_GEO_TIFF_TERRAIN_OK ")), "")
                assert line, result.stdout
                native = json.loads(line.removeprefix("DEM_GEO_TIFF_TERRAIN_OK "))
                assert native["operation"] == operation
                assert native["selected_source_item_id"] == item_id
                assert native["input_nodata"] == 2
                counts = assert_geotiff_reference(output, values, valid, case, spec, native)
                case_record["operations"][operation] = {
                    "compiled_spec": spec, "native_counts": native,
                    "readback_sha256": sha256(output), **counts,
                }
        assert len(registered) == 2 and len(records) == 2
        save("dem-workflow-result.json", {
            "scope": (
                "Synthetic source GeoTIFF normalized by gee.ingest.optical_item; official "
                "SDK graph compiled against captured local catalog metadata; exact selected "
                "item id and LocalEeTerrainSpec passed to standalone GeoTrellis numeric kernel; "
                "GeoTrellis wrote each output GeoTIFF and Rasterio independently read it back. "
                "No full graph executor, SparkContext, service, private data, or Google comparison."
            ),
            "source_fixture_sha256": fixture_sha256(),
            "probe_sha256": sha256(PROBE),
            "source_hashes": source_hashes,
            "cases": records,
        })
        successful = True
    except BaseException as error:
        save("failure.json", {
            "type": type(error).__name__, "message": str(error),
            "traceback": traceback.format_exc(), "completed_cases": records,
        })
        raise
    finally:
        monkeypatch.undo() if "monkeypatch" in locals() else None
        shutil.rmtree(scratch, ignore_errors=True)
        cleaned = not scratch.exists()
        save("scratch-cleanup-readback.json", {
            "scratch": str(scratch), "removed": cleaned,
            "result": "passed" if successful else "failed; fixture, hashes and logs retained in audit",
        })
        assert cleaned, f"owned DEM workflow scratch remains: {scratch}"
        try:
            scratch_base.rmdir()
        except OSError:
            pass
