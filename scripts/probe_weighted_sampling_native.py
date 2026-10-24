#!/usr/bin/env python3
"""Run the fractional-mask-to-sampling tile probe from a verified current audit JAR."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from scripts.ee_audit_native_manifest import validate_native_manifest
from ee_kernel_subprocess import run_bounded


PROBE_SOURCE = ROOT / "tests/fixtures/ee-weighted-sampling-kernel-probe.scala"
DEFAULT_FIXTURE = ROOT / "tests/fixtures/ee-weighted-sampling-wave65-v1.json"
EXPECTED_MANIFEST = ROOT / (
    "audit/gee-python-wave66/native/final-1-20261024/"
    "local-ee-mask-math-adapter.jar.manifest.json"
)
SERVICE_NAME = "org.openeo.geotrelliscommon.CubeProcessProvider"
MAX_FIXTURE_BYTES = 1_000_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_paths(manifest_path: Path) -> tuple[dict, Path, list[Path], list[Path], Path, Path]:
    if manifest_path.expanduser().resolve(strict=True) != EXPECTED_MANIFEST.resolve(strict=True):
        raise ValueError("Weighted sampling must use the designated current audit manifest")
    checked = validate_native_manifest(
        manifest_path, expected_adapter="local-ee-mask-weights-audit-adapter",
    )
    manifest = checked["manifest"]
    providers = manifest.get("services", {}).get(SERVICE_NAME, "").splitlines()
    for name in ("local.ee.sample.LocalEeSampleCubeProcessProvider",
                 "local.ee.image.sample.LocalEeImageSampleCubeProcessProvider"):
        if name not in providers:
            raise ValueError("audit manifest omits a required sampling SPI provider")
    return (manifest, checked["jar"], checked["scala_tools"], checked["runtime_jars"],
            checked["java"], checked["jar_tool"])


def run_probe(manifest_path: Path = EXPECTED_MANIFEST, fixture_path: Path = DEFAULT_FIXTURE,
              receipt_dir: Path | None = None) -> dict:
    manifest, jar, scala_tools, runtime_jars, java, jar_tool = _manifest_paths(manifest_path)
    fixture_path = fixture_path.expanduser().resolve(strict=True)
    raw_fixture = fixture_path.read_bytes()
    if len(raw_fixture) > MAX_FIXTURE_BYTES:
        raise ValueError(f"weighted sampling fixture exceeds {MAX_FIXTURE_BYTES} bytes")
    fixture = json.loads(raw_fixture)
    if (type(fixture) is not dict
            or fixture.get("schema") != "local-ee-weighted-sampling-wave65/v1"
            or type(fixture.get("tiles")) is not list
            or type(fixture.get("image_sample_cases")) is not list):
        raise ValueError("fixture does not satisfy local-ee-weighted-sampling-wave65/v1")
    if not PROBE_SOURCE.is_file():
        raise FileNotFoundError(PROBE_SOURCE)
    raw_probe = PROBE_SOURCE.read_bytes()

    compiler_cp = os.pathsep.join(map(str, scala_tools))
    classpath = os.pathsep.join(map(str, [jar, *runtime_jars]))
    with tempfile.TemporaryDirectory(prefix="local-ee-weighted-sampling-") as directory:
        scratch = Path(directory)
        source_path = scratch / "WeightedSamplingKernelProbe.scala"
        cases_path = scratch / "weighted-sampling-cases.json"
        classes = scratch / "classes"
        classes.mkdir()
        source_path.write_bytes(raw_probe)
        cases_path.write_bytes(raw_fixture)
        compile_result = run_bounded(
            [str(java), "-cp", compiler_cp, "scala.tools.nsc.Main",
             "-classpath", classpath, "-d", str(classes), str(source_path)],
            cwd=str(ROOT), timeout=150,
        )
        if compile_result.returncode != 0:
            raise RuntimeError(
                f"weighted sampling Scala probe compile failed: {compile_result.stderr}")
        started = time.monotonic()
        result = run_bounded(
            [str(java), "-cp", str(classes) + os.pathsep + classpath,
             "local.ee.reduce.WeightedSamplingKernelProbe", str(cases_path)],
            cwd=str(ROOT), timeout=120,
        )
        elapsed = time.monotonic() - started
        if result.returncode != 0:
            raise RuntimeError(
                f"weighted sampling native probe failed: {result.stderr or result.stdout}")
        marker = "WEIGHTED_SAMPLING_NATIVE_RESULT "
        line = next((line for line in result.stdout.splitlines() if line.startswith(marker)), None)
        if line is None:
            raise RuntimeError(f"native probe emitted no result marker: {result.stdout}")
        native = json.loads(line[len(marker):])
        if native.get("fixture_schema") != fixture["schema"]:
            raise RuntimeError("native probe returned a different fixture identity")

    summary = {
        "fixture_schema": fixture["schema"],
        "fixture_sha256": hashlib.sha256(raw_fixture).hexdigest(),
        "probe_source_sha256": hashlib.sha256(raw_probe).hexdigest(),
        "manifest_path": str(Path(manifest_path).resolve()),
        "manifest_sha256": sha256(Path(manifest_path).resolve()),
        "manifest_format": manifest["format"],
        "deployment_eligible": manifest["deployment_eligible"],
        "jar_path": str(jar),
        "jar_sha256": manifest["jar_sha256"],
        "source_count": len(manifest["sources"]),
        "runtime_jar_count": len(runtime_jars),
        "java_path": str(java),
        "jar_tool_path": str(jar_tool),
        "elapsed_seconds": round(elapsed, 3),
        "image_sample_row_counts": {
            row["name"]: len(row["rows"]) for row in native["image_sample_cases"]
        },
        "sample_regions_row_count": len(native["sample_regions_rows"]),
        "loaded_spi_ids": native["loaded_spi_ids"],
        "execution_scope": (
            "Actual GeoTrellis Float32/Float64 tiles through LocalEeMaskWeightsNumeric.applyTile, "
            "then existing Image.sample and sampleRegions numeric tile kernels. No SparkContext, "
            "engine service, sandbox batch task, VM, container, private raster, or Google request."
        ),
    }
    summary["native_result"] = native
    if receipt_dir is not None:
        receipt_dir = receipt_dir.expanduser().resolve()
        receipt_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        receipt = receipt_dir / f"native-{stamp}-{os.getpid()}-{uuid.uuid4().hex[:12]}.json"
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        descriptor = os.open(receipt, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({key: value for key, value in summary.items() if key != "native_result"},
                      stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        summary["receipt_path"] = str(receipt)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=EXPECTED_MANIFEST,
                        help="read-only current audit manifest; never uses the deployment lock")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--receipt-dir", type=Path,
                        help="optional ignored directory for a unique concise audit receipt")
    args = parser.parse_args()
    summary = run_probe(args.manifest, args.fixture, args.receipt_dir)
    print(json.dumps({key: value for key, value in summary.items() if key != "native_result"},
                     ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
