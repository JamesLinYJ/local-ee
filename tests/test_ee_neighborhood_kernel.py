"""Contracts and opt-in actual GeoTrellis Float64 neighborhood kernel probe."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import uuid

import pytest

from ee_kernel_subprocess import run_bounded
from ee_neighborhood_kernel_helpers import make_fixture
from scripts.build_integer_adapter import ROOT, _engine_paths, sha256


def test_neighborhood_spi_has_strict_wire_exact_statistics_and_bounded_halos():
    adapter = (ROOT / "engine/ee_neighborhood_adapter.scala").read_text()
    spec = (ROOT / "engine/ee_neighborhood_spec.scala").read_text()
    budget = (ROOT / "engine/ee_neighborhood_budget.scala").read_text()
    exact = (ROOT / "engine/ee_neighborhood_exact.scala").read_text()
    statistics = (ROOT / "engine/ee_neighborhood_statistics.scala").read_text()
    numeric = (ROOT / "engine/ee_neighborhood_numeric.scala").read_text()
    probe = (ROOT / "tests/fixtures/ee-neighborhood-kernel-probe.scala").read_text()
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text()
    assert 'id = "local_ee_neighborhood"' in adapter
    assert 'arguments.size() == 1 && arguments.containsKey("spec")' in adapter
    assert "input.names.length == 1" in adapter
    assert "LocalEeNeighborhoodSpec.parse(value)" in adapter
    assert "MaxSourceKeys = 100000L" in budget
    assert "MaxDecodedCells = 100000000L" in budget
    assert "MaxTileDecodedCells = 10000000L" in budget
    assert "MaxNeighborhoodWork = 1000000000L" in budget
    assert "MaxPerTileWork = 100000000L" in budget
    assert "selected == selected.sortBy(value => (value.dy, value.dx))" in spec
    assert "STRICT_DUPLICATE_DETECTION" in spec
    assert "text == canonicalJson(result)" in spec
    assert 'encoded.matches("[0-9a-f]{16}")' in spec
    assert "strictly positive finite binary64" in spec
    assert "weightBits == OneBits" in spec
    assert "if (radius == 0) typed.map" in adapter
    assert "typed.bufferTiles(radius, bounds, typed.partitioner)" in adapter
    assert "checked.count() == plan.keyCount" in adapter
    assert adapter.index("checked.count()") < adapter.index("bufferTiles")
    assert "roundedSqrt" in exact and "integerRatio.sqrt()" in exact
    assert "midpointSquared" in exact and "roundQuotientToEven" in exact
    assert "exactMoments" in statistics
    assert "squares.multiply(totalWeight).subtract(total.multiply(total))" in statistics
    assert "count < 2" in statistics
    assert "weightUnitExponent" in statistics and "significand" in statistics
    assert "spec.skipMasked && center.isNaN" in numeric
    assert "value.isNaN" in numeric
    assert "BufferTilesRDD(tiles, spec.radius, bounds).toMap" in probe
    assert "SpaceTimeKey" in probe and "verifyTemporalIsolation" in probe
    assert "SparkContext" not in adapter + probe
    for source in (
        "engine/ee_neighborhood_spec.scala", "engine/ee_neighborhood_budget.scala",
        "engine/ee_neighborhood_exact.scala", "engine/ee_neighborhood_statistics.scala",
        "engine/ee_neighborhood_numeric.scala", "engine/ee_neighborhood_adapter.scala",
    ):
        assert source in builder
    assert "LocalEeNeighborhoodCubeProcessProvider" in builder
    closure = adapter.split("val checked: RDD[(Any, MultibandTile)] = input.source.map", 1)[1].split(
        "require(checked.count()", 1
    )[0]
    assert "input." not in closure


def test_actual_float64_neighborhood_matches_independent_whole_grid_reference():
    if os.environ.get("LOCAL_EE_RUN_NEIGHBORHOOD_KERNEL_TEST") != "1":
        pytest.skip("opt-in trusted GeoTrellis neighborhood probe; no SparkContext, service, or user code")
    fixture = make_fixture()
    assert fixture["case_count"] == 19
    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:10]}"
    scratch = ROOT.parent.parent / "work" / f"gee-python-wave44-neighborhood-{run_id}"
    scratch.mkdir(parents=True, exist_ok=False)
    jar = scratch / "local-ee-integer-adapter.jar"
    builder = ROOT / "scripts/build_integer_adapter.py"
    audit_dir = os.environ.get("GEE_AUDIT_DIR")
    audit_target = Path(audit_dir) / f"neighborhood-kernel-{run_id}" if audit_dir else None
    if audit_target:
        audit_target.mkdir(parents=True, exist_ok=False)

    def save_audit(name: str, contents: str) -> None:
        if audit_target:
            (audit_target / name).write_text(contents, encoding="utf-8")

    try:
        cases_path = scratch / "neighborhood-cases.json"
        cases_path.write_text(json.dumps(fixture, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        build = run_bounded(
            [sys.executable, str(builder), "--output", str(jar)], cwd=str(ROOT), timeout=300,
        )
        save_audit("adapter-build.stdout.txt", build.stdout)
        save_audit("adapter-build.stderr.txt", build.stderr)
        assert build.returncode == 0, build.stderr
        manifest = json.loads(build.stdout)
        assert manifest["adapter"] == "local-ee-integer-adapter"
        for source in (
            "engine/ee_neighborhood_spec.scala", "engine/ee_neighborhood_budget.scala",
            "engine/ee_neighborhood_exact.scala", "engine/ee_neighborhood_statistics.scala",
            "engine/ee_neighborhood_numeric.scala", "engine/ee_neighborhood_adapter.scala",
        ):
            assert source in manifest["sources"]
        assert manifest["jar_sha256"] == sha256(jar)

        java, _, compiler_tools, runtime_jars, _ = _engine_paths()
        classpath = os.pathsep.join(map(str, [jar, *runtime_jars]))
        classes = scratch / "probe-classes"
        classes.mkdir()
        probe_source = ROOT / "tests/fixtures/ee-neighborhood-kernel-probe.scala"
        compile_result = run_bounded(
            [str(java), "-cp", os.pathsep.join(map(str, compiler_tools)),
             "scala.tools.nsc.Main", "-classpath", classpath, "-d", str(classes), str(probe_source)],
            cwd=str(ROOT), timeout=120,
        )
        save_audit("probe-compile.stdout.txt", compile_result.stdout)
        save_audit("probe-compile.stderr.txt", compile_result.stderr)
        assert compile_result.returncode == 0, compile_result.stderr

        probe_result = run_bounded(
            [str(java), "-cp", str(classes) + os.pathsep + classpath,
             "local.ee.reduce.EeNeighborhoodKernelProbe", str(cases_path)],
            cwd=str(ROOT), timeout=180,
        )
        save_audit("probe-run.stdout.txt", probe_result.stdout)
        save_audit("probe-run.stderr.txt", probe_result.stderr)
        assert probe_result.returncode == 0, probe_result.stderr
        assert (f"NEIGHBORHOOD_KERNEL_OK cases={fixture['case_count']} "
                f"manual_pixels={fixture['pixel_count']} collection_pixels={fixture['pixel_count']} "
                "temporal_keys=4 budget_3x3_per_tile=64291844 "
                "budget_7x7_per_tile=260901924 budget_7x7_result=rejected "
                "budget_3x3_variance_per_tile=243270660 budget_3x3_variance_result=rejected "
                "budget_128_variance_per_tile=60817924 "
                "budget_3x3_stdDev_per_tile=300155908 "
                "budget_3x3_sampleStdDev_per_tile=300221444 budget_checks=13") in probe_result.stdout

        result = {
            "scope": "Trusted standalone GeoTrellis Float64 neighborhood kernel, manual halo assembly, and collection BufferTilesRDD; no SparkContext, service, or user code",
            "stdout": probe_result.stdout,
            "stderr": probe_result.stderr,
            "case_count": fixture["case_count"],
            "pixel_count": fixture["pixel_count"],
            "probe_sha256": sha256(probe_source),
            "manifest": manifest,
            "coverage": [
                "independent Fraction and Decimal whole-grid references with raw-bit output checks",
                "all 12 supported operations, weighted and unweighted contracts, and empty support NoData",
                "weighted cancellation, overflowing intermediates, subnormal/huge coefficient range, and large common offsets",
                "spatial seams, masked and missing neighbors, skip_masked true/false, missing output keys, and radius zero",
                "strict canonical JSON, duplicate/order/range/type/weight validation, and unweighted coefficient constraints",
                "SpaceTimeKey collection buffering preserves observed keys and isolates timestamps",
                "unchanged key/cell/tile/work budgets; 3x3 and 7x7 256x256 readbacks include exact arithmetic costs",
                "both stdDev variants are directly checked to charge more than their variance counterpart",
                "explicit final Float64 sum overflow failure",
            ],
            "limitations": [
                "the collection buffer path is tested without SparkContext or a scheduled RDD job",
                "the full cube process, sandbox, service, browser, deployment, private real data, and Google parity are not established",
                "variance is budget-rejected at 3x3 256x256 but accepted at 128x128 under the unchanged cap; exact estimates are recorded",
            ],
        }
        save_audit("neighborhood-cases.json", json.dumps(fixture, indent=2) + "\n")
        save_audit("adapter-build.manifest.json", json.dumps(manifest, indent=2) + "\n")
        save_audit("neighborhood-result.json", json.dumps(result, indent=2) + "\n")
    finally:
        import shutil

        shutil.rmtree(scratch, ignore_errors=True)
