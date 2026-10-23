"""Opt-in actual GeoTrellis Float64 statistic tile probe; no SparkContext."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

import pytest

from ee_kernel_subprocess import run_bounded
from ee_reduce_statistics_kernel_helpers import assert_reference_anchors, make_fixture
from scripts.build_integer_adapter import ROOT, _engine_paths, sha256


pytestmark = pytest.mark.skipif(
    os.environ.get("LOCAL_EE_RUN_REDUCE_STATISTICS_KERNEL_TEST") != "1",
    reason="opt-in trusted GeoTrellis Float64 reducer tile kernel; no Spark, service, or user-code acceptance",
)


def test_actual_float64_tiles_match_independent_statistics_references():
    fixture = make_fixture()
    assert_reference_anchors(fixture)
    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:10]}"
    audit = ROOT / "audit/gee-python-wave40/native-statistics" / run_id
    audit.mkdir(parents=True, exist_ok=False)
    scratch = ROOT.parent.parent / "work/gee-python-wave40-owned-unique" / run_id
    scratch.mkdir(parents=True, exist_ok=False)
    fixture_path = scratch / "reduce-statistics-cases.json"
    result_path = audit / "reduce-statistics-result.json"
    report = {
        "scope": "Trusted standalone GeoTrellis Float64 tile kernel; no SparkContext, service, or user code",
        "run_id": run_id,
        "status": "running",
        "fixture": fixture,
        "limitations": [
            "Does not establish full Spark cube, native sandbox, service, browser, or Google acceptance"
        ],
    }
    compile_result = None
    probe_result = None
    try:
        fixture_path.write_text(json.dumps(fixture, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        java, _, compiler_tools, runtime_jars, locked_jars = _engine_paths()
        classpath = os.pathsep.join(map(str, runtime_jars))
        compiler_classpath = os.pathsep.join(map(str, compiler_tools))
        classes = scratch / "probe-classes"
        classes.mkdir()
        numeric_source = ROOT / "engine/ee_reduce_numeric.scala"
        statistics_source = ROOT / "engine/ee_reduce_statistics.scala"
        probe_source = ROOT / "tests/fixtures/ee-reduce-statistics-probe.scala"
        compile_result = run_bounded(
            [
                str(java), "-cp", compiler_classpath, "scala.tools.nsc.Main",
                "-classpath", classpath, "-d", str(classes),
                str(statistics_source), str(numeric_source), str(probe_source),
            ],
            cwd=str(ROOT),
            timeout=180,
        )
        assert compile_result.returncode == 0, compile_result.stderr

        probe_result = run_bounded(
            [
                str(java), "-cp", str(classes) + os.pathsep + classpath,
                "local.ee.reduce.EeReduceStatisticsKernelProbe", str(fixture_path),
            ],
            cwd=str(ROOT),
            timeout=120,
        )
        assert probe_result.returncode == 0, probe_result.stderr
        expected = (
            "EE_REDUCE_STATISTICS_KERNEL_OK reducers=7 cases=7 pixels=41 "
            "rejects=8 Float64=true noData=NaN"
        )
        assert expected in probe_result.stdout
        owned_sources = [
            ROOT / "engine/ee_reduce_numeric.scala",
            ROOT / "engine/ee_reduce_adapter.scala",
            ROOT / "engine/ee_reduce_statistics.scala",
            ROOT / "tests/test_ee_reduce_statistics_kernel.py",
            ROOT / "tests/ee_reduce_statistics_kernel_helpers.py",
            ROOT / "tests/fixtures/ee-reduce-statistics-probe.scala",
        ]
        report.update({
            "status": "passed",
            "stdout": probe_result.stdout,
            "stderr": probe_result.stderr,
            "compile_stdout": compile_result.stdout,
            "compile_stderr": compile_result.stderr,
            "fixture_sha256": sha256(fixture_path),
            "probe_sha256": sha256(probe_source),
            "numeric_sha256": sha256(numeric_source),
            "statistics_sha256": sha256(statistics_source),
            "owned_source_sha256": {
                str(path.relative_to(ROOT)): sha256(path) for path in owned_sources
            },
            "java": str(java),
            "scala_compiler_jars": [path.name for path in compiler_tools],
            "runtime_jar_count": len(runtime_jars),
            "engine_lock_sha256": sha256(ROOT / ".native/engine-lock.json"),
            "upstream_jars_verified_against_lock": locked_jars,
        })
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        if compile_result is not None:
            report["compile_stdout"] = compile_result.stdout
            report["compile_stderr"] = compile_result.stderr
        if probe_result is not None:
            report["stdout"] = probe_result.stdout
            report["stderr"] = probe_result.stderr
        raise
    finally:
        if fixture_path.is_file():
            shutil.copy2(fixture_path, audit / "reduce-statistics-cases.json")
            report["fixture_sha256"] = sha256(fixture_path)
        result_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        if scratch.exists():
            shutil.rmtree(scratch)
