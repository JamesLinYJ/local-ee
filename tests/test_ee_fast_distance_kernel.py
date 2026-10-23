"""Portable reference contracts and opt-in GeoTrellis fast-distance validation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

import pytest

from ee_fast_distance_kernel_helpers import (
    METRICS,
    NO_TARGET_DISTANCE,
    brute_force_transform,
    digest_unsigned,
    make_fixture,
)
from ee_kernel_subprocess import run_bounded
from gee.fast_distance_spec import (
    decode_fast_distance_spec,
    fast_distance_process_spec,
    prepare_fast_distance_spec,
)
from scripts.build_integer_adapter import ROOT, _engine_paths, sha256


FAST_DISTANCE_SOURCES = (
    "engine/ee_fast_distance_spec.scala",
    "engine/ee_fast_distance_budget.scala",
    "engine/ee_fast_distance_halo.scala",
    "engine/ee_fast_distance_adapter.scala",
    "engine/ee_fast_distance_transform.scala",
    "engine/ee_fast_distance_transform_envelope.scala",
)


def _source_case(fixture, name):
    return next(case for case in fixture["source_cases"] if case["name"] == name)


def test_fast_distance_oracle_and_fixture_cover_masks_keys_time_and_large_windows():
    fixture = make_fixture()
    assert fixture == make_fixture()
    assert fixture["schema"] == "local-ee-synthetic-fast-distance/v1"
    assert fixture["kernel_case_count"] == len(fixture["kernel_cases"]) == 13
    assert fixture["source_case_count"] == len(fixture["source_cases"]) == 16
    assert fixture["source_observed_keys"] == sum(
        case["observed_key_count"] for case in fixture["source_cases"]
    )
    assert fixture["source_evaluated_pixels"] == sum(
        case["evaluated_pixel_count"] for case in fixture["source_cases"]
    )
    assert fixture["source_grid_slots"] == sum(
        case["grid_slot_count"] for case in fixture["source_cases"]
    )
    assert {case["metric"] for case in fixture["kernel_cases"]} == set(METRICS)

    expected = {
        "squared_euclidean": [2, 1, 2, 1, 0, 1],
        "manhattan": [2, 1, 2, 1, 0, 1],
        "chebyshev": [1, 1, 1, 1, 0, 1],
    }
    for metric, values in expected.items():
        assert brute_force_transform([0, 0, 0, 0, 1, 0], 3, 2, metric) == values
        assert brute_force_transform([0] * 7, 7, 1, metric) == [NO_TARGET_DISTANCE] * 7

    long_line = next(case for case in fixture["kernel_cases"] if "long-line" in case["name"])
    assert long_line["width"] == 65_537 and long_line["height"] == 1
    assert long_line["last_value"] == 65_536**2 > 2**31 - 1
    assert long_line["digest"] == digest_unsigned([x * x for x in range(65_537)])
    assert digest_unsigned([0x01020304], width=4) == hashlib.sha256(
        bytes.fromhex("01020304")
    ).hexdigest()

    default_spec = decode_fast_distance_spec(prepare_fast_distance_spec())
    assert default_spec == {
        "metric": "squared_euclidean", "neighborhood": 256, "v": 1,
    }
    process = fast_distance_process_spec()
    assert "default256" in process["description"]
    assert "finite Int32" in process["description"]
    assert "absent source keys remain absent" in process["description"]

    wide = [case for case in fixture["source_cases"]
            if case["name"].startswith("default-neighborhood-256-")]
    assert {case["metric"] for case in wide} == set(METRICS)
    assert all(case["neighborhood"] == 256 and case["tile_cols"] == 256
               and case["tile_rows"] == 256 and case["observed_key_count"] == 9
               for case in wide)
    multihop = [case for case in fixture["source_cases"]
                if case["name"].startswith("two-tile-hop-temporal-")]
    assert len(multihop) == 3
    assert all(case["observed_key_count"] == 16 for case in multihop)
    assert all({tuple(tile["key"]) for tile in case["tiles"]}
               == {tuple(tile["key"]) for tile in case["expected_tiles"]}
               for case in fixture["source_cases"])

    numeric = _source_case(fixture, "finite-sign-subnormal-extremes-and-masked-center")
    assert numeric["probes"][0]["value"] == 2
    assert numeric["probes"][1]["value"] == 10
    assert all("expected_tiles" in case and len(case["expected_tiles"]) == case["observed_key_count"]
               for case in fixture["source_cases"])


def test_fast_distance_native_contract_has_strict_wire_budgets_and_real_probe_calls():
    adapter = (ROOT / "engine/ee_fast_distance_adapter.scala").read_text()
    spec = (ROOT / "engine/ee_fast_distance_spec.scala").read_text()
    budget = (ROOT / "engine/ee_fast_distance_budget.scala").read_text()
    halo = (ROOT / "engine/ee_fast_distance_halo.scala").read_text()
    transform = (ROOT / "engine/ee_fast_distance_transform.scala").read_text()
    envelope = (ROOT / "engine/ee_fast_distance_transform_envelope.scala").read_text()
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text()
    probe = (ROOT / "tests/fixtures/ee-fast-distance-kernel-probe.scala").read_text()
    controls = (ROOT / "tests/fixtures/ee-fast-distance-kernel-controls.scala").read_text()
    doc = (ROOT / "docs/gee-python/fast-distance.md").read_text()

    assert 'id = "local_ee_fast_distance_transform"' in adapter
    assert 'arguments.size() == 1 && arguments.containsKey("spec")' in adapter
    assert "LocalEeFastDistanceSpec.parse(value)" in adapter
    assert "input.names.length == 1" in adapter
    assert "STRICT_DUPLICATE_DETECTION" in spec
    assert "text == canonicalJson(result)" in spec
    assert "MaxNeighborhood = 4096" in spec
    assert "Math.multiplyExact(neighborhood, neighborhood)" in spec
    assert "MaxAggregateWork = 1000000000L" in budget
    assert "MaxPerTileWork = 100000000L" in budget
    assert "targetsFromTile" in halo and "value != 0.0d" in halo
    assert "value.isNaN || value.isFinite" in halo
    assert "def emitFragments" in halo and "def assemble" in halo
    assert "def apply" in transform and "Array[Long]" in transform
    assert "Long.MaxValue / 4L" in envelope
    assert "LocalEeFastDistanceHalo.targetsFromTile" in probe
    assert "LocalEeFastDistanceHalo.emitFragments" in probe
    assert "LocalEeFastDistanceHalo.assemble" in probe
    assert "LocalEeFastDistanceTransform.apply" in probe
    assert "FAST_DISTANCE_KERNEL_OK" in probe
    assert "SparkContext(" not in probe and "ServiceLoader" not in probe
    assert "verifyTileAndFragmentGuards" in probe and "verifyBudgetBoundaries" in probe
    assert "targetsFromTile(null" in controls
    assert "oversized fragment groups must fail before allocating" in controls
    assert "duplicate center markers must fail closed" in controls
    assert "MaxAggregateWork / (representative.perTileWork + 1L)" in controls
    assemble_source = halo[halo.index("def assemble("):]
    assert assemble_source.index("val firstPass = pieces.iterator") < assemble_source.index(
        "val targets = new Array[Boolean]")
    for source in FAST_DISTANCE_SOURCES:
        assert source in builder
    assert "LocalEeFastDistanceCubeProcessProvider" in builder
    assert "256 by" in doc and "4096" in doc and "mask" in doc.lower()


def test_actual_fast_distance_tiles_match_independent_digests_and_key_sets():
    if os.environ.get("LOCAL_EE_RUN_FAST_DISTANCE_KERNEL_TEST") != "1":
        pytest.skip("opt-in trusted GeoTrellis tile probe; no SparkContext, service, or user code")
    audit_env = os.environ.get("GEE_AUDIT_DIR")
    if not audit_env:
        pytest.skip("opt-in native fast-distance probe requires a unique GEE_AUDIT_DIR")

    fixture = make_fixture()
    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:10]}"
    audit_target = Path(audit_env).expanduser().resolve() / f"fast-distance-kernel-{run_id}"
    audit_target.mkdir(parents=True, exist_ok=False)
    scratch_base = ROOT.parent.parent / "work" / "gee-python-wave48-fast-distance-kernel"
    scratch_base_created = not scratch_base.exists()
    scratch_base.mkdir(parents=True, exist_ok=True)
    scratch = scratch_base / run_id
    scratch.mkdir(parents=False, exist_ok=False)
    jar = scratch / "local-ee-integer-adapter.jar"
    successful = False
    build_seconds = 0.0
    probe_seconds = 0.0

    def save_audit(name: str, contents: str) -> None:
        (audit_target / name).write_text(contents, encoding="utf-8")

    try:
        cases_path = scratch / "fast-distance-cases.json"
        fixture_json = json.dumps(fixture, indent=2, allow_nan=False) + "\n"
        cases_path.write_text(fixture_json, encoding="utf-8")
        save_audit("fast-distance-cases.json", fixture_json)

        builder = ROOT / "scripts/build_integer_adapter.py"
        started = time.monotonic()
        build = run_bounded(
            [sys.executable, str(builder), "--output", str(jar)],
            cwd=str(ROOT), timeout=300,
        )
        build_seconds = time.monotonic() - started
        save_audit("adapter-build.stdout.txt", build.stdout)
        save_audit("adapter-build.stderr.txt", build.stderr)
        assert build.returncode == 0, build.stderr
        manifest = json.loads(build.stdout)
        assert manifest["adapter"] == "local-ee-integer-adapter"
        assert all(source in manifest["sources"] for source in FAST_DISTANCE_SOURCES)
        assert manifest["jar_sha256"] == sha256(jar)
        save_audit("adapter-manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")

        # The adapter manifest hashes every Scala source passed to scalac. Add only
        # direct Python/test inputs and the lock files actually read by this probe.
        direct_inputs = (
            ROOT / "scripts/build_integer_adapter.py",
            ROOT / ".native/engine-lock.json",
            ROOT / "gee/fast_distance_spec.py",
            ROOT / "tests/ee_fast_distance_kernel_helpers.py",
            ROOT / "tests/test_ee_fast_distance_kernel.py",
            ROOT / "tests/ee_kernel_subprocess.py",
            ROOT / "tests/fixtures/ee-fast-distance-kernel-probe.scala",
            ROOT / "tests/fixtures/ee-fast-distance-kernel-controls.scala",
        )
        source_hashes = {name: digest for name, digest in manifest["sources"].items()}
        for path in direct_inputs:
            source_hashes[path.relative_to(ROOT).as_posix()] = sha256(path)
        assert manifest["build_script_sha256"] == source_hashes["scripts/build_integer_adapter.py"]
        save_audit("source-hashes.json", json.dumps(source_hashes, indent=2, sort_keys=True) + "\n")

        java, _, compiler_tools, runtime_jars, _ = _engine_paths()
        classpath = os.pathsep.join(map(str, [jar, *runtime_jars]))
        classes = scratch / "probe-classes"
        classes.mkdir()
        probe_source = ROOT / "tests/fixtures/ee-fast-distance-kernel-probe.scala"
        controls_source = ROOT / "tests/fixtures/ee-fast-distance-kernel-controls.scala"
        compile_result = run_bounded(
            [str(java), "-cp", os.pathsep.join(map(str, compiler_tools)),
             "scala.tools.nsc.Main", "-classpath", classpath,
             "-d", str(classes), str(probe_source), str(controls_source)],
            cwd=str(ROOT), timeout=150,
        )
        save_audit("probe-compile.stdout.txt", compile_result.stdout)
        save_audit("probe-compile.stderr.txt", compile_result.stderr)
        assert compile_result.returncode == 0, compile_result.stderr

        started = time.monotonic()
        result = run_bounded(
            [str(java), "-cp", str(classes) + os.pathsep + classpath,
             "local.ee.reduce.EeFastDistanceKernelProbe", str(cases_path)],
            cwd=str(ROOT), timeout=180,
        )
        probe_seconds = time.monotonic() - started
        save_audit("probe-run.stdout.txt", result.stdout)
        save_audit("probe-run.stderr.txt", result.stderr)
        assert result.returncode == 0, result.stderr
        line = next((item for item in result.stdout.splitlines()
                     if item.startswith("FAST_DISTANCE_KERNEL_OK ")), "")
        assert line, result.stdout
        counts = dict(re.findall(r"([a-z0-9_]+)=([^ ]+)", line))
        expected_kernel_pixels = sum(case["width"] * case["height"]
                                      for case in fixture["kernel_cases"])
        long_line = next(case for case in fixture["kernel_cases"] if "long-line" in case["name"])
        assert counts["kernel_cases"] == str(fixture["kernel_case_count"])
        assert counts["kernel_pixels"] == str(expected_kernel_pixels)
        assert counts["long_line_last"] == str(long_line["last_value"])
        assert counts["source_cases"] == str(fixture["source_case_count"])
        assert counts["source_keys"] == str(fixture["source_observed_keys"])
        assert counts["source_pixels"] == str(fixture["source_evaluated_pixels"])
        assert counts["grid_slots"] == str(fixture["source_grid_slots"])
        assert int(counts["fragments"]) > 0
        assert counts["default_plan_cases"] == "3"
        assert counts["two_hop_crosses"] == "3"
        assert counts["wire_rejects"] == str(len(fixture["invalid_specs"]))
        assert counts["tile_rejects"] == "4"
        assert counts["fragment_rejects"] == "5"
        assert counts["duplicate_center_rejects"] == "1"
        assert counts["oversized_fragment_rejects"] == "2"
        assert counts["budget_rejects"] == "4"
        assert counts["max_neighborhood_cap"] == str(4096**2)
        assert 0 < int(counts["budget_boundary_keys"]) < 100_000
        assert int(counts["budget_boundary_work"]) <= 1_000_000_000

        save_audit("kernel-result.json", json.dumps({
            "scope": "Actual GeoTrellis DoubleArrayTile inputs through targetsFromTile, multi-hop emitFragments and assemble, plus pure Long transform; no SparkContext, service, or user code",
            "summary": counts,
            "kernel_case_count": fixture["kernel_case_count"],
            "source_case_count": fixture["source_case_count"],
            "source_observed_keys": fixture["source_observed_keys"],
            "source_pixels_compared": fixture["source_evaluated_pixels"],
            "declared_grid_slots": fixture["source_grid_slots"],
            "reference": "independent Python brute-force nearest-target integer-coordinate oracle with big-endian SHA-256 tile digests",
            "coverage": [
                "all three exact metrics, empty/full/sparse masks, one-dimensional and two-dimensional transforms",
                "a 65,537-cell 1-D squared-distance control whose final exact Long exceeds Int32",
                "all 16 source fixtures compared by full observed SpatialKey/SpaceTimeKey set and every tile digest/range/cap count",
                "default N=256 over all three 3x3 256x256 observed tile grids; 362,741,850 work and 18,305,280 decoded cells per plan",
                "two-tile-hop halo transfer with a missing tile, two timestamps, and time isolation",
                "negative finite, subnormal, extreme finite, positive/negative zero, and NoData input controls",
                "strict canonical wire rejection, malformed tile/fragment and oversized-group rejection before target allocation",
                "duplicate-center rejection, Int32 cap boundaries, and exact budget accept/reject limits",
            ],
            "build_seconds": build_seconds,
            "probe_seconds": probe_seconds,
            "adapter_manifest": manifest,
            "stdout": result.stdout,
        }, indent=2, sort_keys=True) + "\n")
        successful = True
    except BaseException as error:
        save_audit("failure.txt", f"{type(error).__name__}: {error}\n")
        raise
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        scratch_cleaned = not scratch.exists()
        save_audit("scratch-cleanup-readback.json", json.dumps({
            "scratch": str(scratch), "removed": scratch_cleaned,
            "result": "passed" if successful else "failed; fixture and logs retained in audit",
        }, indent=2, sort_keys=True) + "\n")
        assert scratch_cleaned, f"owned fast-distance scratch directory remains: {scratch}"
        if scratch_base_created:
            try:
                scratch_base.rmdir()
            except OSError:
                pass
