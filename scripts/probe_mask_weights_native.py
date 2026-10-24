#!/usr/bin/env python3
"""Run the direct GeoTrellis mask-weight probe from an audit-only manifest."""
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

from scripts.build_integer_adapter import SOURCES as ADAPTER_SOURCES
from ee_kernel_subprocess import run_bounded


PROBE_SOURCE = ROOT / "tests/fixtures/ee-mask-weights-kernel-probe.scala"
DEFAULT_FIXTURE = ROOT / "tests/fixtures/ee-mask-weights-wave64-v1.json"
SERVICE_NAME = "org.openeo.geotrelliscommon.CubeProcessProvider"
PROVIDER = "local.ee.reduce.LocalEeMaskWeightsCubeProcessProvider"
REQUIRED_SOURCES = {
    "engine/ee_mask_weights_spec.scala",
    "engine/ee_mask_weights_numeric.scala",
    "engine/ee_mask_weights_adapter.scala",
}
MAX_FIXTURE_BYTES = 1_000_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_paths(manifest: dict, manifest_path: Path) -> tuple[Path, Path, list[Path], list[Path]]:
    if (manifest.get("format") != "local-ee-standalone-audit-v1"
            or manifest.get("adapter") != "local-ee-mask-weights-audit-adapter"
            or manifest.get("deployment_eligible") is not False):
        raise ValueError("manifest is not the non-deployment mask-weight audit artifact")
    source_hashes = manifest.get("sources")
    if type(source_hashes) is not dict:
        raise ValueError("audit manifest has no native source hash map")
    expected_sources = {
        str(source.relative_to(ROOT)): source for source in ADAPTER_SOURCES
    }
    if len(expected_sources) != len(ADAPTER_SOURCES):
        raise ValueError("adapter builder source list contains duplicate entries")
    if set(source_hashes) != set(expected_sources):
        raise ValueError("audit manifest source set differs from the current builder")
    if not REQUIRED_SOURCES.issubset(source_hashes):
        raise ValueError("audit manifest omits a mask-weight native source")
    for relative, source in expected_sources.items():
        if not source.is_file() or source_hashes.get(relative) != sha256(source):
            raise ValueError(f"audit manifest does not match current native source: {relative}")

    builder = ROOT / "scripts/build_integer_adapter.py"
    if manifest.get("build_script_sha256") != sha256(builder):
        raise ValueError("audit manifest does not match the current native builder")
    helper = ROOT / "scripts/ee_adapter_build_inputs.py"
    if manifest.get("build_helpers", {}).get(
            "scripts/ee_adapter_build_inputs.py") != sha256(helper):
        raise ValueError("audit manifest does not match the standalone build helper")

    jar = Path(manifest.get("jar", "")).expanduser().resolve(strict=True)
    if manifest.get("jar_sha256") != sha256(jar):
        raise ValueError("audit JAR does not match its SHA-256 receipt")
    audit_root = (ROOT / "audit/gee-python-wave64/native").resolve()
    if not _is_child(jar, audit_root):
        raise ValueError("audit JAR must stay in the ignored wave64 audit directory")
    if manifest_path != Path(str(jar) + ".manifest.json"):
        raise ValueError("manifest is not adjacent to its declared audit JAR")

    service_entry = manifest.get("services", {}).get(SERVICE_NAME, "")
    if PROVIDER not in service_entry.splitlines():
        raise ValueError("audit manifest does not register the mask-weight provider")

    native_jars = (ROOT / ".native/jars").resolve()
    spark_jars = (
        ROOT / ".native/engine/lib/python3.11/site-packages/pyspark/jars"
    ).resolve()

    def checked_file(row, label, *, jar_only=False):
        if type(row) is not dict or type(row.get("path")) is not str:
            raise ValueError(f"audit manifest has an invalid {label} record")
        path = Path(row["path"]).expanduser().resolve(strict=True)
        if row.get("sha256") != sha256(path):
            raise ValueError(f"audit manifest hash mismatch for {label}: {path}")
        if jar_only and not any(
                _is_child(path, directory) for directory in (native_jars, spark_jars)):
            raise ValueError(f"{label} is outside the existing native JAR directories")
        return path

    java = Path(manifest.get("java", "")).expanduser().resolve(strict=True)
    if manifest.get("java_sha256") != sha256(java):
        raise ValueError("audit manifest Java runtime hash mismatch")
    jar_tool = Path(manifest.get("jar_tool", "")).expanduser().resolve(strict=True)
    if manifest.get("jar_tool_sha256") != sha256(jar_tool):
        raise ValueError("audit manifest jar tool hash mismatch")

    scala_rows = manifest.get("scala_tools")
    if type(scala_rows) is not list or len(scala_rows) != 3:
        raise ValueError("audit manifest must name Scala compiler/library/reflect JARs")
    scala_tools = [checked_file(row, "Scala tool JAR", jar_only=True) for row in scala_rows]
    if {path.name.split("-")[1] for path in scala_tools} != {
            "compiler", "library", "reflect"}:
        raise ValueError("audit manifest Scala tool names are malformed")

    runtime_rows = manifest.get("runtime_jars")
    if type(runtime_rows) is not list or not runtime_rows:
        raise ValueError("audit manifest has no runtime JAR list")
    runtime_jars = [checked_file(row, "runtime JAR", jar_only=True) for row in runtime_rows]
    if any(path.suffix != ".jar" for path in runtime_jars):
        raise ValueError("audit manifest runtime classpath contains a non-JAR file")
    return java, jar, scala_tools, runtime_jars


