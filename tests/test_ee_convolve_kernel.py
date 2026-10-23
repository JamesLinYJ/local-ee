"""Contracts and opt-in actual GeoTrellis Float64 Image.convolve kernel probe."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import uuid

import pytest

from ee_convolve_kernel_helpers import make_fixture
from ee_kernel_subprocess import run_bounded
from scripts.build_integer_adapter import ROOT, _engine_paths, sha256


def test_convolve_spi_uses_strict_exact_float64_kernel_and_bounded_halos():
    adapter = (ROOT / "engine/ee_convolve_adapter.scala").read_text()
    spec = (ROOT / "engine/ee_convolve_spec.scala").read_text()
    numeric = (ROOT / "engine/ee_convolve_numeric.scala").read_text()
    probe = (ROOT / "tests/fixtures/ee-convolve-kernel-probe.scala").read_text()
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text()
    budget = spec.split("object LocalEeConvolveBudget", 1)[1]
    assert 'id = "local_ee_convolve"' in adapter
    assert 'arguments.size() == 1 && arguments.containsKey("spec")' in adapter
    assert "LocalEeConvolveSpec.parse(value)" in adapter
    assert "input.names.length == 1" in adapter
    assert "MaxSourceKeys = 100000L" in budget
    assert "MaxDecodedCells = 100000000L" in budget
    assert "MaxTileDecodedCells = 10000000L" in budget
    assert "MaxConvolveWork = 1000000000L" in budget
    assert "MaxPerTileWork = 100000000L" in budget
    assert "exactAccumulatorLimbs" in spec
    assert "unitExponent" in spec
    assert "Math.multiplyExact(2L, limbs)" in budget
    assert "Math.multiplyExact(limbs, 8L)" in budget
    assert "def estimate(keyCount: Long" in budget
    assert "per-tile work limit (${result.perTileWork})" in budget
    assert "selected == selected.sortBy(value => (value.dy, value.dx))" in spec
    assert "STRICT_DUPLICATE_DETECTION" in spec
    assert 'text == canonicalJson(result)' in spec
    assert 'encoded.matches("[0-9a-f]{16}")' in spec
    assert "bits != Long.MinValue" in spec
    assert "if (radius == 0) typed.map" in adapter
    assert "typed.bufferTiles(radius, bounds, typed.partitioner)" in adapter
    assert "checked.count() == plan.keyCount" in adapter
    assert adapter.index("checked.count()") < adapter.index("bufferTiles")
    assert "applyBufferedTile" in numeric and "exactProductUnits" in numeric
    assert "roundRightToEven" in numeric
    assert "coefficient.significand" in numeric and "coefficient.exponent" in numeric
    assert "subnormalShift >= 0" in numeric
    assert "final Float64 result overflowed" in numeric
    assert "completeSupport = false" in numeric
    assert "coefficient.isZero" not in numeric  # zero taps were removed from spec.active
    assert "BufferTilesRDD(tiles, radius, bounds).toMap" in probe
    assert "SpaceTimeKey" in probe and "verifyTemporalIsolation" in probe
    assert "SparkContext" not in adapter + probe
    for source in ("engine/ee_convolve_spec.scala", "engine/ee_convolve_numeric.scala",
                   "engine/ee_convolve_adapter.scala"):
        assert source in builder
    assert "LocalEeConvolveCubeProcessProvider" in builder

    closure = adapter.split("val checked: RDD[(Any, MultibandTile)] = input.source.map", 1)[1].split(
        "require(checked.count()", 1
    )[0]
    assert "input." not in closure


def test_actual_float64_convolve_matches_independent_whole_raster_reference():
    if os.environ.get("LOCAL_EE_RUN_CONVOLVE_KERNEL_TEST") != "1":
        pytest.skip("opt-in trusted GeoTrellis convolve probe; no SparkContext, service, or user code")
    fixture = make_fixture()
    assert fixture["case_count"] == 11
    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:10]}"
    scratch = ROOT.parent.parent / "work" / f"gee-python-wave43-convolve-{run_id}"
    scratch.mkdir(parents=True, exist_ok=False)
    jar = scratch / "local-ee-integer-adapter.jar"
    builder = ROOT / "scripts/build_integer_adapter.py"
    audit_dir = os.environ.get("GEE_AUDIT_DIR")
    audit_target = Path(audit_dir) / f"convolve-kernel-{run_id}" if audit_dir else None
    if audit_target:
        audit_target.mkdir(parents=True, exist_ok=False)

    def save_audit(name: str, contents: str) -> None:
        if audit_target:
            (audit_target / name).write_text(contents, encoding="utf-8")

    try:
        cases_path = scratch / "convolve-cases.json"
        cases_path.write_text(json.dumps(fixture, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        build = run_bounded(
            [sys.executable, str(builder), "--output", str(jar)],
            cwd=str(ROOT), timeout=240,
        )
        save_audit("adapter-build.stdout.txt", build.stdout)
        save_audit("adapter-build.stderr.txt", build.stderr)
        assert build.returncode == 0, build.stderr
        manifest = json.loads(build.stdout)
        assert manifest["adapter"] == "local-ee-integer-adapter"
        for source in ("engine/ee_convolve_spec.scala", "engine/ee_convolve_numeric.scala",
                       "engine/ee_convolve_adapter.scala"):
            assert source in manifest["sources"]
        assert manifest["jar_sha256"] == sha256(jar)

        java, _, compiler_tools, runtime_jars, _ = _engine_paths()
        classpath = os.pathsep.join(map(str, [jar, *runtime_jars]))
        classes = scratch / "probe-classes"
        classes.mkdir()
        probe_source = ROOT / "tests/fixtures/ee-convolve-kernel-probe.scala"
        compile_result = run_bounded(
            [
                str(java), "-cp", os.pathsep.join(map(str, compiler_tools)),
                "scala.tools.nsc.Main", "-classpath", classpath,
                "-d", str(classes), str(probe_source),
            ], cwd=str(ROOT), timeout=120,
        )
        save_audit("probe-compile.stdout.txt", compile_result.stdout)
        save_audit("probe-compile.stderr.txt", compile_result.stderr)
        assert compile_result.returncode == 0, compile_result.stderr

        probe_result = run_bounded(
            [
                str(java), "-cp", str(classes) + os.pathsep + classpath,
                "local.ee.reduce.EeConvolveKernelProbe", str(cases_path),
            ], cwd=str(ROOT), timeout=120,
        )
        save_audit("probe-run.stdout.txt", probe_result.stdout)
        save_audit("probe-run.stderr.txt", probe_result.stderr)
        assert probe_result.returncode == 0, probe_result.stderr
        expected = (
            f"CONVOLVE_KERNEL_OK cases={fixture['case_count']} manual_pixels={fixture['pixel_count']} "
            f"collection_pixels={fixture['pixel_count']} temporal_keys=2 "
            "budget_3x3_per_tile=58065924 budget_7x7_per_tile=238947364 "
            "budget_7x7_result=rejected budget_checks=9"
        )
        assert expected in probe_result.stdout

        result = {
            "scope": "Trusted standalone GeoTrellis Float64 convolution kernel, manual halo assembly, and collection BufferTilesRDD; no SparkContext, service, or user code",
            "stdout": probe_result.stdout,
            "stderr": probe_result.stderr,
            "case_count": fixture["case_count"],
            "pixel_count": fixture["pixel_count"],
            "probe_sha256": sha256(probe_source),
            "manifest": manifest,
            "coverage": [
                "independent Fraction.from_float whole-raster reference and raw-bit comparison",
                "asymmetric signed correlation placement across spatial tile seams",
                "missing source tile and masked nonzero support return NaN; zero taps need no neighbor",
                "center mask preservation and canonical all-zero single-center behavior",
                "exact large product cancellation, subnormal products/residuals, halfway ties, and normal-boundary products",
                "deterministic raw-bit-generated finite raster values and a nine-coefficient exact Fraction reference",
                "dynamic common-unit accumulator bounds retain 66 limbs for mixed smallest-subnormal/largest-finite weights",
                "positive and negative final underflow preserve round-to-nearest ties-to-even zero sign",
                "strict canonical JSON, duplicate keys, coefficient shape/order, finite weights, and negative-zero rejection",
                "SpaceTimeKey collection buffering preserves observed time keys without cross-time support",
                "exact work/cell/key budgets, small-tile halo boundary, and explicit final overflow failure",
                "3x3 at 256x256 accepted and 7x7 at 256x256 reports its modeled per-tile work before rejection",
            ],
            "limitations": [
                "The positive-radius GeoTrellis buffer path is checked with its collection overload, not a SparkContext or scheduled RDD job",
                "The full cube task, macOS sandbox, service, browser, deployment, and Google numerical parity are not established",
                "Strict complete support for nonzero coefficients is the declared local policy and has no Google behavior comparison",
            ],
        }
        save_audit("convolve-cases.json", json.dumps(fixture, indent=2) + "\n")
        save_audit("adapter-build.manifest.json", json.dumps(manifest, indent=2) + "\n")
        save_audit("convolve-result.json", json.dumps(result, indent=2) + "\n")
    finally:
        import shutil

        shutil.rmtree(scratch, ignore_errors=True)
