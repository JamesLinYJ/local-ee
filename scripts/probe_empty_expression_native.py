#!/usr/bin/env python3
"""Run the bounded Wave67 probe on the retained Wave66 audit artifact."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from ee_kernel_subprocess import run_bounded
from scripts.ee_audit_native_manifest import CURRENT_ADAPTER_MANIFEST, validate_native_manifest
from scripts.build_integer_adapter import SOURCES


EXPECTED_MANIFEST = CURRENT_ADAPTER_MANIFEST
DEFAULT_FIXTURE = ROOT / "tests/fixtures/ee-empty-expression-wave67-v1.json"
PROBE_SOURCE = ROOT / "tests/fixtures/ee-empty-expression-kernel-probe.scala"
EXPECTED_ADAPTER = "local-ee-mask-weights-audit-adapter"
MAX_FIXTURE_BYTES = 1_000_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_fixture(path: Path) -> tuple[bytes, dict]:
    raw = path.expanduser().resolve(strict=True).read_bytes()
    if len(raw) > MAX_FIXTURE_BYTES:
        raise ValueError(f"Wave67 fixture exceeds {MAX_FIXTURE_BYTES} bytes")
    fixture = json.loads(raw)
    if (type(fixture) is not dict
            or fixture.get("schema") != "local-ee-empty-expression-wave67/v1"
            or fixture.get("source_bands") != [
                "red", "nir", "mask_science", "old_weight", "new_weight"
            ]):
        raise ValueError("fixture does not satisfy local-ee-empty-expression-wave67/v1")
    grid = fixture.get("grid")
    if (type(grid) is not dict or grid.get("tile_cols") != 4
            or grid.get("tile_rows") != 4):
        raise ValueError("Wave67 native probe requires one 4x4 tile")
    science = fixture.get("source_values")
    transitions = fixture.get("mask_transitions")
    if (type(science) is not dict or set(science) != {"red", "nir"}
            or type(transitions) is not dict
            or set(transitions) != {"science", "old_weights", "new_weights", "case_names"}):
        raise ValueError("Wave67 fixture has an invalid science or mask transition payload")
    frozen_keys = (
        "schema", "fixture_id", "input_only", "source_id", "source_bands",
        "source_values", "grid", "region", "mask_transitions", "provenance",
    )
    canonical_inputs = json.dumps(
        {key: fixture[key] for key in frozen_keys}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    if (fixture.get("input_only") is not True
            or fixture.get("frozen_before_local_compile") is not True
            or fixture.get("provenance", {}).get("production_results_included") is not False
            or fixture.get("frozen_input_sha256") != hashlib.sha256(canonical_inputs).hexdigest()):
        raise ValueError("Wave67 original inputs are not frozen or contain production results")
    if any(type(science[name]) is not list or len(science[name]) != 16
           for name in ("red", "nir")):
        raise ValueError("Wave67 science bands must contain exactly 16 values")
    if any(type(transitions[name]) is not list or len(transitions[name]) != 16
           for name in ("science", "old_weights", "new_weights", "case_names")):
        raise ValueError("Wave67 mask transition bands must contain exactly 16 values")
    if not PROBE_SOURCE.is_file():
        raise FileNotFoundError(PROBE_SOURCE)
    return raw, fixture


def _write_receipt(directory: Path, payload: dict) -> Path:
    directory = Path(directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / f"probe-{stamp}-{os.getpid()}-{uuid.uuid4().hex[:12]}.json"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return path


def run_probe(fixture_path: Path = DEFAULT_FIXTURE,
              manifest_path: Path = EXPECTED_MANIFEST,
              receipt_dir: Path | None = None) -> dict:
    manifest_path = Path(manifest_path).expanduser().resolve(strict=True)
    checked = validate_native_manifest(
        manifest_path, expected_adapter=EXPECTED_ADAPTER,
    )
    manifest = checked["manifest"]
    if (len(manifest.get("sources", {})) != len(SOURCES)
            or len(checked["scala_tools"]) != 3
            or len(checked["runtime_jars"]) != 245
            or manifest.get("deployment_eligible") is not False
            or "25" not in str(manifest.get("java_version", ""))):
        raise ValueError("Native manifest must verify the current exact source set, JDK 25, and the retained 245-JAR classpath")
    fixture_path = Path(fixture_path).expanduser().resolve(strict=True)
    fixture_bytes, fixture = _validate_fixture(fixture_path)
    probe_bytes = PROBE_SOURCE.read_bytes()
    java = Path(manifest["java"]).expanduser().resolve(strict=True)
    java_home = java.parent.parent
    compiler_classpath = os.pathsep.join(map(str, checked["scala_tools"]))
    runtime_classpath = os.pathsep.join(map(str, [checked["jar"], *checked["runtime_jars"]]))
    result_payload = None
    native_result = None
    try:
        with tempfile.TemporaryDirectory(prefix="local-ee-wave67-") as temporary:
            scratch = Path(temporary)
            source_path = scratch / "EmptyExpressionKernelProbe.scala"
            fixture_copy = scratch / "fixture.json"
            classes = scratch / "classes"
            classes.mkdir()
            source_path.write_bytes(probe_bytes)
            fixture_copy.write_bytes(fixture_bytes)
            compile_result = run_bounded(
                [str(java), "-Xmx1g", "-cp", compiler_classpath,
                 "scala.tools.nsc.Main", "-classpath", runtime_classpath,
                 "-d", str(classes), str(source_path)],
                cwd=str(ROOT), timeout=150,
                env={**os.environ, "JAVA_HOME": str(java_home)},
            )
            if compile_result.returncode != 0:
                raise RuntimeError(
                    "Wave67 Scala probe compile failed: "
                    f"{compile_result.stderr or compile_result.stdout}")
            jvm_opens = [f"--add-opens=java.base/{module}=ALL-UNNAMED" for module in (
                "java.io", "java.lang", "java.lang.invoke", "java.lang.reflect", "java.net",
                "java.nio", "java.util", "java.util.concurrent", "java.util.concurrent.atomic",
                "sun.nio.ch", "sun.nio.cs", "sun.security.action", "sun.util.calendar",
            )]
            environment = {
                **os.environ, "JAVA_HOME": str(java_home),
                "SPARK_LOCAL_IP": "127.0.0.1", "SPARK_LOCAL_HOSTNAME": "localhost",
            }
            probe = run_bounded(
                [str(java), "-Xmx1g", *jvm_opens, "-cp",
                 os.pathsep.join(map(str, [classes, checked["jar"], *checked["runtime_jars"]])),
                 "local.ee.reduce.EmptyExpressionKernelProbe", str(fixture_copy)],
                cwd=str(ROOT), timeout=90, env=environment,
            )
            if probe.returncode != 0:
                raise RuntimeError(
                    f"Wave67 native probe failed: {probe.stderr or probe.stdout}")
            marker = "EMPTY_EXPRESSION_NATIVE_RESULT "
            line = next((line for line in probe.stdout.splitlines()
                         if line.startswith(marker)), None)
            if line is None:
                raise RuntimeError(f"Wave67 probe emitted no result marker: {probe.stdout}")
            native = json.loads(line[len(marker):])
            native_result = native
            if any(len(native[name]) != 16 for name in (
                    "setter_values", "setter_weights", "update_mask_values", "update_mask_weights",
                    "fractional_hidden_recovery_values", "fractional_hidden_recovery_weights")):
                raise RuntimeError("Wave67 native probe returned an incomplete 4x4 transition tile")
            result_payload = {
                "status": "passed",
                "fixture_schema": fixture["schema"],
                "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
                "probe_source_sha256": hashlib.sha256(probe_bytes).hexdigest(),
                "manifest_path": str(checked["manifest_path"]),
                "manifest_sha256": sha256(checked["manifest_path"]),
                "jar_path": str(checked["jar"]),
                "jar_sha256": manifest["jar_sha256"],
                "source_count": len(manifest["sources"]),
                "scala_tool_count": len(checked["scala_tools"]),
                "runtime_jar_count": len(checked["runtime_jars"]),
                "java_version": manifest["java_version"],
                "deployment_eligible": False,
                "sample_row_counts": {
                    key: len(native[key])
                    for key in (
                        "map_sample_rows", "default_value_sample_rows",
                        "default_weight_sample_rows", "setter_value_sample_rows",
                        "setter_weight_sample_rows", "update_mask_value_sample_rows",
                        "update_mask_weight_sample_rows",
                        "fractional_hidden_recovery_value_sample_rows",
                        "fractional_hidden_recovery_weight_sample_rows",
                    )
                },
                "native_result": native,
                "numeric_comparison": "IEEE-754 Float64 bitwise equality (0 ULP tolerance)",
                "scope": (
                    "Actual LocalEeMaskWeightsNumeric.applyTile, one 4x4 local[1] "
                    "LocalEeMaskCubeProcesses.unmask call, and LocalEeImageSampleKernel. "
                    "This does not establish full Spark batch, browser, deployment, or Google equivalence."
                ),
            }
    except Exception as error:
        if receipt_dir is not None:
            _write_receipt(receipt_dir, {
                "status": "failed", "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
                "probe_source_sha256": hashlib.sha256(probe_bytes).hexdigest(),
                "manifest_path": str(manifest_path), "error": repr(error),
                "deployment_eligible": False,
                **({"native_result": native_result} if native_result is not None else {}),
            })
        raise
    if result_payload is None:
        raise RuntimeError("Wave67 probe produced no result payload")
    if receipt_dir is not None:
        result_payload["receipt_path"] = str(_write_receipt(receipt_dir, {
            key: value for key, value in result_payload.items()
        }))
    return result_payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=EXPECTED_MANIFEST)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--receipt-dir", type=Path)
    args = parser.parse_args()
    summary = run_probe(args.fixture, args.manifest, args.receipt_dir)
    print(json.dumps({key: value for key, value in summary.items() if key != "native_result"},
                     ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