def _is_child(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def run_probe(manifest_path: Path, fixture_path: Path = DEFAULT_FIXTURE) -> dict:
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    java, jar, scala_tools, runtime_jars = _manifest_paths(manifest, manifest_path)

    raw_fixture = fixture_path.expanduser().resolve(strict=True).read_bytes()
    if len(raw_fixture) > MAX_FIXTURE_BYTES:
        raise ValueError(f"mask-weight fixture exceeds {MAX_FIXTURE_BYTES} bytes")
    fixture = json.loads(raw_fixture)
    if (type(fixture) is not dict
            or fixture.get("schema") != "local-ee-mask-weights-wave64/v1"
            or type(fixture.get("cases")) is not list
            or type(fixture.get("invalid_specs")) is not list
            or type(fixture.get("invalid_tile_cases")) is not list):
        raise ValueError("fixture does not satisfy local-ee-mask-weights-wave64/v1")
    if not PROBE_SOURCE.is_file():
        raise FileNotFoundError(PROBE_SOURCE)

    compiler_cp = os.pathsep.join(map(str, scala_tools))
    classpath = os.pathsep.join(map(str, [jar, *runtime_jars]))
    with tempfile.TemporaryDirectory(prefix="local-ee-mask-weights-probe-") as directory:
        scratch = Path(directory)
        source_path = scratch / "EeMaskWeightsKernelProbe.scala"
        cases_path = scratch / "mask-weight-cases.json"
        classes = scratch / "classes"
        classes.mkdir()
        source_path.write_bytes(PROBE_SOURCE.read_bytes())
        cases_path.write_bytes(raw_fixture)
        compile_result = run_bounded(
            [str(java), "-cp", compiler_cp, "scala.tools.nsc.Main",
             "-classpath", classpath, "-d", str(classes), str(source_path)],
            cwd=str(ROOT), timeout=150,
        )
        if compile_result.returncode != 0:
            raise RuntimeError(f"Scala mask-weight probe compile failed: {compile_result.stderr}")

        started = time.monotonic()
        result = run_bounded(
            [str(java), "-cp", str(classes) + os.pathsep + classpath,
             "local.ee.reduce.EeMaskWeightsKernelProbe", str(cases_path)],
            cwd=str(ROOT), timeout=120,
        )
        elapsed = time.monotonic() - started
        if result.returncode != 0:
            raise RuntimeError(f"mask-weight native probe failed: {result.stderr or result.stdout}")
        summary = next((line for line in result.stdout.splitlines()
                        if line.startswith("MASK_WEIGHTS_KERNEL_OK ")), "")
        expected_summary = (
            f"MASK_WEIGHTS_KERNEL_OK cases={len(fixture['cases'])} "
            f"pixels={fixture['pixel_count']} invalid_specs={len(fixture['invalid_specs'])} "
            f"invalid_tiles={len(fixture['invalid_tile_cases'])} "
            f"composite_updates={len(fixture['composite']['new_masks'])}"
        )
        if summary != expected_summary:
            raise RuntimeError(f"native probe emitted no success marker: {result.stdout}")

    return {
        "fixture_schema": fixture["schema"],
        "case_count": len(fixture["cases"]),
        "pixel_count": fixture["pixel_count"],
        "invalid_spec_count": len(fixture["invalid_specs"]),
        "invalid_tile_count": len(fixture["invalid_tile_cases"]),
        "composite_update_count": len(fixture["composite"]["new_masks"]),
        "fixture_sha256": hashlib.sha256(raw_fixture).hexdigest(),
        "probe_source_sha256": sha256(PROBE_SOURCE),
        "elapsed_seconds": round(elapsed, 3),
        "manifest_path": str(manifest_path),
        "manifest_format": manifest["format"],
        "deployment_eligible": manifest["deployment_eligible"],
        "manifest_jar_sha256": manifest["jar_sha256"],
        "summary": summary,
        "scope": "Actual GeoTrellis DoubleArrayTile inputs through "
                 "LocalEeMaskWeightsNumeric.applyTile; no SparkContext, service, "
                 "sandbox task, VM, container, or private raster data.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path,
                        help="path to the audit-only standalone adapter manifest")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE,
                        help="mask-weight fixture JSON; defaults to the checked wave64 fixture")
    args = parser.parse_args()
    print(json.dumps(run_probe(args.manifest, args.fixture), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
