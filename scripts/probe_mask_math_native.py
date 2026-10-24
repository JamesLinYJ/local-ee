#!/usr/bin/env python3
"""Probe Wave66 math and fractional-mask tile kernels from the verified audit JAR."""
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

from ee_kernel_subprocess import run_bounded
from scripts.ee_audit_native_manifest import CURRENT_ADAPTER_MANIFEST, validate_native_manifest


EXPECTED_MANIFEST = CURRENT_ADAPTER_MANIFEST
DEFAULT_FIXTURE = ROOT / "tests/fixtures/ee-mask-math-wave66-v1.json"
PROBE_SOURCE = ROOT / "tests/fixtures/ee-mask-math-kernel-probe.scala"
EXPECTED_ADAPTER = "local-ee-mask-weights-audit-adapter"
MAX_FIXTURE_BYTES = 1_000_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_probe(manifest_path: Path = EXPECTED_MANIFEST,
              fixture_path: Path = DEFAULT_FIXTURE,
              receipt_dir: Path | None = None) -> dict:
    """Compile the temporary probe against a current, strictly verified audit artifact."""
    checked = validate_native_manifest(
        manifest_path, expected_adapter=EXPECTED_ADAPTER,
    )
    manifest = checked["manifest"]
    jar = checked["jar"]
    scala_tools = checked["scala_tools"]
    runtime_jars = checked["runtime_jars"]
    java = checked["java"]
    fixture_path = Path(fixture_path).expanduser().resolve(strict=True)
    fixture_bytes = fixture_path.read_bytes()
    if len(fixture_bytes) > MAX_FIXTURE_BYTES:
        raise ValueError(f"mask math fixture exceeds {MAX_FIXTURE_BYTES} bytes")
    fixture = json.loads(fixture_bytes)
    if (type(fixture) is not dict
            or fixture.get("schema") != "local-ee-mask-math-wave66/v1"
            or type(fixture.get("tiles")) is not list):
        raise ValueError("fixture does not satisfy local-ee-mask-math-wave66/v1")
    if not PROBE_SOURCE.is_file():
        raise FileNotFoundError(PROBE_SOURCE)
    probe_bytes = PROBE_SOURCE.read_bytes()
    compiler_cp = os.pathsep.join(map(str, scala_tools))
    classpath = os.pathsep.join(map(str, [jar, *runtime_jars]))

    with tempfile.TemporaryDirectory(prefix="local-ee-mask-math-") as directory:
        scratch = Path(directory)
        source_path = scratch / "MaskMathKernelProbe.scala"
        fixture_copy = scratch / "fixture.json"
        classes = scratch / "classes"
        classes.mkdir()
        source_path.write_bytes(probe_bytes)
        fixture_copy.write_bytes(fixture_bytes)
        compile_result = run_bounded(
            [str(java), "-cp", compiler_cp, "scala.tools.nsc.Main",
             "-classpath", classpath, "-d", str(classes), str(source_path)],
            cwd=str(ROOT), timeout=150,
        )
        if compile_result.returncode != 0:
            raise RuntimeError(
                "mask math Scala probe compile failed: "
                f"{compile_result.stderr or compile_result.stdout}")
        started = time.monotonic()
        result = run_bounded(
            [str(java), "-cp", str(classes) + os.pathsep + classpath,
             "local.ee.reduce.MaskMathKernelProbe", str(fixture_copy)],
            cwd=str(ROOT), timeout=120,
        )
        elapsed = time.monotonic() - started
        if result.returncode != 0:
            raise RuntimeError(
                f"mask math native probe failed: {result.stderr or result.stdout}")
        marker = "MASK_MATH_NATIVE_RESULT "
        line = next((line for line in result.stdout.splitlines() if line.startswith(marker)), None)
        if line is None:
            raise RuntimeError(f"native probe emitted no result marker: {result.stdout}")
        native = json.loads(line[len(marker):])

    if native.get("fixture_schema") != fixture["schema"]:
        raise RuntimeError("native probe returned a different fixture identity")
    expected_outputs = {
        "red_sqrt", "red_log", "wide_add_right", "wide_add_left",
        "red_clamp", "red_unit_scale", "wide_to_float", "wide_float32_asin",
        "wide_pixel_asin", "wide_pixel_atan2_right", "wide_pixel_atan2_left",
    }
    if not expected_outputs.issubset(native.get("outputs", {})):
        raise RuntimeError("native probe omitted required Wave66 math outputs")
    if native.get("source_infinity_guard_rejected") != [True, True]:
        raise RuntimeError("native source guard did not reject both zero-weight infinities")

    summary = {
        "fixture_schema": fixture["schema"],
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "probe_source_sha256": hashlib.sha256(probe_bytes).hexdigest(),
        "manifest_path": str(checked["manifest_path"]),
        "manifest_sha256": sha256(checked["manifest_path"]),
        "jar_path": str(jar),
        "jar_sha256": manifest["jar_sha256"],
        "source_count": len(manifest["sources"]),
        "scala_tool_count": len(scala_tools),
        "runtime_jar_count": len(runtime_jars),
        "deployment_eligible": manifest["deployment_eligible"],
        "elapsed_seconds": round(elapsed, 3),
        "native_output_count": len(native["outputs"]),
        "sample_value_row_count": len(native["values_sample_rows"]),
        "sample_weight_row_count": len(native["weights_sample_rows"]),
        "source_infinity_guard_rejected": native["source_infinity_guard_rejected"],
        "loaded_spi_ids": native["loaded_spi_ids"],
        "execution_scope": (
            "Actual local GeoTrellis Float64/Float32 tile kernels, mask apply/result_value/validity/update, "
            "and existing Image.sample kernel. The Scala probe is compiled in a temporary directory; "
            "no SparkContext, engine service, VM, container, private data, or Google request is used."
        ),
    }
    summary["native_result"] = native
    if receipt_dir is not None:
        receipt_dir = Path(receipt_dir).expanduser().resolve()
        receipt_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        receipt = receipt_dir / f"native-{stamp}-{os.getpid()}-{uuid.uuid4().hex[:12]}.json"
        descriptor = os.open(receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({key: value for key, value in summary.items() if key != "native_result"},
                      stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        summary["receipt_path"] = str(receipt)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=EXPECTED_MANIFEST)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--receipt-dir", type=Path)
    args = parser.parse_args()
    summary = run_probe(args.manifest, args.fixture, args.receipt_dir)
    print(json.dumps({key: value for key, value in summary.items() if key != "native_result"},
                     ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
