"""Independent numeric controls and opt-in trusted GeoTrellis distance probe."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import uuid

import pytest

from ee_distance_kernel_helpers import (
    _float,
    canonical_invalid_specs,
    make_fixture,
)
from ee_kernel_subprocess import run_bounded
from gee.distance_spec import decode_distance_spec, prepare_distance_spec
from scripts.build_integer_adapter import ROOT, _engine_paths, sha256


DISTANCE_SOURCES = (
    "engine/ee_distance_spec.scala",
    "engine/ee_distance_budget.scala",
    "engine/ee_distance_numeric.scala",
    "engine/ee_distance_adapter.scala",
)


def _case(fixture, name):
    return next(value for value in fixture["cases"] if value["name"] == name)


def _pixel(case, col, row):
    return _float(case["expected"][row * case["width"] + col])


def test_distance_reference_covers_metrics_radius_masks_keys_and_value_range():
    fixture = make_fixture()
    assert fixture["schema"] == "local-ee-synthetic-image-distance/v1"
    assert fixture["case_count"] >= 10
    assert fixture["grid_slot_count"] == fixture["case_count"] * 8 * 6
    assert fixture["evaluated_pixel_count"] < fixture["grid_slot_count"]
    assert {case["metric"] for case in fixture["cases"]} == {
        "euclidean", "manhattan", "chebyshev",
    }

    below = _case(fixture, "fractional-euclidean-nextafter-sqrt2-below")
    at_sqrt2 = _case(fixture, "fractional-euclidean-sqrt2")
    assert _pixel(below, 3, 2) is None
    assert _pixel(at_sqrt2, 3, 2) == math.sqrt(2.0)
    assert _pixel(_case(fixture, "fractional-manhattan-1_5"), 3, 2) is None
    assert _pixel(_case(fixture, "fractional-chebyshev-1_5"), 3, 2) == 1.0
    subnormal = _case(fixture, "subnormal-radius-includes-only-center")
    assert subnormal["radius"] == math.ulp(0.0)
    assert _pixel(subnormal, 3, 1) == 0.0
    assert _pixel(subnormal, 2, 1) is None

    masked = _case(fixture, "masked-center-skip")
    filled = _case(fixture, "masked-center-fill")
    assert _pixel(masked, 4, 2) is None
    assert _pixel(filled, 4, 2) == 2.0  # The closer masked candidate is ignored.
    assert all(value is None for value in _case(fixture, "no-target-no-sentinel")["expected"])

    missing = _case(fixture, "missing-tile-is-not-a-target")
    assert (1, 0) not in {tuple(key) for key in missing["tile_keys"]}
    assert _pixel(missing, 3, 1) is None
    assert _pixel(_case(fixture, "edge-target-positive-control"), 1, 1) == 1.0

    for metric in ("euclidean", "manhattan", "chebyshev"):
        case = _case(fixture, f"metric-{metric}-radius-2")
        assert _pixel(case, 3, 1) == 0.0       # Negative, nonzero target.
        assert _pixel(case, 2, 1) == 1.0
        assert _pixel(case, 4, 4) == 0.0       # Smallest subnormal target.
        assert _pixel(case, 6, 1) == 0.0       # Largest finite Float64 target.
        assert _pixel(case, 0, 5) == 0.0       # Negative extreme target.

    radius_zero = _case(fixture, "radius-zero-positive-control")
    assert _pixel(radius_zero, 3, 1) == 0.0
    assert _pixel(radius_zero, 2, 1) is None


def test_distance_wire_is_exact_canonical_and_bounded():
    for metric in ("euclidean", "manhattan", "chebyshev"):
        text = prepare_distance_spec(metric, 16.0, False)
        assert len(text) <= 1024
        spec = decode_distance_spec(text)
        assert spec == {
            "metric": metric,
            "radius": "4030000000000000",
            "skip_masked": False,
            "v": 1,
        }
    assert decode_distance_spec(prepare_distance_spec("euclidean", -0.0))["radius"] == \
        "0000000000000000"

    for text in canonical_invalid_specs():
        with pytest.raises(ValueError):
            decode_distance_spec(text)
    for metric, radius, skip_masked in (
        ("circle", 1, True), ("euclidean", -0.1, True),
        ("euclidean", 16.1, True), ("euclidean", float("inf"), True),
        ("euclidean", True, True), ("euclidean", 1, 1),
    ):
        with pytest.raises(ValueError):
            prepare_distance_spec(metric, radius, skip_masked)


def test_native_distance_contract_is_canonical_bounded_and_registered():
    adapter = (ROOT / "engine/ee_distance_adapter.scala").read_text()
    spec = (ROOT / "engine/ee_distance_spec.scala").read_text()
    numeric = (ROOT / "engine/ee_distance_numeric.scala").read_text()
    budget = (ROOT / "engine/ee_distance_budget.scala").read_text()
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text()
    probe = (ROOT / "tests/fixtures/ee-distance-kernel-probe.scala").read_text()
    doc = (ROOT / "docs/gee-python/distance.md").read_text()

    assert 'id = "local_ee_distance"' in adapter
    assert 'arguments.size() == 1 && arguments.containsKey("spec")' in adapter
    assert "LocalEeDistanceSpec.parse(value)" in adapter
    assert "input.names.length == 1" in adapter
    assert 'encoded.matches("[0-9a-f]{16}")' in spec
    assert "STRICT_DUPLICATE_DETECTION" in spec
    assert "floorPowerOfTwo" in spec and "squaredRadiusFloor" in spec
    assert "radiusBits: Long" in spec and "val halo: Int = math.ceil(radius)" in spec
    assert "value != 0.0d" in numeric and "skipMasked && center.isNaN" in numeric
    assert "DoubleArrayTile(output, outputCols, outputRows, DoubleConstantNoDataCellType)" in numeric
    for cap in ("MaxSourceKeys = 100000L", "MaxDecodedCells = 100000000L",
                "MaxTileDecodedCells = 10000000L", "MaxDistanceWork = 1000000000L",
                "MaxPerTileWork = 100000000L"):
        assert cap in budget
    assert "LocalEeDistanceBudget.plan" in adapter
    for source in DISTANCE_SOURCES:
        assert source in builder
    assert "LocalEeDistanceCubeProcessProvider" in builder
    assert "BufferTilesRDD(tiles, setup.spec.halo, bounds).toMap" in probe
    assert "SpaceTimeKey" in probe and "verifyTemporalIsolation" in probe
    assert "SparkContext(" not in probe
    doc_lower = doc.lower()
    assert ("nextafter" in doc_lower and "no target" in doc_lower
            and "1,000,000,000" in doc_lower
            and "upstream graph evaluation" in doc_lower and "end-to-end" in doc_lower)


def test_actual_distance_tiles_match_fraction_reference_and_buffered_collection():
    if os.environ.get("LOCAL_EE_RUN_DISTANCE_KERNEL_TEST") != "1":
        pytest.skip("opt-in trusted GeoTrellis distance probe; no SparkContext, service, or user code")
    audit_env = os.environ.get("GEE_AUDIT_DIR")
    if not audit_env:
        pytest.skip("opt-in native distance probe requires a unique GEE_AUDIT_DIR")

    fixture = make_fixture()
    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:10]}"
    scratch = Path(tempfile.mkdtemp(prefix=f"local-ee-distance-{run_id}-"))
    audit_root = Path(audit_env).expanduser().resolve()
    audit_target = audit_root / f"distance-kernel-{run_id}"
    audit_target.mkdir(parents=True, exist_ok=False)
    jar = scratch / "local-ee-integer-adapter.jar"
    successful = False
    build_seconds = 0.0
    probe_seconds = 0.0

    def save_audit(name: str, contents: str) -> None:
        (audit_target / name).write_text(contents, encoding="utf-8")

    tracked = [ROOT / source for source in DISTANCE_SOURCES]
    tracked += [
        ROOT / "scripts/build_integer_adapter.py",
        ROOT / ".native/engine-lock.json",
        ROOT / "gee/distance_spec.py",
        ROOT / "engine/ee_reduce_support.scala",
        ROOT / "tests/ee_kernel_subprocess.py",
        ROOT / "tests/ee_distance_kernel_helpers.py",
        ROOT / "tests/test_ee_distance_kernel.py",
        ROOT / "tests/fixtures/ee-distance-kernel-probe.scala",
    ]
    save_audit("source-hashes.json", json.dumps({
        path.relative_to(ROOT).as_posix(): sha256(path) for path in tracked
    }, indent=2, sort_keys=True) + "\n")

    try:
        cases_path = scratch / "distance-cases.json"
        fixture_json = json.dumps(fixture, indent=2, allow_nan=False) + "\n"
        cases_path.write_text(fixture_json, encoding="utf-8")
        save_audit("distance-cases.json", fixture_json)

        started = time.monotonic()
        build = run_bounded(
            [sys.executable, str(ROOT / "scripts/build_integer_adapter.py"),
             "--output", str(jar)],
            cwd=str(ROOT), timeout=300,
        )
        build_seconds = time.monotonic() - started
        save_audit("adapter-build.stdout.txt", build.stdout)
        save_audit("adapter-build.stderr.txt", build.stderr)
        assert build.returncode == 0, build.stderr
        manifest = json.loads(build.stdout)
        assert manifest["adapter"] == "local-ee-integer-adapter"
        assert all(source in manifest["sources"] for source in DISTANCE_SOURCES)
        assert "engine/ee_reduce_support.scala" in manifest["sources"]
        assert manifest["jar_sha256"] == sha256(jar)
        save_audit("adapter-manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")

        java, _, compiler_tools, runtime_jars, _ = _engine_paths()
        classpath = os.pathsep.join(map(str, [jar, *runtime_jars]))
        classes = scratch / "probe-classes"
        classes.mkdir()
        probe_source = ROOT / "tests/fixtures/ee-distance-kernel-probe.scala"
        compile_result = run_bounded(
            [str(java), "-cp", os.pathsep.join(map(str, compiler_tools)),
             "scala.tools.nsc.Main", "-classpath", classpath,
             "-d", str(classes), str(probe_source)],
            cwd=str(ROOT), timeout=150,
        )
        save_audit("probe-compile.stdout.txt", compile_result.stdout)
        save_audit("probe-compile.stderr.txt", compile_result.stderr)
        assert compile_result.returncode == 0, compile_result.stderr

        started = time.monotonic()
        probe_result = run_bounded(
            [str(java), "-cp", str(classes) + os.pathsep + classpath,
             "local.ee.reduce.EeDistanceKernelProbe", str(cases_path)],
            cwd=str(ROOT), timeout=180,
        )
        probe_seconds = time.monotonic() - started
        save_audit("probe-run.stdout.txt", probe_result.stdout)
        save_audit("probe-run.stderr.txt", probe_result.stderr)
        assert probe_result.returncode == 0, probe_result.stderr
        line = next((item for item in probe_result.stdout.splitlines()
                     if item.startswith("DISTANCE_KERNEL_OK ")), "")
        assert line, probe_result.stdout
        counts = dict(re.findall(r"([a-z0-9_]+)=([^ ]+)", line))
        assert counts["cases"] == str(fixture["case_count"])
        assert counts["manual_pixels"] == str(fixture["evaluated_pixel_count"])
        assert counts["collection_pixels"] == str(fixture["evaluated_pixel_count"])
        assert counts["grid_slots"] == str(fixture["grid_slot_count"])
        assert counts["temporal_keys"] == "4"
        assert counts["wire_rejects"] == str(len(fixture["invalid_specs"]))
        assert counts["budget_metrics"] == "3"
        assert counts["budget_total_rejects"] == "3"
        assert counts["budget_guard_rejects"] == "5"
        assert counts["numeric_guard_rejects"] == "5"
        save_audit("kernel-result.json", json.dumps({
            "scope": "actual Float64 GeoTrellis tiles, independent whole-grid Fraction oracle, manual halo and BufferTilesRDD paths; no SparkContext/service/user code",
            "summary": counts,
            "case_count": fixture["case_count"],
            "evaluated_pixels_per_path": fixture["evaluated_pixel_count"],
            "whole_grid_slots_compared_per_path": fixture["grid_slot_count"],
            "fixture_bytes": len(fixture_json.encode("utf-8")),
            "build_seconds": build_seconds,
            "probe_seconds": probe_seconds,
            "radius_boundary": "exact binary64 squared comparison around nextafter(sqrt(2), 0)",
            "large_tile_budget": "256x256 tiles at radius 16 for all three metrics, including the exact 1e9 total-work accept/reject boundary",
            "negative_controls": {
                "budget_guards": int(counts["budget_guard_rejects"]),
                "numeric_guards": int(counts["numeric_guard_rejects"]),
            },
            "no_target": "expected Double NaN NoData; no finite sentinel assumed",
            "stdout": probe_result.stdout,
        }, indent=2, sort_keys=True) + "\n")
        successful = True
    except BaseException as error:
        save_audit("failure.txt", f"{type(error).__name__}: {error}\n")
        raise
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        scratch_cleaned = not scratch.exists()
        save_audit("scratch-cleanup-readback.json", json.dumps({
            "scratch": str(scratch),
            "removed": scratch_cleaned,
            "result": "passed" if successful else "failed; fixture and logs retained in audit",
        }, indent=2, sort_keys=True) + "\n")
        assert scratch_cleaned, f"owned distance scratch directory remains: {scratch}"
