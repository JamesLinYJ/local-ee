"""Contracts and opt-in actual GeoTrellis Float64 focal tile-kernel probe."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import uuid

import pytest

from ee_focal_kernel_helpers import make_fixture
from ee_kernel_subprocess import run_bounded
from scripts.build_integer_adapter import ROOT, _engine_paths, sha256


def test_focal_spi_preflights_work_and_uses_fresh_spatial_halos():
    adapter = (ROOT / "engine/ee_focal_adapter.scala").read_text()
    spec = (ROOT / "engine/ee_focal_spec.scala").read_text()
    numeric = (ROOT / "engine/ee_focal_numeric.scala").read_text()
    probe = (ROOT / "tests/fixtures/ee-focal-kernel-probe.scala").read_text()
    budget = spec.split("object LocalEeFocalBudget", 1)[1]
    assert 'id = "local_ee_focal"' in adapter
    assert 'arguments.size() == 1 && arguments.containsKey("spec")' in adapter
    assert 'case value: String => LocalEeFocalSpec.parse(value)' in adapter
    assert "input.names.length == 1" in adapter
    assert "MaxFocalWork = 1000000000L" in budget
    assert "MaxPerTileWork = 100000000L" in budget
    assert "MaxDecodedCells = 100000000L" in budget
    assert "MaxTileDecodedCells = 10000000L" in budget
    assert "allIterationBufferCells <= MaxDecodedCells" in budget
    assert "ExactAccumulatorLimbs = 34L" in budget
    assert "MeanNeighborLimbWork = ExactAccumulatorLimbs * 2L" in budget
    assert "MeanRoundingLimbWork = ExactAccumulatorLimbs * 8L" in budget
    assert "MedianMidpointLimbWork = ExactAccumulatorLimbs * 12L" in budget
    assert 'case "mean" => Math.addExact' in budget and 'case "median" => MedianMidpointLimbWork' in budget
    assert "subnormalUnits(values(index))" in numeric
    assert "roundedAverage(subnormalUnits(left).add(subnormalUnits(right)), 2)" in numeric
    assert "LocalEeFocalBudget.plan(13L, 32, 32, spec)" in probe
    assert "LocalEeFocalBudget.plan(1L, 1400, 1400, pixelWork)" in probe
    assert "LocalEeFocalBudget.plan(1L, 256, 256, ordinaryMean)" in probe
    assert "LocalEeFocalBudget.plan(1L, 256, 256, ordinaryMedian)" in probe
    assert "LocalEeFocalBudget.plan(1L, 3, 2, edgeRadius)" in probe
    assert "positive neighborhood radius must be smaller than the smaller tile dimension" in spec
    assert "BufferTilesRDD(tiles, radius, bounds).toMap" in probe
    assert "checked.count() == plan.keyCount" in adapter
    assert adapter.index("checked.count()") < adapter.index("runIterations(checked")
    assert "typed.bufferTiles(radius, bounds, typed.partitioner)" in adapter
    assert "if (radius == 0) typed.map" in adapter
    assert "applyUnbuffered(tile, cols, rows, spec)" in adapter
    assert 'case "spatial" => spatialPass' in adapter and 'case "temporal" => temporalPass' in adapter
    assert "while (iteration < spec.iterations)" in adapter
    assert "copyAsDouble(tile, 1, cols, rows)" in adapter
    assert 'Set("mean", "min", "max", "median", "mode")' in spec
    assert "selectedOffsets == selectedOffsets.sortBy(offset => (offset.dy, offset.dx))" in spec
    assert "selectedOffsets.distinct.length == selectedOffsets.length" in spec
    assert 'text == canonicalJson(result)' in spec
    checked_map = adapter.split("val checked: RDD[(Any, MultibandTile)] = input.source.map", 1)[1].split(
        "require(checked.count()", 1
    )[0]
    assert "input." not in checked_map
    assert "SparkContext" not in adapter


def test_actual_float64_focal_kernel_matches_whole_raster_reference():
    if os.environ.get("LOCAL_EE_RUN_FOCAL_KERNEL_TEST") != "1":
        pytest.skip("opt-in trusted GeoTrellis focal tile-kernel probe; no SparkContext, service, or user code")
    fixture = make_fixture()
    assert fixture["case_count"] == 33
    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:10]}"
    scratch = ROOT.parent.parent / "work" / f"gee-python-wave42-focal-{run_id}"
    scratch.mkdir(parents=True, exist_ok=False)
    jar = scratch / "local-ee-integer-adapter.jar"
    builder = ROOT / "scripts/build_integer_adapter.py"
    audit_dir = os.environ.get("GEE_AUDIT_DIR")
    audit_target = Path(audit_dir) / f"focal-kernel-{run_id}" if audit_dir else None
    if audit_target:
        audit_target.mkdir(parents=True, exist_ok=False)
    try:
        build = run_bounded(
            [sys.executable, str(builder), "--output", str(jar)],
            cwd=str(ROOT),
            timeout=240,
        )
        assert build.returncode == 0, build.stderr
        manifest = json.loads(build.stdout)
        assert manifest["adapter"] == "local-ee-integer-adapter"
        assert "engine/ee_focal_spec.scala" in manifest["sources"]
        assert "engine/ee_focal_numeric.scala" in manifest["sources"]
        assert "engine/ee_focal_adapter.scala" in manifest["sources"]
        assert manifest["jar_sha256"] == sha256(jar)

        java, _, compiler_tools, runtime_jars, _ = _engine_paths()
        classpath = os.pathsep.join(map(str, [jar, *runtime_jars]))
        classes = scratch / "probe-classes"
        classes.mkdir()
        probe_source = ROOT / "tests/fixtures/ee-focal-kernel-probe.scala"
        compile_result = run_bounded(
            [
                str(java), "-cp", os.pathsep.join(map(str, compiler_tools)),
                "scala.tools.nsc.Main", "-classpath", classpath,
                "-d", str(classes), str(probe_source),
            ],
            cwd=str(ROOT),
            timeout=120,
        )
        assert compile_result.returncode == 0, compile_result.stderr

        cases_path = scratch / "focal-cases.json"
        cases_path.write_text(json.dumps(fixture, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        probe_result = run_bounded(
            [
                str(java), "-cp", str(classes) + os.pathsep + classpath,
                "local.ee.reduce.EeFocalKernelProbe", str(cases_path),
            ],
            cwd=str(ROOT),
            timeout=120,
        )
        assert probe_result.returncode == 0, probe_result.stderr
        expected = (
            f"FOCAL_KERNEL_OK cases={fixture['case_count']} manual_pixels={fixture['pixel_count']} "
            f"collection_pixels={fixture['pixel_count']} temporal_keys=4 budget_checks=7"
        )
        assert expected in probe_result.stdout

        result = {
            "scope": "Trusted standalone GeoTrellis Float64 kernel plus positive-radius collection BufferTilesRDD overload and zero-radius same-tile path; no SparkContext, service, or user code",
            "stdout": probe_result.stdout,
            "stderr": probe_result.stderr,
            "case_count": fixture["case_count"],
            "pixel_count": fixture["pixel_count"],
            "valid_pixel_count": fixture["valid_pixel_count"],
            "probe_sha256": sha256(probe_source),
            "manifest": manifest,
            "coverage": [
                "all five focal operations over independent whole-raster references",
                "manual and GeoTrellis collection-buffered cross-tile neighborhoods, absent source tile, and two regenerated halo iterations",
                "missing-neighbor NoData, NaN preservation/fill, empty windows, signed-zero mode ties, and near-maximum Float64 values",
                "all-NoData windows, single-offset identity, adjacent-large rounding, subnormal preservation, and cancellation residuals",
                "Fraction-based exact mean/midpoint references with raw-bit-identical near-max, normal/subnormal boundary, and halfway-tie results",
                "deterministic finite binary64 stress neighborhoods checked with exact rational means and medians",
                "SpaceTimeKey collection buffering preserves observed times without cross-time mixing",
                "zero-radius cases use the direct same-tile kernel and do not ask BufferTilesRDD to crop empty neighbor slices",
                "strict canonical JSON version, fields, operation, offsets, byte size, and trailing-content rejection",
            ],
            "limitations": [
                "The locked GeoTrellis BufferTiles collection overload fails when a positive radius equals the smaller tile dimension; preflight rejects that boundary",
                "The collection overload also fails for radius zero by cropping an empty neighbor slice; the adapter uses its direct same-tile path instead",
                "Collection BufferTilesRDD overload is tested without SparkContext; Spark RDD scheduling and the full adapter cube path are not run by this probe",
                "Does not establish native sandbox, service, browser, deployment, or Google acceptance",
            ],
        }
        result_path = scratch / "focal-result.json"
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

        if audit_target:
            (audit_target / "focal-cases.json").write_text(
                cases_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
            (audit_target / "focal-result.json").write_text(
                result_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
            (audit_target / "focal-adapter.manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            (audit_target / "adapter-build.stdout.txt").write_text(build.stdout, encoding="utf-8")
            (audit_target / "adapter-build.stderr.txt").write_text(build.stderr, encoding="utf-8")
            (audit_target / "probe-compile.stdout.txt").write_text(compile_result.stdout, encoding="utf-8")
            (audit_target / "probe-compile.stderr.txt").write_text(compile_result.stderr, encoding="utf-8")
            (audit_target / "probe-run.stdout.txt").write_text(probe_result.stdout, encoding="utf-8")
            (audit_target / "probe-run.stderr.txt").write_text(probe_result.stderr, encoding="utf-8")
    finally:
        import shutil

        shutil.rmtree(scratch, ignore_errors=True)
