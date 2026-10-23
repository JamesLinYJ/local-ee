#!/usr/bin/env python3
"""Run the trusted standalone GeoTrellis integer-values probe from a built manifest.

This launcher accepts the manifest emitted beside the registered native adapter JAR.
It compiles only a temporary probe class, creates only synthetic tiles, and never starts
SparkContext, a service, a sandbox task, a VM, or a container.
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

from scripts.build_integer_adapter import SOURCES as ADAPTER_SOURCES, _engine_paths
from ee_integer_values_kernel_helpers import make_fixture
from ee_kernel_subprocess import run_bounded


NATIVE_SOURCES = (
    "engine/ee_cell_conversion.scala",
    "engine/ee_reduce_support.scala",
    "engine/ee_integer_values_spec.scala",
    "engine/ee_integer_values_numeric.scala",
    "engine/ee_integer_values_adapter.scala",
)
SERVICE_NAME = "org.openeo.geotrelliscommon.CubeProcessProvider"
PROVIDER = "local.ee.reduce.LocalEeIntegerValuesCubeProcessProvider"


PROBE_SOURCE_PATH = ROOT / "tests/fixtures/ee-integer-values-kernel-probe.scala"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checked_manifest(path: Path) -> tuple[dict, Path]:
    manifest_path = path.expanduser().resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("adapter") != "local-ee-integer-adapter":
        raise ValueError("manifest is not for the local integer adapter")
    sources = manifest.get("sources")
    if not isinstance(sources, dict):
        raise ValueError("adapter manifest has no source digest map")
    expected_sources = {str(source.relative_to(ROOT)): source for source in ADAPTER_SOURCES}
    if len(expected_sources) != len(ADAPTER_SOURCES):
        raise ValueError("current adapter build source list contains duplicate paths")
    if set(sources) != set(expected_sources):
        missing = sorted(set(expected_sources) - set(sources))
        extra = sorted(set(sources) - set(expected_sources))
        raise ValueError(f"adapter manifest source set differs from current build sources: "
                         f"missing={missing}, extra={extra}")
    if not set(NATIVE_SOURCES).issubset(expected_sources):
        raise ValueError("current adapter build source list omits a required integer kernel source")
    for relative, source in expected_sources.items():
        if not source.is_file() or sources.get(relative) != sha256(source):
            raise ValueError(f"adapter manifest does not match current native source: {relative}")
    builder = ROOT / "scripts/build_integer_adapter.py"
    if manifest.get("build_script_sha256") != sha256(builder):
        raise ValueError("adapter manifest does not match the current build script")
    services = manifest.get("services", {}).get(SERVICE_NAME, "")
    if PROVIDER not in services.splitlines():
        raise ValueError("adapter manifest does not register the integer-values SPI provider")
    jar = Path(manifest.get("jar", "")).expanduser().resolve(strict=True)
    if manifest.get("jar_sha256") != sha256(jar):
        raise ValueError("adapter JAR does not match the manifest SHA-256")
    return manifest, jar


def run_probe(manifest_path: Path) -> dict:
    manifest, jar = _checked_manifest(manifest_path)
    fixture = make_fixture()
    java, _, compiler_tools, runtime_jars, _ = _engine_paths()
    with tempfile.TemporaryDirectory(prefix="local-ee-integer-values-") as directory:
        scratch = Path(directory)
        source_path = scratch / "EeIntegerValuesKernelProbe.scala"
        cases_path = scratch / "integer-values-cases.json"
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
            raise RuntimeError(f"Scala probe compile failed: {compile_result.stderr}")
        started = time.monotonic()
        result = run_bounded(
            [str(java), "-cp", str(classes) + os.pathsep + classpath,
             "local.ee.reduce.EeIntegerValuesKernelProbe", str(cases_path)],
            cwd=str(ROOT), timeout=120,
        )
        elapsed = time.monotonic() - started
        if result.returncode != 0:
            raise RuntimeError(f"native probe failed: {result.stderr or result.stdout}")
        line = next((item for item in result.stdout.splitlines()
                     if item.startswith("INTEGER_VALUES_KERNEL_OK ")), "")
        if not line:
            raise RuntimeError(f"native probe emitted no success marker: {result.stdout}")
        return {
            "scope": "Actual GeoTrellis tiles through LocalEeIntegerValuesNumeric.applyTile; "
                     "no SparkContext, service, sandbox task, VM, container, or user data",
            "fixture_schema": fixture["schema"],
            "case_count": fixture["case_count"],
            "pixel_count": fixture["pixel_count"],
            "invalid_spec_count": len(fixture["invalid_specs"]),
            "invalid_tile_count": len(fixture["invalid_tile_cases"]),
            "masked_constant_case_count": len(fixture["masked_constant_cases"]),
            "qa_composite_steps": len(fixture["qa_composite"]["steps"]),
            "qa_composite_pixels": len(fixture["qa_composite"]["raw_scl"]),
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
                        help="path to the new build_integer_adapter.py JSON manifest")
    args = parser.parse_args()
    print(json.dumps(run_probe(args.manifest), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
