"""Synthetic source, offline SDK helpers and factor expectations for wave54."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np

from ee_matrix_factor_reference import factor_matrix_result
from ee_random_split_parity import JAVASCRIPT


ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXAMPLE = ROOT / "examples/59_GEE_python_matrix_factors.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/13_矩阵分解.js"
ITEM_ID = "matrix-factor-scene-v1"
OUTPUT_BANDS = {
    "cholesky_L": ["L0_C0", "L0_C1", "L1_C0", "L1_C1"],
    "cholesky_reconstruction": ["R0_C0", "R0_C1", "R1_C0", "R1_C1"],
    "cholesky_float32_L": ["L0_C0", "L0_C1", "L1_C0", "L1_C1"],
    "cholesky_float32_then_double_L": ["L0_C0", "L0_C1", "L1_C0", "L1_C1"],
    "lu_float32_U": ["U0_C0", "U0_C1", "U1_C0", "U1_C1"],
    "lu_factors": [
        "L0_C0", "L0_C1", "L1_C0", "L1_C1",
        "U0_C0", "U0_C1", "U1_C0", "U1_C1",
        "P0_C0", "P0_C1", "P1_C0", "P1_C1",
    ],
    "lu_left_product": ["R0_C0", "R0_C1", "R1_C0", "R1_C1"],
    "lu_right_product": ["R0_C0", "R0_C1", "R1_C0", "R1_C1"],
    "lu_upper_inverse": ["R0_C0", "R0_C1", "R1_C0", "R1_C1"],
    "cholesky_solve_from_factors": ["X0_rhs", "X1_rhs"],
}


def example_module():
    spec = importlib.util.spec_from_file_location("matrix_factor_example", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_fixture():
    example = example_module()
    catalog, items = example.declared_catalog()
    float32_max = float(np.finfo(np.float32).max)
    matrices = [
        [[16_777_217.0, 0.0], [0.0, 1.0]],
        [[4.0, 12.0], [12.0, 37.0]],
        [[1.0, 2.0], [3.0, 4.0]],
        [[1.0, 2.0], [2.0, 4.0]],
        [[1.0, 0.0], [0.0, np.nan]],
        [[1e30, 0.0], [0.0, 1e-30]],
        [[1.0, float32_max], [0.5, -float32_max]],
        [[2.0, 0.5], [0.5, 2.0]],
    ]
    source = {
        name: np.asarray([matrix[row][column] for matrix in matrices], dtype=np.float64)
        for name, row, column in (
            ("m00", 0, 0), ("m01", 0, 1),
            ("m10", 1, 0), ("m11", 1, 1),
        )
    }
    source["b0"] = np.asarray([1.0, 4.0, 1.0, 1.0, 1.0, np.nan, 1.0, 1.0])
    source["b1"] = np.asarray([2.0, 13.0, 2.0, 2.0, 1.0, 2.0, 1.0, 0.5])
    grid = np.asarray([[index + 0.5, 0.5] for index in range(8)], dtype=np.float64)
    geometry = items["sentinel-2-l2a"][0]["geometry"]
    return {
        "catalog": catalog, "items": items, "arrays": {ITEM_ID: source},
        "grid": grid, "geometry": geometry,
    }


def make_ee():
    from gee.ee_python_client import configure_local_ee

    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def python_results(local):
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.offline import OfflineGuard

    with OfflineGuard() as guard:
        ee = make_ee()
        outputs = example_module().build_workflow(
            ee, ee.ImageCollection("sentinel-2-l2a").first(),
        )
        encoded = {
            name: ee.serializer.encode(image, for_cloud_api=False)
            for name, image in outputs.items()
        }
        compiled = {
            name: compile_expression(expression, local["catalog"], local["items"])
            for name, expression in encoded.items()
        }
    attempts = guard.evidence()["attempt_count"]
    assert attempts == 0
    return compiled, encoded, attempts


def javascript_expressions():
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node is required for pinned JavaScript SDK graph parity")
    script = JAVASCRIPT.split("const config =", 1)[0] + f"""
const exampleSource = fs.readFileSync({json.dumps(JAVASCRIPT_EXAMPLE)}, 'utf8');
const factory = new Function('ee', exampleSource + '\\nreturn outputs;');
const outputs = factory(ee);
console.log(JSON.stringify({{
  attempts,
  outputs: Object.fromEntries(Object.entries(outputs).map(([name, value]) =>
    [name, ee.Serializer.encode(value)]))
}}));
"""
    completed = subprocess.run(
        [node, "-e", script], cwd=ROOT, capture_output=True,
        text=True, timeout=30,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    result = json.loads(completed.stdout)
    if result["attempts"] != 0:
        raise AssertionError("JavaScript SDK attempted network access")
    return result["outputs"], result["attempts"]


def numeric_result(result, local):
    from ee_float64_graph_reference import evaluate_float64_graph
    from gee.graph import validate

    validate(result["process_graph"])
    assert result["kind"] == "image"
    assert len(result["process_graph"]) <= 500
    return evaluate_float64_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries={ITEM_ID: local["geometry"]},
    )


def expected_outputs(local):
    source = local["arrays"][ITEM_ID]
    count = len(local["grid"])
    expected = {
        name: np.full((len(bands), count), np.nan, dtype=np.float64)
        for name, bands in OUTPUT_BANDS.items()
    }
    for pixel in range(count):
        matrix = np.asarray([
            [source["m00"][pixel], source["m01"][pixel]],
            [source["m10"][pixel], source["m11"][pixel]],
        ], dtype=np.float64)
        if np.isfinite(matrix).all():
            lower = factor_matrix_result("cholesky", matrix)
            if lower is not None:
                expected["cholesky_L"][:, pixel] = lower.reshape(-1)
                expected["cholesky_reconstruction"][:, pixel] = (
                    lower @ lower.T
                ).reshape(-1)
            for name, cast_output in (
                    ("cholesky_float32_L", True),
                    ("cholesky_float32_then_double_L", False)):
                cast_matrix = matrix.astype(np.float32).astype(np.float64)
                cast_lower = factor_matrix_result("cholesky", cast_matrix)
                if cast_lower is not None:
                    if cast_output:
                        cast_lower = cast_lower.astype(np.float32).astype(np.float64)
                    expected[name][:, pixel] = cast_lower.reshape(-1)

            factors = factor_matrix_result("lu", matrix)
            if factors is not None:
                lower_lu, upper, permutation = factors
                expected["lu_factors"][:, pixel] = factors.reshape(-1)
                expected["lu_left_product"][:, pixel] = (
                    permutation @ matrix
                ).reshape(-1)
                expected["lu_right_product"][:, pixel] = (
                    lower_lu @ upper
                ).reshape(-1)
                if pixel in {0, 1, 2, 7}:
                    expected["lu_upper_inverse"][:, pixel] = np.linalg.inv(
                        upper
                    ).reshape(-1)

            float32_matrix = matrix.astype(np.float32).astype(np.float64)
            float32_factors = factor_matrix_result("lu", float32_matrix)
            if float32_factors is not None:
                with np.errstate(over="ignore", invalid="ignore"):
                    expected["lu_float32_U"][:, pixel] = (
                        float32_factors[1].astype(np.float32)
                        .astype(np.float64).reshape(-1)
                    )

            rhs = np.asarray([source["b0"][pixel], source["b1"][pixel]])
            if lower is not None and np.isfinite(rhs).all() and pixel in {0, 1, 7}:
                expected["cholesky_solve_from_factors"][:, pixel] = np.linalg.solve(
                    lower.T, np.linalg.solve(lower, rhs),
                )
    return expected
