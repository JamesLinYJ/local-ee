#!/usr/bin/env python3
"""Run the fractional-mask-to-sampling tile probe from a verified Wave64 audit JAR."""
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

from scripts.build_integer_adapter import SOURCES as ADAPTER_SOURCES
from ee_kernel_subprocess import run_bounded


PROBE_SOURCE = ROOT / "tests/fixtures/ee-weighted-sampling-kernel-probe.scala"
DEFAULT_FIXTURE = ROOT / "tests/fixtures/ee-weighted-sampling-wave65-v1.json"
EXPECTED_MANIFEST = ROOT / (
    "audit/gee-python-wave64/native/final-2-20261024/"
    "local-ee-mask-weights-adapter.jar.manifest.json"
)
SERVICE_NAME = "org.openeo.geotrelliscommon.CubeProcessProvider"
REQUIRED_SOURCES = {
    "engine/ee_mask_weights_spec.scala",
    "engine/ee_mask_weights_numeric.scala",
    "engine/ee_mask_weights_adapter.scala",
    "engine/ee_sample_kernel.scala",
    "engine/ee_sample_adapter.scala",
    "engine/ee_image_sample_options.scala",
    "engine/ee_image_sample_kernel.scala",
    "engine/ee_image_sample_adapter.scala",
}
MAX_FIXTURE_BYTES = 1_000_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_child(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _manifest_paths(manifest_path: Path) -> tuple[dict, Path, list[Path], list[Path], Path, Path]:
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    if manifest_path != EXPECTED_MANIFEST.resolve(strict=True):
        raise ValueError("Wave65 sampling must use the designated read-only Wave64 audit manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("format") != "local-ee-standalone-audit-v1"
            or manifest.get("adapter") != "local-ee-mask-weights-audit-adapter"
            or manifest.get("deployment_eligible") is not False):
        raise ValueError("manifest is not the non-deployment Wave64 mask-weight audit artifact")

    source_hashes = manifest.get("sources")
    expected_sources = {str(source.relative_to(ROOT)): source for source in ADAPTER_SOURCES}
    if (type(source_hashes) is not dict or set(source_hashes) != set(expected_sources)
            or not REQUIRED_SOURCES.issubset(source_hashes)):
        raise ValueError("audit manifest source set differs from the current native adapter")
    for relative, source in expected_sources.items():
        if not source.is_file() or source_hashes.get(relative) != sha256(source):
            raise ValueError(f"audit manifest does not match current native source: {relative}")

    builder = ROOT / "scripts/build_integer_adapter.py"
    helper = ROOT / "scripts/ee_adapter_build_inputs.py"
    if manifest.get("build_script_sha256") != sha256(builder):
        raise ValueError("audit manifest does not match the current native builder")
    if manifest.get("build_helpers", {}).get(
            "scripts/ee_adapter_build_inputs.py") != sha256(helper):
        raise ValueError("audit manifest does not match the current build helper")

    jar = Path(manifest.get("jar", "")).resolve(strict=True)
    audit_root = (ROOT / "audit/gee-python-wave64/native").resolve(strict=True)
    if (manifest.get("jar_sha256") != sha256(jar) or not _is_child(jar, audit_root)
            or manifest_path != Path(str(jar) + ".manifest.json")):
        raise ValueError("manifest JAR identity or digest is invalid")
    service_entry = manifest.get("services", {}).get(SERVICE_NAME, "")
    required_providers = (
        "local.ee.reduce.LocalEeMaskWeightsCubeProcessProvider",
        "local.ee.sample.LocalEeSampleCubeProcessProvider",
        "local.ee.image.sample.LocalEeImageSampleCubeProcessProvider",
    )
    if any(provider not in service_entry.splitlines() for provider in required_providers):
        raise ValueError("audit manifest omits a required mask or sampling SPI provider")

    def checked_runtime(row: object, label: str, *, jar_only: bool = False) -> Path:
        if type(row) is not dict or type(row.get("path")) is not str:
            raise ValueError(f"audit manifest has an invalid {label} record")
        path = Path(row["path"]).resolve(strict=True)
        if row.get("sha256") != sha256(path):
            raise ValueError(f"audit manifest hash mismatch for {label}: {path}")
        if jar_only:
            permitted = (
                ROOT / ".native/jars",
                ROOT / ".native/engine/lib/python3.11/site-packages/pyspark/jars",
            )
            if not any(_is_child(path, directory.resolve()) for directory in permitted):
                raise ValueError(f"{label} is outside the existing native JAR directories")
            if path.suffix != ".jar":
                raise ValueError(f"{label} is not a JAR")
        return path

    java = Path(manifest.get("java", "")).resolve(strict=True)
    jar_tool = Path(manifest.get("jar_tool", "")).resolve(strict=True)
    if (manifest.get("java_sha256") != sha256(java)
            or manifest.get("jar_tool_sha256") != sha256(jar_tool)):
        raise ValueError("audit manifest Java runtime or jar-tool hash differs")
    scala_rows = manifest.get("scala_tools")
    if type(scala_rows) is not list or len(scala_rows) != 3:
        raise ValueError("audit manifest must name Scala compiler, library and reflect JARs")
    scala_tools = [checked_runtime(row, "Scala tool JAR", jar_only=True) for row in scala_rows]
    tool_kinds = {path.name.split("-")[1] for path in scala_tools}
    if tool_kinds != {"compiler", "library", "reflect"}:
        raise ValueError("audit manifest Scala tool names are malformed")
    runtime_rows = manifest.get("runtime_jars")
    if type(runtime_rows) is not list or not runtime_rows:
        raise ValueError("audit manifest has no runtime JAR list")
    runtime_jars = [checked_runtime(row, "runtime JAR", jar_only=True) for row in runtime_rows]
    return manifest, jar, scala_tools, runtime_jars, java, jar_tool


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
                        help="read-only Wave64 audit manifest; never uses the deployment lock")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--receipt-dir", type=Path,
                        help="optional ignored directory for a unique concise audit receipt")
    args = parser.parse_args()
    summary = run_probe(args.manifest, args.fixture, args.receipt_dir)
    print(json.dumps({key: value for key, value in summary.items() if key != "native_result"},
                     ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
