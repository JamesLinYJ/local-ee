"""Opt-in actual GeoTrellis tile kernel versus independent Shapely pixel intersections."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import struct
import subprocess

import numpy as np
import pytest
from shapely import transform as shapely_transform
from pyproj import Transformer
from shapely import box
from shapely import wkt as shapely_wkt

from scripts.build_integer_adapter import ROOT, _engine_paths, build


SCRATCH = Path("/Users/james/Documents/Codex/2026-10-21/wo/work/gee-python-wave24-native")
pytestmark = pytest.mark.skipif(
    os.environ.get("LOCAL_EE_RUN_SAMPLE_KERNEL_TEST") != "1",
    reason="opt-in trusted standalone GeoTrellis tile probe; no SparkContext or engine service",
)


def fixture():
    bands = [list(map(float, range(40, 52))), [100.25 + i for i in range(12)]]
    bands[1][1] = None
    cases = [{
        "xmin": 0.0, "ymin": 0.0, "xmax": 8.0, "ymax": 6.0,
        "columns": 8, "rows": 6, "tile_cols": 4, "tile_rows": 3,
        "key_col": 1, "key_row": 1, "cell_type": "float32", "bands": bands,
        "regions": [
            "POINT (4.2 2.8)",
            "MULTIPOINT ((4.2 2.8), (5 2.8), (5.2 1.2), (4.2 2.8), (8 2), (5 0))",
            "POLYGON ((5 2, 6 2, 6 1, 5 1, 5 2))",
            "POLYGON ((4.5 2, 5 2, 5 1, 4.5 1, 4.5 2))",
            "MULTIPOLYGON (((6 3, 7 3, 7 2, 6 2, 6 3)), ((7 1, 8 1, 8 0, 7 0, 7 1)))",
        ],
        "reject": False,
    }, {
        "xmin": 0.0, "ymin": 0.0, "xmax": 8.0, "ymax": 6.0,
        "columns": 8, "rows": 6, "tile_cols": 4, "tile_rows": 3,
        "key_col": 1, "key_row": 1, "cell_type": "float64",
        "bands": [[40.0, 41.0, "Infinity"] + [43.0 + i for i in range(9)]],
        "regions": ["POINT (6.2 2.8)"], "reject": True,
    }, {
        "xmin": 0.0, "ymin": 0.0, "xmax": 32.0, "ymax": 32.0,
        "columns": 32, "rows": 32, "tile_cols": 32, "tile_rows": 32,
        "key_col": 0, "key_row": 0, "cell_type": "float64",
        "bands": [list(map(float, range(1024)))],
        "regions": ["POLYGON ((0 32, 32 32, 32 0, 0 0, 0 32))"], "reject": True,
    }, {
        "xmin": 0.0, "ymin": 0.0, "xmax": 40.0, "ymax": 25.0,
        "columns": 40, "rows": 25, "tile_cols": 40, "tile_rows": 25,
        "key_col": 0, "key_row": 0, "cell_type": "float64",
        "bands": [[1.7976931348623157e308] * 1000 for _ in range(64)],
        "regions": ["POLYGON ((0 25, 40 25, 40 0, 0 0, 0 25))"], "reject": True,
    }, {
        "xmin": 0.0, "ymin": 0.0, "xmax": 8000000.0, "ymax": 6000000.0,
        "columns": 8, "rows": 6, "tile_cols": 4, "tile_rows": 3,
        "key_col": 1, "key_row": 1, "epsg": 3857, "cell_type": "float32",
        "bands": bands,
        "regions": [
            "POINT (45 20)",
            "MULTIPOINT ((45 20), (50 20), (60 10), (45 20), (80 10), (60 0))",
            "POLYGON ((46 20, 54 20, 54 10, 46 10, 46 20))",
            "POLYGON ((55 15, 60 15, 60 10, 55 10, 55 15))",
        ],
        "reject": False,
    }]
    return {
        "cases": cases,
        "invalid_wkts": [
            "LINESTRING (0 0, 1 1)",
            "POLYGON ((0 0, 1 1, 1 0, 0 1, 0 0))",
            "POINT (181 0)",
            "POINT Z (0 0 1)",
        ],
    }


def oracle(case):
    """Independent WKT parsing, raster-cell intersections and mask rules via Shapely."""
    width, height = case["tile_cols"], case["tile_rows"]
    first_col, first_row = case["key_col"] * width, case["key_row"] * height
    cell_w = (case["xmax"] - case["xmin"]) / case["columns"]
    cell_h = (case["ymax"] - case["ymin"]) / case["rows"]
    epsg = case.get("epsg", 4326)
    to_source = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    to_wgs84 = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    expected = []
    for feature_index, text in enumerate(case["regions"]):
        def project(coordinates):
            x, y = to_source.transform(coordinates[:, 0], coordinates[:, 1])
            return np.column_stack((x, y))

        geometry = shapely_transform(shapely_wkt.loads(text), project, include_z=False)
        points = []
        if geometry.geom_type == "Point":
            points = [geometry]
        elif geometry.geom_type == "MultiPoint":
            points = list(geometry.geoms)
        if points:
            selected = set()
            for point in points:
                if (case["xmin"] <= point.x < case["xmax"] and
                    case["ymin"] < point.y <= case["ymax"]):
                    col = math.floor((point.x - case["xmin"]) / cell_w)
                    row = math.floor((case["ymax"] - point.y) / cell_h)
                    selected.add((row, col))
        else:
            selected = set()
            for row in range(case["rows"]):
                for col in range(case["columns"]):
                    left = case["xmin"] + col * cell_w
                    right = left + cell_w
                    top = case["ymax"] - row * cell_h
                    bottom = top - cell_h
                    if geometry.intersection(box(left, bottom, right, top)).area > 0:
                        selected.add((row, col))
        for row, col in sorted(selected):
            local_row, local_col = row - first_row, col - first_col
            if 0 <= local_row < height and 0 <= local_col < width:
                index = local_row * width + local_col
                values = [None if band[index] is None else float(band[index])
                          for band in case["bands"]]
                if any(value is None for value in values):
                    continue
                if any(not math.isfinite(value) for value in values):
                    raise ValueError("sampled valid pixel is non-finite")
                if case["cell_type"] == "float32":
                    values = [struct.unpack("!f", struct.pack("!f", value))[0]
                              for value in values]
                expected.append({
                    "feature": feature_index, "row": row, "col": col,
                    "x": to_wgs84.transform(case["xmin"] + (col + 0.5) * cell_w,
                                            case["ymax"] - (row + 0.5) * cell_h)[0],
                    "y": to_wgs84.transform(case["xmin"] + (col + 0.5) * cell_w,
                                            case["ymax"] - (row + 0.5) * cell_h)[1],
                    "values": values,
                })
    expected.sort(key=lambda row: (row["feature"], row["row"], row["col"]))
    if len(expected) > 1000:
        raise ValueError("sample result row limit exceeded")
    if len(json.dumps(expected, separators=(",", ":"), allow_nan=False).encode("utf-8")) > 1000000:
        raise ValueError("sample response byte limit exceeded")
    return expected


def test_actual_native_tile_kernel_matches_shapely_oracle():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    jar = SCRATCH / "local-ee-integer-adapter.jar"
    build(jar)
    java, _, compiler, runtime, _ = _engine_paths()
    classes = SCRATCH / "sample-kernel-classes"
    classes.mkdir(parents=True, exist_ok=True)
    source = ROOT / "tests/fixtures/ee-sample-kernel-probe.scala"
    classpath = os.pathsep.join(map(str, [jar, *runtime]))
    compile_command = [str(java), "-cp", os.pathsep.join(map(str, compiler)),
                       "scala.tools.nsc.Main", "-classpath", classpath,
                       "-d", str(classes), str(source)]
    compiled = subprocess.run(compile_command, capture_output=True, text=True, timeout=120)
    assert compiled.returncode == 0, compiled.stderr

    data = fixture()
    data['cases'].append({
        'xmin': 0.0, 'ymin': 0.0, 'xmax': 1.0, 'ymax': 1.0,
        'columns': 1, 'rows': 1, 'tile_cols': 1, 'tile_rows': 1,
        'key_col': 0, 'key_row': 0, 'cell_type': 'float64',
        'bands': [[1.0000000000000002], [0.1]],
        'regions': ['POINT (0.5 0.5)'], 'reject': False,
    })
    fixture_path = SCRATCH / "sample-kernel-cases.json"
    fixture_path.write_text(json.dumps(data, allow_nan=False))
    result = subprocess.run([str(java), "-cp", str(classes) + os.pathsep + classpath,
                             "SampleKernelProbe", str(fixture_path)],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    line = next(line for line in result.stdout.splitlines()
                if line.startswith("SAMPLE_KERNEL_RESULT "))
    actual = json.loads(line.removeprefix("SAMPLE_KERNEL_RESULT "))
    if os.environ.get('GEE_AUDIT_DIR'):
        target = Path(os.environ['GEE_AUDIT_DIR'])
        target.mkdir(parents=True, exist_ok=True)
        (target / 'sample-kernel-cases.json').write_text(json.dumps(data, indent=2) + '\n')
        (target / 'sample-kernel.json').write_text(json.dumps(actual, indent=2) + '\n')
    assert actual["invalid_wkt_count"] == len(data["invalid_wkts"])
    assert actual["tile_edge_candidate_count"] == 2
    forward = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    expected_projected = forward.transform(1.0, 1.0)
    assert actual["projected_point"][0] == pytest.approx(expected_projected[0], rel=1e-9)
    assert actual["projected_point"][1] == pytest.approx(expected_projected[1], rel=1e-9)

    for case, native in zip(data["cases"], actual["cases"]):
        if case["reject"]:
            with pytest.raises(ValueError):
                oracle(case)
            assert native["rejected"] is True
        else:
            assert native["rejected"] is False
            actual_rows = json.loads(native["rows"])
            expected_rows = oracle(case)
            assert len(actual_rows) == len(expected_rows)
            for actual_row, expected_row in zip(actual_rows, expected_rows):
                for field in ("feature", "row", "col", "values"):
                    assert actual_row[field] == expected_row[field]
                assert actual_row["x"] == pytest.approx(expected_row["x"], abs=1e-9)
                assert actual_row["y"] == pytest.approx(expected_row["y"], abs=1e-9)
