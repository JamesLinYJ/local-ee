"""Opt-in actual GeoTrellis Float32 pixel-math kernel probe; no SparkContext."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import uuid

import pytest

from ee_pixel_math_kernel_helpers import (
    OPERATION_ARITIES,
    assert_reference_anchors,
    make_fixture,
)
from ee_kernel_subprocess import run_bounded
from scripts.build_integer_adapter import ROOT, _engine_paths, sha256


pytestmark = pytest.mark.skipif(
    os.environ.get("LOCAL_EE_RUN_PIXEL_MATH_KERNEL_TEST") != "1",
    reason="opt-in trusted GeoTrellis pixel-math tile kernel; no Spark, service, or user-code acceptance",
)


def test_actual_float32_tile_math_matches_independent_references():
    assert_reference_anchors()
    fixture = make_fixture()
    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:10]}"
    scratch = ROOT.parent.parent / "work" / f"gee-python-wave34-{run_id}"
    scratch.mkdir(parents=True, exist_ok=False)
    jar = scratch / "local-ee-integer-adapter.jar"
    builder = ROOT / "scripts/build_integer_adapter.py"
    build = run_bounded(
        [sys.executable, str(builder), "--output", str(jar)],
        cwd=str(ROOT),
        timeout=240,
    )
    assert build.returncode == 0, build.stderr
    manifest = json.loads(build.stdout)
    assert manifest["adapter"] == "local-ee-integer-adapter"
    assert "engine/ee_pixel_math_numeric.scala" in manifest["sources"]
    assert "engine/ee_pixel_math_adapter.scala" in manifest["sources"]
    assert manifest["jar_sha256"] == sha256(jar)
    assert manifest["math_dependencies"] == {
        "commons-math3-3.6.1.jar":
            "1e56d7b058d28b65abd256b8458e3885b674c1d588fa43cd7d1cbb9c7ef2b308"
    }

    java, _, compiler_tools, runtime_jars, _ = _engine_paths()
    classpath = os.pathsep.join(map(str, [jar, *runtime_jars]))
    classes = scratch / "probe-classes"
    classes.mkdir()
    probe_source = ROOT / "tests/fixtures/ee-pixel-math-kernel-probe.scala"
    compile_result = run_bounded(
        [
            str(java),
            "-cp",
            os.pathsep.join(map(str, compiler_tools)),
            "scala.tools.nsc.Main",
            "-classpath",
            classpath,
            "-d",
            str(classes),
            str(probe_source),
        ],
        cwd=str(ROOT),
        timeout=120,
    )
    assert compile_result.returncode == 0, compile_result.stderr

    cases_path = scratch / "pixel-math-cases.json"
    cases_path.write_text(json.dumps(fixture, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    probe_result = run_bounded(
        [
            str(java),
            "-cp",
            str(classes) + os.pathsep + classpath,
            "EePixelMathKernelProbe",
            str(cases_path),
        ],
        cwd=str(ROOT),
        timeout=120,
    )
    assert probe_result.returncode == 0, probe_result.stderr
    expected = (
        f"PIXEL_MATH_KERNEL_OK operations={len(OPERATION_ARITIES)} "
        f"cases={len(fixture['cases'])} pixels={fixture['pixel_count']}"
    )
    assert expected in probe_result.stdout

    result = {
        "scope": "Trusted standalone GeoTrellis tile kernel; no SparkContext, service, or user code",
        "stdout": probe_result.stdout,
        "stderr": probe_result.stderr,
        "operation_arities": OPERATION_ARITIES,
        "case_count": len(fixture["cases"]),
        "pixel_count": fixture["pixel_count"],
        "probe_sha256": sha256(probe_source),
        "manifest": manifest,
        "local_policies": [
            "atan2 and signum signed zeros are checked exactly",
            "Commons Math Erf.erf(-0.0) returns +0.0, so erf zero-sign parity is not required",
        ],
        "limitations": [
            "Does not establish full Spark cube, native sandbox, service, browser, or Google acceptance"
        ],
    }
    result_path = scratch / "pixel-math-result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    audit_dir = os.environ.get("GEE_AUDIT_DIR")
    if audit_dir:
        target = Path(audit_dir) / f"pixel-math-kernel-{run_id}"
        target.mkdir(parents=True, exist_ok=False)
        (target / "pixel-math-cases.json").write_text(
            cases_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (target / "pixel-math-result.json").write_text(
            result_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (target / "pixel-math-adapter.manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
