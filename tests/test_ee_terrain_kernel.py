"""Contracts and opt-in actual GeoTrellis terrain-kernel verification."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

import pytest

from ee_terrain_kernel_helpers import canonical_spec, make_fixture
from ee_kernel_subprocess import run_bounded
from scripts.build_integer_adapter import ROOT, _engine_paths, sha256


TERRAIN_SOURCES = (
    "engine/ee_terrain_spec.scala", "engine/ee_terrain_budget.scala",
    "engine/ee_terrain_metric.scala", "engine/ee_terrain_numeric.scala",
    "engine/ee_terrain_adapter.scala",
)


def test_terrain_native_contract_is_strict_bounded_and_registered():
    adapter = (ROOT / "engine/ee_terrain_adapter.scala").read_text()
    spec = (ROOT / "engine/ee_terrain_spec.scala").read_text()
    budget = (ROOT / "engine/ee_terrain_budget.scala").read_text()
    metric = (ROOT / "engine/ee_terrain_metric.scala").read_text()
    numeric = (ROOT / "engine/ee_terrain_numeric.scala").read_text()
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text()
    probe = (ROOT / "tests/fixtures/ee-terrain-kernel-probe.scala").read_text()
    doc = (ROOT / "docs/gee-python/terrain-native.md").read_text()

    assert 'id = "local_ee_terrain"' in adapter
    assert 'arguments.size() == 1 && arguments.containsKey("spec")' in adapter
    assert "LocalEeTerrainSpec.parse(value)" in adapter
    assert "input.names.length == 1" in adapter
    for cap in ("MaxSourceKeys = 100000L", "MaxDecodedCells = 100000000L",
                "MaxTileDecodedCells = 10000000L", "MaxPerTileWork = 100000000L",
                "MaxTerrainWork = 1000000000L"):
        assert cap in budget
    assert "CoordinateCellWork = 64L" in budget
    assert "OutputWorkPerCell = 256L" in budget
    assert "transformResultObjects" in budget and "explicitArrayBytes" in budget
    assert "STRICT_DUPLICATE_DETECTION" in spec
    assert 'encoded.matches("[0-9a-f]{16}")' in spec
    assert "bits != Long.MinValue" in spec
    assert 'text == canonicalJson(result)' in spec
    assert "canonical 270/45 degree angle defaults" in spec
    assert "1L << 52" in metric and "half-cell" in metric
    assert "new LocalEeTerrainMetric.CoordinateCache" in numeric
    assert "difference(east, west" in numeric and "difference(south, north" in numeric
    assert "Math.getExponent" in numeric and "Math.scalb" in numeric
    assert "DoubleArrayTile(output, outputCols, outputRows, DoubleConstantNoDataCellType)" in numeric
    assert "math.floor(clamped * 255.0d + 0.5d)" in numeric
    assert "typed.bufferTiles(1, bounds, typed.partitioner)" in adapter
    assert "checked.count() == plan.keyCount" in adapter
    assert adapter.index("checked.count()") < adapter.index("bufferTiles")
    assert "BufferTilesRDD(tiles, 1, bounds).toMap" in probe
    assert "SpaceTimeKey" in probe and "verifyTemporalIsolation" in probe
    assert "org.apache.spark.SparkContext" not in adapter + probe
    for source in TERRAIN_SOURCES:
        assert source in builder
    assert "LocalEeTerrainCubeProcessProvider" in builder
    assert "tangent-chord" in doc and "floor(clamp(illumination) * 255 + 0.5)" in doc

    closure = adapter.split("val checked: RDD[(Any, MultibandTile)] = input.source.map", 1)[1].split(
        "require(checked.count()", 1
    )[0]
    assert "input." not in closure
    assert canonical_spec("slope") == (
        '{"azimuth":"4070e00000000000","elevation":"4046800000000000",'
        '"operation":"slope","v":1}'
    )


def test_actual_float64_terrain_matches_independent_pyproj_decimal_reference():
    if os.environ.get("LOCAL_EE_RUN_TERRAIN_KERNEL_TEST") != "1":
        pytest.skip("opt-in trusted GeoTrellis terrain probe; no SparkContext, service, or user code")

    fixture = make_fixture()
    assert fixture["case_count"] == 14
    assert fixture["pixel_count"] == 504
    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:10]}"
    scratch_base = ROOT.parent.parent / "work" / "gee-python-wave45-terrain-unique"
    scratch = scratch_base / run_id
    scratch.mkdir(parents=True, exist_ok=False)
    audit_target = ROOT / "audit/gee-python-wave45/native/terrain" / run_id
    audit_target.mkdir(parents=True, exist_ok=False)
    jar = scratch / "local-ee-integer-adapter.jar"
    successful = False

    def save_audit(name: str, contents: str) -> None:
        (audit_target / name).write_text(contents, encoding="utf-8")

    tracked_sources = [ROOT / source for source in TERRAIN_SOURCES]
    tracked_sources += [
        ROOT / "scripts/build_integer_adapter.py",
        ROOT / "tests/ee_terrain_kernel_helpers.py",
        ROOT / "tests/test_ee_terrain_kernel.py",
        ROOT / "tests/fixtures/ee-terrain-kernel-probe.scala",
    ]
    save_audit("source-hashes.json", json.dumps({
        path.relative_to(ROOT).as_posix(): sha256(path) for path in tracked_sources
    }, indent=2, sort_keys=True) + "\n")

    try:
        cases_path = scratch / "terrain-cases.json"
        fixture_json = json.dumps(fixture, indent=2, allow_nan=False) + "\n"
        cases_path.write_text(fixture_json, encoding="utf-8")
        save_audit("terrain-cases.json", fixture_json)
        build = run_bounded(
            [sys.executable, str(ROOT / "scripts/build_integer_adapter.py"), "--output", str(jar)],
            cwd=str(ROOT), timeout=300,
        )
        save_audit("adapter-build.stdout.txt", build.stdout)
        save_audit("adapter-build.stderr.txt", build.stderr)
        assert build.returncode == 0, build.stderr
        manifest = json.loads(build.stdout)
        assert manifest["adapter"] == "local-ee-integer-adapter"
        assert all(source in manifest["sources"] for source in TERRAIN_SOURCES)
        assert manifest["jar_sha256"] == sha256(jar)
        save_audit("adapter-manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")

        java, _, compiler_tools, runtime_jars, _ = _engine_paths()
        classpath = os.pathsep.join(map(str, [jar, *runtime_jars]))
        classes = scratch / "probe-classes"
        classes.mkdir()
        probe_source = ROOT / "tests/fixtures/ee-terrain-kernel-probe.scala"
        compile_result = run_bounded(
            [str(java), "-cp", os.pathsep.join(map(str, compiler_tools)),
             "scala.tools.nsc.Main", "-classpath", classpath,
             "-d", str(classes), str(probe_source)],
            cwd=str(ROOT), timeout=150,
        )
        save_audit("probe-compile.stdout.txt", compile_result.stdout)
        save_audit("probe-compile.stderr.txt", compile_result.stderr)
        assert compile_result.returncode == 0, compile_result.stderr

        probe_result = run_bounded(
            [str(java), "-cp", str(classes) + os.pathsep + classpath,
             "local.ee.reduce.EeTerrainKernelProbe", str(cases_path)],
            cwd=str(ROOT), timeout=180,
        )
        save_audit("probe-run.stdout.txt", probe_result.stdout)
        save_audit("probe-run.stderr.txt", probe_result.stderr)
        assert probe_result.returncode == 0, probe_result.stderr
        line = next((line for line in probe_result.stdout.splitlines()
                     if line.startswith("TERRAIN_KERNEL_OK ")), "")
        assert line, probe_result.stdout
        counts = dict(re.findall(r"([a-z0-9_]+)=([^ ]+)", line))
        assert counts["cases"] == "14"
        assert counts["manual_pixels"] == "504"
        assert counts["collection_pixels"] == "504"
        assert counts["global_col"] == "4294967294"
        assert counts["budget_256_per_tile"] == "21037312"
        assert counts["budget_256_3x3"] == "189335808"
        assert counts["wire_rejects"] == "9"
        assert counts["budget_rejects"] == "7"
        assert counts["metric_rejects"] == "5"
        assert float(counts["max_angle_error"]) <= 2.0e-7
        save_audit("kernel-result.json", json.dumps({
            "scope": "Actual GeoTrellis Float64 terrain tiles, manual one-cell halo and collection BufferTilesRDD; no SparkContext/service/user code",
            "summary": counts,
            "case_count": fixture["case_count"],
            "pixel_count_per_path": fixture["pixel_count"],
            "reference": "pyproj WGS84 transform plus Decimal-backed ECEF tangent-chord 2x2 solve",
            "angular_tolerance_degrees": 2.0e-7,
            "subnormal_tolerance": "max(32 ulps, 1e-6 relative); expected output must remain nonzero",
            "hillshade": "exact rounded integer in physical Float64 0..255",
            "rejections": {
                "canonical_wire_cases": int(counts["wire_rejects"]),
                "budget_cases": int(counts["budget_rejects"]),
                "grid_metric_cases": int(counts["metric_rejects"]),
            },
            "stdout": probe_result.stdout,
        }, indent=2, sort_keys=True) + "\n")
        successful = True
    except BaseException as error:
        save_audit("failure.txt", f"{type(error).__name__}: {error}\n")
        raise
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        scratch_cleaned = not scratch.exists()
        save_audit("scratch-cleanup-readback.json", json.dumps({
            "scratch": str(scratch), "removed": scratch_cleaned,
            "result": "passed" if successful else "failed; fixture and logs retained in audit",
        }, indent=2, sort_keys=True) + "\n")
        assert scratch_cleaned, f"owned terrain scratch directory remains: {scratch}"
        try:
            scratch_base.rmdir()
        except OSError:
            pass
