#!/usr/bin/env python3
"""Run a trusted standalone GeoTrellis probe for the Float64-value kernel.

The adjacent adapter manifest is verified by the integer-values launcher. This script
compiles a temporary Scala probe and synthetic fixture only; it starts no SparkContext,
provider service, sandbox task, VM, or container.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from scripts.probe_integer_values_native import _checked_manifest, _engine_paths, sha256
from ee_float64_values_kernel_helpers import make_fixture
from ee_kernel_subprocess import run_bounded


PROBE_SOURCE_PATH = ROOT / "tests/fixtures/ee-float64-values-kernel-probe.scala"


def run_probe(manifest_path: Path) -> dict:
    manifest, jar = _checked_manifest(manifest_path)
    fixture = make_fixture()
    java, _, compiler_tools, runtime_jars, _ = _engine_paths()
    with tempfile.TemporaryDirectory(prefix="local-ee-float64-values-") as directory:
        scratch = Path(directory)
        source_path = scratch / "EeFloat64ValuesKernelProbe.scala"
        cases_path = scratch / "float64-values-cases.json"
        classes = scratch / "classes"
        classes.mkdir()
        source_path.write_bytes(PROBE_SOURCE_PATH.read_bytes())
        cases_path.write_text(json.dumps(fixture, indent=2, allow_nan=False) + "\n",
                              encoding="utf-8")
        classpath = os.pathsep.join(map(str, [jar, *runtime_jars]))
        compiler_classpath = os.pathsep.join(map(str, compiler_tools))
        compile_result = run_bounded(
            [str(java), "-cp", compiler_classpath, "scala.tools.nsc.Main",
             "-classpath", classpath, "-d", str(classes), str(source_path)],
            cwd=str(ROOT), timeout=150,
        )
        if compile_result.returncode != 0:
            raise RuntimeError(f"Scala Float64 probe compile failed: {compile_result.stderr}")
        started = time.monotonic()
        result = run_bounded(
            [str(java), "-cp", str(classes) + os.pathsep + classpath,
             "local.ee.reduce.EeFloat64ValuesKernelProbe", str(cases_path)],
            cwd=str(ROOT), timeout=120,
        )
        elapsed = time.monotonic() - started
        if result.returncode != 0:
            raise RuntimeError(f"native Float64 probe failed: {result.stderr or result.stdout}")
        line = next((item for item in result.stdout.splitlines()
                     if item.startswith("FLOAT64_VALUES_KERNEL_OK ")), "")
        if not line:
            raise RuntimeError(f"native probe emitted no success marker: {result.stdout}")
        metrics = dict(token.split("=", 1) for token in line.split()[1:])
        tolerances = {
            operation: max(row["tolerance_ulps"] for row in fixture["cases"]
                           if json.loads(row["spec"])["op"] == operation)
            for operation in fixture["operations"]
        }
        return {
            "scope": "Actual GeoTrellis tiles through direct and historical-dispatcher "
                     "Float64 kernels; no SparkContext, provider service, user data, VM, or container",
            "fixture_schema": fixture["schema"],
            "case_count": fixture["case_count"],
            "pixel_count": fixture["pixel_count"],
            "operation_count": len(fixture["operations"]),
            "max_observed_ulps": int(metrics["max_observed_ulps"]),
            "tolerance_ulps_by_operation": tolerances,
            "invalid_spec_count": len(fixture["invalid_specs"]),
            "invalid_tile_count": len(fixture["invalid_tile_cases"]),
            "composite_stage_count": 6,
            "composite_pixel_count": 44,
            "fixture_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
            "probe_source_sha256": sha256(PROBE_SOURCE_PATH),
            "elapsed_seconds": round(elapsed, 3),
            "manifest_path": str(manifest_path.expanduser().resolve()),
            "manifest_jar_sha256": manifest["jar_sha256"],
            "summary": line,
            "stdout": result.stdout,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path,
                        help="path to the current build_integer_adapter.py JSON manifest")
    args = parser.parse_args()
    print(json.dumps(run_probe(args.manifest), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
