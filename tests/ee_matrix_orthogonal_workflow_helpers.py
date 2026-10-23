"""Synthetic, offline SDK and numeric helpers for wave55 QR/SVD workflows."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

import numpy as np

from ee_random_split_parity import JAVASCRIPT


ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXAMPLE = ROOT / "examples/60_GEE_python_matrix_orthogonal.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/14_矩阵正交分解.js"
ITEM_ID = "matrix-orthogonal-scene-v1"
OUTPUT_BANDS = {
    "qr_tall_q": [f"r{row}_c{column}" for row in range(3) for column in range(2)],
    "qr_tall_r": [f"r{row}_c{column}" for row in range(2) for column in range(2)],
    "qr_tall_reconstruction": [f"r{row}_c{column}" for row in range(3) for column in range(2)],
    "qr_tall_projection": [f"r{row}_value" for row in range(3)],
    "qr_tall_least_squares": [f"c{row}_value" for row in range(2)],
    "qr_tall_fit": [f"r{row}_value" for row in range(3)],
    "svd_tall_u": [f"r{row}_k{column}" for row in range(3) for column in range(2)],
    "svd_tall_s": [f"k{row}_k{column}" for row in range(2) for column in range(2)],
    "svd_tall_v": [f"c{row}_k{column}" for row in range(2) for column in range(2)],
    "svd_tall_rank1": [f"r{row}_c{column}" for row in range(3) for column in range(2)],
    "svd_tall_reconstruction": [f"r{row}_c{column}" for row in range(3) for column in range(2)],
    "svd_tall_rank2": [f"r{row}_c{column}" for row in range(3) for column in range(2)],
    "svd_square_u": [f"r{row}_k{column}" for row in range(2) for column in range(2)],
    "svd_square_s": [f"k{row}_k{column}" for row in range(2) for column in range(2)],
    "svd_square_v": [f"c{row}_k{column}" for row in range(2) for column in range(2)],
    "svd_square_reconstruction": [f"r{row}_c{column}" for row in range(2) for column in range(2)],
    "svd_square_rank1": [f"r{row}_c{column}" for row in range(2) for column in range(2)],
    "svd_square_rank2": [f"r{row}_c{column}" for row in range(2) for column in range(2)],
    "qr_wide_q": [f"r{row}_c{column}" for row in range(2) for column in range(2)],
    "qr_wide_r": [f"r{row}_c{column}" for row in range(2) for column in range(3)],
    "qr_wide_reconstruction": [f"r{row}_c{column}" for row in range(2) for column in range(3)],
    "svd_wide_u": [f"r{row}_k{column}" for row in range(2) for column in range(2)],
    "svd_wide_s": [f"k{row}_k{column}" for row in range(2) for column in range(2)],
    "svd_wide_v": [f"c{row}_k{column}" for row in range(3) for column in range(2)],
    "svd_wide_rank1": [f"r{row}_c{column}" for row in range(2) for column in range(3)],
    "svd_wide_reconstruction": [f"r{row}_c{column}" for row in range(2) for column in range(3)],
    "svd_wide_rank2": [f"r{row}_c{column}" for row in range(2) for column in range(3)],
    "svd_truncation_u": [f"r{row}_k{column}" for row in range(3) for column in range(3)],
    "svd_truncation_s": [f"k{row}_k{column}" for row in range(3) for column in range(3)],
    "svd_truncation_v": [f"c{row}_k{column}" for row in range(3) for column in range(3)],
    "qr_float32_then_double_reconstruction": [
        f"r{row}_c{column}" for row in range(3) for column in range(2)
    ],
    "svd_float32_then_double_reconstruction": [
        f"r{row}_c{column}" for row in range(3) for column in range(2)
    ],
}


def example_module():
    spec = importlib.util.spec_from_file_location("matrix_orthogonal_example", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_fixture():
    example = example_module()
    catalog, items = example.declared_catalog()
    matrices = [
        [[1.0, 2.0], [3.0, 4.0], [5.0, 7.0]],
        [[1.0, 2.0], [2.0, 4.0], [3.0, 6.0]],
        [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]],
        [[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]],
        [[1.0, 0.0], [0.0, 0.0], [0.0, 0.0]],
        [[1.0, 2.0], [np.nan, 4.0], [5.0, 7.0]],
        [[16_777_217.0, 1.0], [2.0, 3.0], [4.0, 5.0]],
        [[2.0, -3.0], [4.0, 6.0], [1.0, 9.0]],
        [[1.0, 0.0], [0.0, 1e-20], [0.0, 0.0]],
        [[1.0, 1.0], [1.0, 1.0 + 2.0**-20], [2.0, 2.0]],
        [[0.0, 1.0], [0.0, 2.0], [0.0, 3.0]],
        [[1.0, -1.0], [-2.0, 3.0], [4.0, 5.0]],
    ]
    source = {
        f"a{row}{column}": np.asarray(
            [matrix[row][column] for matrix in matrices], dtype=np.float64,
        )
        for row in range(3) for column in range(2)
    }
    source.update({
        "b0": np.asarray([1.0, 0.0, 2.0, 1.0, 3.0, -1.0, 4.0, 1.0, 0.5, 2.0, -2.0, 3.0]),
        "b1": np.asarray([2.0, 1.0, -1.0, 0.0, 1.0, 3.0, -2.0, 4.0, 0.0, -1.0, 2.0, 1.0]),
        "b2": np.asarray([-1.0, 4.0, 3.0, 2.0, -2.0, 1.0, 1.0, 0.0, 1.0, 3.0, 5.0, -2.0]),
    })
    grid = np.asarray([[index + 0.5, 0.5] for index in range(len(matrices))], dtype=np.float64)
    geometry = items["sentinel-2-l2a"][0]["geometry"]
    return {
        "catalog": catalog, "items": items, "arrays": {ITEM_ID: source},
        "grid": grid, "geometry": geometry,
        "matrices": np.asarray(matrices, dtype=np.float64),
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


def record_evidence(name, value):
    if directory := os.environ.get("GEE_AUDIT_DIR"):
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"matrix-orthogonal-{name}-{os.getpid()}-{uuid.uuid4().hex}.json"
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def decoded_values(compiled, local):
    result = {}
    for name, graph in compiled.items():
        values, bands, timed = numeric_result(graph, local)
        assert bands == OUTPUT_BANDS[name]
        assert timed is False
        result[name] = values
    return result


def matrix_output(values, name, pixel, shape):
    return values[name][:, pixel].reshape(shape)


def assert_svd(values, prefix, matrix, pixel, u_shape, v_shape):
    u = matrix_output(values, f"svd_{prefix}_u", pixel, u_shape)
    singular = matrix_output(values, f"svd_{prefix}_s", pixel, (2, 2))
    v = matrix_output(values, f"svd_{prefix}_v", pixel, v_shape)
    assert np.isfinite(u).all() and np.isfinite(singular).all() and np.isfinite(v).all()
    np.testing.assert_allclose(u.T @ u, np.eye(2), rtol=0, atol=3e-12)
    np.testing.assert_allclose(v.T @ v, np.eye(2), rtol=0, atol=3e-12)
    np.testing.assert_allclose(singular, np.diag(np.diag(singular)), rtol=0, atol=2e-14)
    spectrum = np.diag(singular)
    assert np.all(spectrum >= 0.0)
    assert spectrum[0] >= spectrum[1]

    reconstructed = u @ singular @ v.T
    np.testing.assert_allclose(
        reconstructed, matrix, rtol=2e-10, atol=2e-10,
        err_msg=f"{prefix} SVD reconstruction at pixel {pixel}",
    )
    rank1 = u[:, :1] @ singular[:1, :1] @ v[:, :1].T
    np.testing.assert_allclose(
        matrix_output(values, f"svd_{prefix}_rank1", pixel, matrix.shape),
        rank1, rtol=2e-10, atol=2e-10,
    )
    return spectrum


def matrices_for_pixel(local, *, wide=False, float32_then_double=False):
    matrices = local["matrices"]
    if float32_then_double:
        matrices = matrices.astype(np.float32).astype(np.float64)
    if wide:
        matrices = np.swapaxes(matrices, 1, 2)
    return matrices


def budget_limited_outputs(ee):
    return example_module().build_budget_limited_compositions(
        ee, ee.ImageCollection("sentinel-2-l2a").first(),
    )
