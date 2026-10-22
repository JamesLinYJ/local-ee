"""Opt-in standalone GeoTrellis Image.sample kernel versus an independent grid/hash oracle."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from shapely.geometry import Point
from shapely import wkt as shapely_wkt

from scripts.build_integer_adapter import ROOT, _engine_paths, build


SCRATCH = ROOT.parents[1] / "work/gee-python-wave28-native"
AUDIT = (Path(os.environ["GEE_AUDIT_DIR"]) / "image-sample-native"
         if os.environ.get("GEE_AUDIT_DIR")
         else ROOT.parents[1] / "work/audit/gee-python-wave28-native")
FIXTURE = ROOT / "tests/fixtures/ee-image-sample-kernel-v1.json"
pytestmark = pytest.mark.skipif(
    os.environ.get("LOCAL_EE_RUN_IMAGE_SAMPLE_KERNEL_TEST") != "1",
    reason="opt-in trusted standalone Image.sample kernel; no SparkContext or service",
)
MASK64 = (1 << 64) - 1


def _mix64(value):
    value &= MASK64
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK64
    return value ^ (value >> 31)


def _grid_random(seed, col, row):
    mixed = _mix64((seed & MASK64) ^ _mix64(col + 0x9E3779B97F4A7C15)
                   ^ _mix64(row + 0xD1B54A32D192ED03))
    return (mixed >> 11) * 2.0**-53


def _roi_cells(wkt, grid):
    geometry = shapely_wkt.loads(wkt)
    cells = set()
    if geometry.geom_type in {"Point", "MultiPoint"}:
        points = [geometry] if geometry.geom_type == "Point" else list(geometry.geoms)
        for point in points:
            if grid["xmin"] <= point.x < grid["xmax"] and grid["ymin"] < point.y <= grid["ymax"]:
                col = math.floor((point.x - grid["xmin"]) / (grid["xmax"] - grid["xmin"]) * grid["columns"])
                row = math.floor((grid["ymax"] - point.y) / (grid["ymax"] - grid["ymin"]) * grid["rows"])
                cells.add((row, col))
        return cells
    cell_width = (grid["xmax"] - grid["xmin"]) / grid["columns"]
    cell_height = (grid["ymax"] - grid["ymin"]) / grid["rows"]
    for row in range(grid["rows"]):
        for col in range(grid["columns"]):
            center = Point(grid["xmin"] + (col + 0.5) * cell_width,
                           grid["ymax"] - (row + 0.5) * cell_height)
            if geometry.covers(center):
                cells.add((row, col))
    return cells


def _reference(case, fixture):
    grid, options = fixture["grid"], case["options"]
    cells = _roi_cells(case["wkt"], grid)
    population = len(cells)
    if options["factor"] is not None:
        probability = options["factor"]
    elif options["num_pixels"] is not None:
        probability = 0.0 if population == 0 else min(1.0, options["num_pixels"] / population)
    else:
        probability = 1.0
    tiles = {(tile["col"], tile["row"]): tile for tile in fixture["tiles"]}
    tile_rows, tile_cols = grid["tile_rows"], grid["tile_cols"]
    cell_width = (grid["xmax"] - grid["xmin"]) / grid["columns"]
    cell_height = (grid["ymax"] - grid["ymin"]) / grid["rows"]
    expected = []
    for row, col in sorted(cells):
        if _grid_random(options["seed"], col, row) >= probability:
            continue
        key = col // tile_cols, row // tile_rows
        tile = tiles.get(key)
        if tile is None:
            values = [None, None]
        else:
            offset = (row % tile_rows) * tile_cols + (col % tile_cols)
            values = [band[offset] for band in tile["bands"]]
        if options["drop_nulls"] and any(value is None for value in values):
            continue
        expected.append({
            "feature": 0, "row": row, "col": col,
            "x": grid["xmin"] + (col + 0.5) * cell_width,
            "y": grid["ymax"] - (row + 0.5) * cell_height,
            "values": values,
        })
    return expected


def test_actual_image_sample_kernel_matches_independent_hash_and_grid_reference():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    AUDIT.mkdir(parents=True, exist_ok=True)
    jar = SCRATCH / "local-ee-integer-adapter.jar"
    manifest = build(jar)
    java, _, compiler, runtime, _ = _engine_paths()
    classes = SCRATCH / "image-sample-classes"
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir()
    source = ROOT / "tests/fixtures/ee-image-sample-kernel-probe.scala"
    classpath = os.pathsep.join(map(str, [jar, *runtime]))
    compiled = subprocess.run(
        [str(java), "-cp", os.pathsep.join(map(str, compiler)), "scala.tools.nsc.Main",
         "-classpath", classpath, "-d", str(classes), str(source)],
        capture_output=True, text=True, timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    fixture = json.loads(FIXTURE.read_text())
    result = subprocess.run(
        [str(java), "-cp", str(classes) + os.pathsep + classpath,
         "ImageSampleKernelProbe", str(FIXTURE)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    line = next(line for line in result.stdout.splitlines()
                if line.startswith("IMAGE_SAMPLE_KERNEL_RESULT "))
    actual = json.loads(line.removeprefix("IMAGE_SAMPLE_KERNEL_RESULT "))
    assert actual["fixture_version"] == 1
    assert actual["invalid_options_rejected"] == len(fixture["invalid_options"])
    assert actual["missing_tile_present"] is True
    missing_edge = actual["missing_edge_tile"]
    assert missing_edge["actual_source_bounds"] == [0, 0, 0, 0]
    assert missing_edge["finite_tile_bounds"] == [0, 0, 2, 0]
    assert missing_edge["finite_candidate_keys"] == [[1, 0]]
    assert missing_edge["source_bounds_candidates_empty"] is True
    missing_edge_rows = json.loads(missing_edge["rows"])
    assert [(row["row"], row["col"]) for row in missing_edge_rows] == [
        (0, 2), (0, 3), (1, 2), (1, 3),
    ]
    assert all(row["values"] == [None, None] for row in missing_edge_rows)
    rows_by_name = {case["name"]: json.loads(case["rows"]) for case in actual["cases"]}
    for case in fixture["regions"]:
        rows = rows_by_name[case["name"]]
        assert rows == _reference(case, fixture)
        native_case = next(entry for entry in actual["cases"] if entry["name"] == case["name"])
        assert native_case["order_invariant"] is True
    assert len(rows_by_name["whole-finite-grid-nullable"]) == 32
    assert rows_by_name["whole-finite-grid-nullable"][0]["values"][0] == 1.0000000000000002
    assert len(rows_by_name["whole-finite-grid-drop-nulls"]) == 26
    assert rows_by_name["num-pixels-zero-empty"] == []
    assert rows_by_name["valid-geometry-outside-grid-empty"] == []

    evidence = {
        "scope": "standalone GeoTrellis pixel kernel and strict option parser; no SparkContext, HTTP service, or Google comparison",
        "adapter_jar": manifest["jar"],
        "adapter_sha256": manifest["jar_sha256"],
        "fixture": str(FIXTURE),
        "fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        "case_rows": {name: len(rows) for name, rows in rows_by_name.items()},
        "missing_edge_tile_rows": len(missing_edge_rows),
        "invalid_options_rejected": actual["invalid_options_rejected"],
        "compile_stderr": compiled.stderr,
        "probe_stdout": result.stdout,
    }
    (AUDIT / "image-sample-native-kernel.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
