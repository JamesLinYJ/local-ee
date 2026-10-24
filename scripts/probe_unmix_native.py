#!/usr/bin/env python3
"""Run the trusted bounded GeoTrellis Image.unmix tile probe from a manifest."""
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
from ee_kernel_subprocess import run_bounded


NATIVE_SOURCES = (
    "engine/ee_cell_conversion.scala",
    "engine/ee_reduce_support.scala",
    "engine/ee_unmix_spec.scala",
    "engine/ee_unmix_rank.scala",
    "engine/ee_unmix_solver.scala",
    "engine/ee_unmix_numeric.scala",
    "engine/ee_unmix_budget.scala",
    "engine/ee_unmix_adapter.scala",
)
SERVICE_NAME = "org.openeo.geotrelliscommon.CubeProcessProvider"
PROVIDER = "local.ee.reduce.LocalEeSpectralUnmixCubeProcessProvider"
PROBE_SOURCE = ROOT / "tests/fixtures/ee-spectral-unmix-kernel-probe.scala"
MAX_FIXTURE_BYTES = 1_000_000


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
        raise ValueError("manifest is not for the local native adapter")
    sources = manifest.get("sources")
    if not isinstance(sources, dict):
        raise ValueError("adapter manifest has no source digest map")
    expected = {str(source.relative_to(ROOT)): source for source in ADAPTER_SOURCES}
    if len(expected) != len(ADAPTER_SOURCES):
        raise ValueError("current adapter build source list contains duplicate paths")
    if set(sources) != set(expected):
        missing = sorted(set(expected) - set(sources))
        extra = sorted(set(sources) - set(expected))
        raise ValueError(f"adapter manifest source set differs from current build sources: "
                         f"missing={missing}, extra={extra}")
    if not set(NATIVE_SOURCES).issubset(expected):
        raise ValueError("current adapter build source list omits a required unmix source")
    for relative, source in expected.items():
        if not source.is_file() or sources.get(relative) != sha256(source):
            raise ValueError(f"adapter manifest does not match current native source: {relative}")
    builder = ROOT / "scripts/build_integer_adapter.py"
    if manifest.get("build_script_sha256") != sha256(builder):
        raise ValueError("adapter manifest does not match the current build script")
    service_entry = manifest.get("services", {}).get(SERVICE_NAME, "")
    if PROVIDER not in service_entry.splitlines():
        raise ValueError("adapter manifest does not register the spectral-unmix provider")
    jar = Path(manifest.get("jar", "")).expanduser().resolve(strict=True)
    if manifest.get("jar_sha256") != sha256(jar):
        raise ValueError("adapter JAR does not match the manifest SHA-256")
    return manifest, jar


def _fixture_payload(path: Path) -> tuple[dict, str]:
    fixture_path = path.expanduser().resolve(strict=True)
    raw = fixture_path.read_bytes()
    if len(raw) > MAX_FIXTURE_BYTES:
        raise ValueError(f"spectral-unmix fixture exceeds {MAX_FIXTURE_BYTES} bytes")
    document = json.loads(raw)
    payload = document.get("native_probe", document) if type(document) is dict else None
    if (type(payload) is not dict
            or payload.get("schema") != "local-ee-spectral-unmix-native/v1"
            or type(payload.get("cases")) is not list or not payload["cases"]
            or type(payload.get("invalid_specs", [])) is not list
            or type(payload.get("reject_inputs", [])) is not list):
        raise ValueError("fixture lacks a valid local-ee-spectral-unmix-native/v1 payload")
    return payload, hashlib.sha256(raw).hexdigest()


def run_probe(manifest_path: Path, fixture_path: Path) -> dict:
    manifest, jar = _checked_manifest(manifest_path)
    fixture, fixture_digest = _fixture_payload(fixture_path)
    java, _, compiler_tools, runtime_jars, _ = _engine_paths()
    with tempfile.TemporaryDirectory(prefix="local-ee-unmix-native-") as directory:
        scratch = Path(directory)
        source_path = scratch / "EeSpectralUnmixKernelProbe.scala"
        cases_path = scratch / "spectral-unmix-cases.json"
        classes = scratch / "classes"
        classes.mkdir()
        source_path.write_bytes(PROBE_SOURCE.read_bytes())
        cases_path.write_text(json.dumps(fixture, separators=(",", ":"), allow_nan=False) + "\n",
                              encoding="utf-8")
        classpath = os.pathsep.join(map(str, [jar, *runtime_jars]))
        compiler_classpath = os.pathsep.join(map(str, compiler_tools))
        compiled = run_bounded(
            [str(java), "-cp", compiler_classpath, "scala.tools.nsc.Main",
             "-classpath", classpath, "-d", str(classes), str(source_path)],
            cwd=str(ROOT), timeout=150,
        )
        if compiled.returncode != 0:
            raise RuntimeError(f"Scala probe compile failed: {compiled.stderr}")
        started = time.monotonic()
        result = run_bounded(
            [str(java), "-cp", str(classes) + os.pathsep + classpath,
             "local.ee.reduce.EeSpectralUnmixKernelProbe", str(cases_path)],
            cwd=str(ROOT), timeout=120,
        )
        elapsed = time.monotonic() - started
        if result.returncode != 0:
            raise RuntimeError(f"native probe failed: {result.stderr or result.stdout}")
        line = next((item for item in result.stdout.splitlines()
                     if item.startswith("SPECTRAL_UNMIX_RESULT ")), "")
        if not line:
            raise RuntimeError(f"native probe emitted no result marker: {result.stdout}")
        observed = json.loads(line.removeprefix("SPECTRAL_UNMIX_RESULT "))
        output_bytes = json.dumps(observed["cases"], sort_keys=True, separators=(",", ":"),
                                  allow_nan=False).encode("utf-8")
        return {
            "schema": observed["schema"],
            "fixture_schema": fixture["schema"],
            "case_count": observed["case_count"],
            "output_cells": sum(row["output_cells"] for row in observed["cases"]),
            "invalid_spec_count": observed["invalid_spec_count"],
            "rejected_input_count": observed["rejected_input_count"],
            "fixture_sha256": fixture_digest,
            "actual_outputs_sha256": hashlib.sha256(output_bytes).hexdigest(),
            "probe_source_sha256": sha256(PROBE_SOURCE),
            "elapsed_seconds": round(elapsed, 3),
            "manifest_path": str(manifest_path.expanduser().resolve()),
            "manifest_jar_sha256": manifest["jar_sha256"],
            "summary": observed["summary"],
            "actual_outputs": observed["cases"],
            "scope": "Actual GeoTrellis DoubleArrayTile inputs through the production numeric kernel; "
                     "no SparkContext, service, SPI loading, user code, VM, container, or private raster data.",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path,
                        help="path to the current native adapter JSON manifest")
    parser.add_argument("--fixture", required=True, type=Path,
                        help="workflow fixture or a native_probe fixture JSON")
    args = parser.parse_args()
    print(json.dumps(run_probe(args.manifest, args.fixture), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
