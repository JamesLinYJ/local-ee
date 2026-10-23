"""Standalone actual GeoTrellis execution for compiler-emitted offset specs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

import pytest

from ee_kernel_subprocess import run_bounded
from scripts.build_integer_adapter import ROOT, _engine_paths, sha256


EXISTING_TILES = [[0, 0], [0, 1], [1, 1]]
KERNEL_WEIGHTS = [[0, 0, -3], [1, 0, 0], [2, 0, 0]]
KERNEL_OFFSETS = [[2, -1], [0, 0], [0, 1]]


@pytest.fixture(autouse=True)
def offline_only():
    from scripts.ee_python_api.offline import OfflineGuard

    with OfflineGuard() as guard:
        yield guard
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture(scope="module")
def ee():
    from gee.ee_python_client import configure_local_ee

    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def _compile_two_band_neighborhood(ee):
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.probe_cases import synthetic_inputs

    image = ee.ImageCollection("sentinel-2-l2a").first().select(["red", "nir"])
    kernel = ee.Kernel.fixed(
        width=3, height=3, weights=KERNEL_WEIGHTS,
        x=0, y=1, normalize=False,
    )
    encoded = ee.serializer.encode(
        image.neighborhoodToBands(kernel), for_cloud_api=False,
    )
    metadata, items, _ = synthetic_inputs()
    return compile_expression(encoded, [metadata], items)


def _source_bands():
    first = [float(index + 1) for index in range(64)]
    second = [float(1001 + index * 3) for index in range(64)]
    # A masked center which a downward offset must fill, plus a masked
    # neighbor which must stay NoData.
    first[2 * 8 + 2] = None
    first[3 * 8 + 1] = None
    second[1 * 8 + 3] = None
    second[3 * 8 + 2] = None
    return [first, second]


def _independent_shift(values, dx, dy):
    width = height = 8
    tile_cols = tile_rows = 4
    available = {tuple(key) for key in EXISTING_TILES}
    result = [None] * (width * height)
    for tile_col, tile_row in available:
        for local_row in range(tile_rows):
            for local_col in range(tile_cols):
                col = tile_col * tile_cols + local_col
                row = tile_row * tile_rows + local_row
                source_col, source_row = col + dx, row + dy
                if not (0 <= source_col < width and 0 <= source_row < height):
                    continue
                if (source_col // tile_cols, source_row // tile_rows) not in available:
                    continue
                result[row * width + col] = values[source_row * width + source_col]
    return result


def _native_fixture(compiled):
    bands = _source_bands()
    expected_names = [
        f"{input_name}_{dx}_{dy}"
        for input_name in ("red", "nir")
        for dx, dy in KERNEL_OFFSETS
    ]
    assert compiled["bands"] == expected_names
    focal_specs = [
        node["arguments"]["spec"]
        for node in compiled["process_graph"].values()
        if node["process_id"] == "local_ee_focal"
    ]
    assert len(focal_specs) == len(expected_names)

    outputs = []
    for output_index, (name, spec_text) in enumerate(zip(expected_names, focal_specs)):
        input_band = output_index // len(KERNEL_OFFSETS)
        spec = json.loads(spec_text)
        assert spec == {
            "iterations": 1,
            "offsets": [KERNEL_OFFSETS[output_index % len(KERNEL_OFFSETS)]],
            "operation": "mean",
            "skip_masked": False,
            "v": 1,
        }
        dx, dy = spec["offsets"][0]
        outputs.append({
            "name": name,
            "input_band": input_band,
            "spec": spec_text,
            "expected": _independent_shift(bands[input_band], dx, dy),
        })

    return {
        "width": 8,
        "height": 8,
        "tile_cols": 4,
        "tile_rows": 4,
        "existing_tiles": EXISTING_TILES,
        "input_bands": bands,
        "outputs": outputs,
    }


def test_probe_source_uses_compiled_focal_specs_and_actual_tile_kernel():
    probe = (ROOT / "tests/fixtures/ee-neighborhood-bands-probe.scala").read_text()
    assert "LocalEeFocalSpec.parse(outputCase.get(\"spec\")" in probe
    assert "LocalEeFocalNumeric.applyBufferedTile" in probe
    assert "valid red neighbor must fill a masked center" in probe
    assert "an explicitly masked neighbor must remain NoData" in probe
    assert "absent tile" in probe


def test_actual_neighborhood_band_pixels_match_independent_whole_grid_shift(ee):
    if os.environ.get("LOCAL_EE_RUN_NEIGHBORHOOD_BANDS_KERNEL_TEST") != "1":
        pytest.skip("opt-in trusted GeoTrellis shifted-pixel probe; no SparkContext, service, or user code")

    fixture = _native_fixture(_compile_two_band_neighborhood(ee))
    assert len(fixture["outputs"]) == 6
    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:10]}"
    scratch = ROOT.parent.parent / "work" / f"gee-python-wave45-neighborhood-bands-{run_id}"
    scratch.mkdir(parents=True, exist_ok=False)
    jar = scratch / "local-ee-integer-adapter.jar"
    builder = ROOT / "scripts/build_integer_adapter.py"
    audit_target = ROOT / "audit/gee-python-wave45/native/neighborhood-bands" / run_id
    audit_target.mkdir(parents=True, exist_ok=False)
    try:
        cases_path = scratch / "neighborhood-band-cases.json"
        cases_text = json.dumps(fixture, indent=2, allow_nan=False) + "\n"
        cases_path.write_text(cases_text, encoding="utf-8")
        (audit_target / "neighborhood-band-cases.json").write_text(
            cases_text, encoding="utf-8",
        )

        build = run_bounded(
            [sys.executable, str(builder), "--output", str(jar)],
            cwd=str(ROOT), timeout=240,
        )
        (audit_target / "adapter-build.stdout.txt").write_text(build.stdout, encoding="utf-8")
        (audit_target / "adapter-build.stderr.txt").write_text(build.stderr, encoding="utf-8")
        assert build.returncode == 0, build.stderr
        manifest = json.loads(build.stdout)
        assert manifest["adapter"] == "local-ee-integer-adapter"
        assert "engine/ee_focal_spec.scala" in manifest["sources"]
        assert "engine/ee_focal_numeric.scala" in manifest["sources"]
        assert "engine/ee_focal_adapter.scala" in manifest["sources"]
        assert manifest["jar_sha256"] == sha256(jar)

        java, _, compiler_tools, runtime_jars, _ = _engine_paths()
        classpath = os.pathsep.join(map(str, [jar, *runtime_jars]))
        classes = scratch / "probe-classes"
        classes.mkdir()
        probe_source = ROOT / "tests/fixtures/ee-neighborhood-bands-probe.scala"
        compile_result = run_bounded(
            [
                str(java), "-cp", os.pathsep.join(map(str, compiler_tools)),
                "scala.tools.nsc.Main", "-classpath", classpath,
                "-d", str(classes), str(probe_source),
            ],
            cwd=str(ROOT), timeout=120,
        )
        (audit_target / "probe-compile.stdout.txt").write_text(
            compile_result.stdout, encoding="utf-8",
        )
        (audit_target / "probe-compile.stderr.txt").write_text(
            compile_result.stderr, encoding="utf-8",
        )
        assert compile_result.returncode == 0, compile_result.stderr

        probe_result = run_bounded(
            [
                str(java), "-cp", str(classes) + os.pathsep + classpath,
                "local.ee.reduce.EeNeighborhoodBandsProbe", str(cases_path),
            ],
            cwd=str(ROOT), timeout=120,
        )
        (audit_target / "probe-run.stdout.txt").write_text(probe_result.stdout, encoding="utf-8")
        (audit_target / "probe-run.stderr.txt").write_text(probe_result.stderr, encoding="utf-8")
        assert probe_result.returncode == 0, probe_result.stderr
        expected = (
            "NEIGHBORHOOD_BANDS_KERNEL_OK outputs=6 compared=384 "
            "masked_center_fills=1 missing_tile_nodata=1 missing_neighbor_nodata=1"
        )
        assert expected in probe_result.stdout

        result = {
            "scope": "Standalone GeoTrellis Float64 focal tile-kernel invocation using six specs extracted from the pinned SDK compiler graph; no SparkContext, service, or user code",
            "stdout": probe_result.stdout,
            "stderr": probe_result.stderr,
            "output_count": len(fixture["outputs"]),
            "compared_pixel_count": 384,
            "probe_sha256": sha256(probe_source),
            "manifest": manifest,
            "coverage": [
                "all three nonzero cells from an asymmetric-focus signed 3x3 kernel across two input bands",
                "independent whole-grid shift references for every actual Float64 tile output",
                "masked center filled by a valid neighbor while a masked neighbor remains NoData",
                "missing upper-right source tile treated as NoData even when backing array cells contain values",
                "domain edges, source tile boundaries, and row-major compiler output specs",
            ],
            "limitations": [
                "does not run Spark RDD scheduling or the full adapter cube path",
                "does not establish sandbox, service, browser, deployment, or Google same-data acceptance",
            ],
        }
        result_path = scratch / "neighborhood-bands-result.json"
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        (audit_target / "neighborhood-bands-result.json").write_text(
            result_path.read_text(encoding="utf-8"), encoding="utf-8",
        )
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)
        if scratch.exists():
            raise RuntimeError(f"native probe scratch cleanup failed: {scratch}")
        (audit_target / "scratch-cleanup.txt").write_text(
            f"removed and confirmed absent: {scratch}\n", encoding="utf-8",
        )
