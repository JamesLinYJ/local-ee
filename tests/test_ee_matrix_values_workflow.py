"""Offline Python/JavaScript graphs and independent pixel-matrix references."""
from fractions import Fraction
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from ee_float64_graph_reference import evaluate_float64_graph
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from ee_random_split_parity import JAVASCRIPT


ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXAMPLE = ROOT / "examples/58_GEE_python_pixel_matrices.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/12_逐像元矩阵.js"
COLLECTION_ID = "sentinel-2-l2a"
ITEM_ID = "matrix-scene-v1"
SOURCE_BANDS = ["m00", "m01", "m10", "m11", "b0", "b1"]
OUTPUT_BANDS = {
    "matrix_inverse": ["row0_col0", "row0_col1", "row1_col0", "row1_col1"],
    "matrix_pseudoinverse": ["row0_col0", "row0_col1", "row1_col0", "row1_col1"],
    "matrix_solve": ["x0_rhs", "x1_rhs"],
    "inverse_reconstruction": ["row0_col0", "row0_col1", "row1_col0", "row1_col1"],
    "pseudoinverse_projection": ["row0_col0", "row0_col1", "row1_col0", "row1_col1"],
    "pseudoinverse_prediction": ["x0_rhs", "x1_rhs"],
    "float64_matrix": ["row0_col0", "row0_col1", "row1_col0", "row1_col1"],
    "float32_then_float64_matrix": ["row0_col0", "row0_col1", "row1_col0", "row1_col1"],
    "float32_then_float64_inverse": ["row0_col0", "row0_col1", "row1_col0", "row1_col1"],
    "float32_matrix": ["row0_col0", "row0_col1", "row1_col0", "row1_col1"],
    "float32_inverse": ["row0_col0", "row0_col1", "row1_col0", "row1_col1"],
}


def _evidence(name, value):
    if directory := os.environ.get("GEE_AUDIT_DIR"):
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _example():
    spec = importlib.util.spec_from_file_location("pixel_matrix_example", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _local_fixture():
    example = _example()
    catalog, items = example.declared_catalog()
    geometry = items[COLLECTION_ID][0]["geometry"]
    arrays = {ITEM_ID: {
        "m00": np.array([16_777_217, 2, 2, 2, 1], dtype=np.float64),
        "m01": np.array([0, 1, 1, 1, 0], dtype=np.float64),
        "m10": np.array([0, 4, 1, 1, 0], dtype=np.float64),
        "m11": np.array([1, 2, 3, np.nan, 1], dtype=np.float64),
        "b0": np.array([2, 5, 11, 13, np.nan], dtype=np.float64),
        "b1": np.array([3, 6, 13, 17, 19], dtype=np.float64),
    }}
    grid = np.array([[index + 0.5, 0.5] for index in range(5)], dtype=np.float64)
    return {
        "catalog": catalog,
        "items": items,
        "arrays": arrays,
        "grid": grid,
        "geometry": geometry,
    }


def _make_ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def _encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def _python_results(local):
    with OfflineGuard() as guard:
        ee = _make_ee()
        outputs = _example().build_workflow(
            ee, ee.ImageCollection(COLLECTION_ID).first(),
        )
        encoded = {name: _encode(ee, image) for name, image in outputs.items()}
        compiled = {
            name: compile_expression(expression, local["catalog"], local["items"])
            for name, expression in encoded.items()
        }
    assert guard.evidence()["attempt_count"] == 0
    return compiled, encoded


def _javascript_expressions():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for pinned JavaScript SDK serialization")
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
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["attempts"] == 0
    return result["outputs"]


def _matrix_specs(result):
    return [json.loads(node["arguments"]["spec"])
            for node in result["process_graph"].values()
            if node["process_id"] == "local_ee_matrix_values"]


def _numeric_result(result, local):
    validate(result["process_graph"])
    assert result["kind"] == "image"
    assert len(result["process_graph"]) <= 500
    values, names, timed = evaluate_float64_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries={ITEM_ID: local["geometry"]},
    )
    assert timed is False
    return values, names


def _fraction_inverse(matrix):
    a, b = map(lambda value: Fraction(str(value)), matrix[0])
    c, d = map(lambda value: Fraction(str(value)), matrix[1])
    determinant = a * d - b * c
    if determinant == 0:
        return None
    return [[d / determinant, -b / determinant],
            [-c / determinant, a / determinant]]


def _scaled_numpy_pseudoinverse(matrix):
    scale = float(np.max(np.abs(matrix)))
    if scale == 0:
        return np.zeros((matrix.shape[1], matrix.shape[0]), dtype=np.float64)
    normalized = matrix / scale
    return np.linalg.pinv(
        normalized, rcond=np.finfo(np.float64).eps * max(matrix.shape),
    ) / scale


def _expected_matrices(local):
    source = local["arrays"][ITEM_ID]
    matrices = np.stack([
        source["m00"], source["m01"], source["m10"], source["m11"],
    ]).reshape(2, 2, -1).transpose(2, 0, 1)
    right = np.stack([source["b0"], source["b1"]], axis=1)[:, :, None]
    expected = {name: np.full((len(bands), matrices.shape[0]), np.nan)
                for name, bands in OUTPUT_BANDS.items()}
    for pixel, matrix in enumerate(matrices):
        if not np.isfinite(matrix).all():
            continue
        pinverse = _scaled_numpy_pseudoinverse(matrix)
        rounded = matrix.astype(np.float32).astype(np.float64)
        expected["matrix_pseudoinverse"][:, pixel] = pinverse.reshape(-1)
        expected["pseudoinverse_projection"][:, pixel] = (pinverse @ matrix).reshape(-1)
        expected["float64_matrix"][:, pixel] = matrix.reshape(-1)
        expected["float32_then_float64_matrix"][:, pixel] = rounded.reshape(-1)
        expected["float32_matrix"][:, pixel] = rounded.astype(np.float32).astype(
            np.float64,
        ).reshape(-1)
        if np.isfinite(right[pixel]).all():
            prediction = pinverse @ right[pixel]
            expected["pseudoinverse_prediction"][:, pixel] = prediction.reshape(-1)
            expected["matrix_solve"][:, pixel] = prediction.reshape(-1)
        inverse = _fraction_inverse(matrix)
        if inverse is not None:
            inverse_float = np.asarray(inverse, dtype=np.float64)
            expected["matrix_inverse"][:, pixel] = inverse_float.reshape(-1)
            expected["inverse_reconstruction"][:, pixel] = (
                inverse_float @ matrix
            ).reshape(-1)
        if np.linalg.matrix_rank(rounded) == 2:
            expected["float32_then_float64_inverse"][:, pixel] = np.linalg.inv(rounded).reshape(-1)
            expected["float32_inverse"][:, pixel] = np.linalg.inv(rounded).astype(
                np.float32,
            ).astype(np.float64).reshape(-1)
    return expected


def test_offline_python_and_javascript_compile_the_same_dynamic_matrix_graphs():
    local = _local_fixture()
    python, encoded = _python_results(local)
    javascript = _javascript_expressions()
    assert set(javascript) == set(python) == set(OUTPUT_BANDS)
    for name, expression in javascript.items():
        compiled = compile_expression(expression, local["catalog"], local["items"])
        assert compiled == python[name], name
        assert compiled["bands"] == OUTPUT_BANDS[name]
        assert _numeric_result(compiled, local)[1] == OUTPUT_BANDS[name]
        assert compiled["source_item_ids"] == [ITEM_ID]
        assert compiled["properties"]["workflow"] == _example().SYNTHETIC_VERSION

    calls = {
        node["functionName"]
        for expression in encoded.values()
        for _key, node in expression.get("scope", [])
        if isinstance(node, dict) and node.get("type") == "Invocation"
    }
    assert {"Image.matrixInverse", "Image.matrixPseudoInverse", "Image.matrixSolve"} <= calls
    assert "Image.matrixSolve" in calls and "Image.matrixMultiply" in calls

    inverse_spec = _matrix_specs(python["matrix_inverse"])
    assert len(inverse_spec) == 1
    assert inverse_spec[0] == {
        "v": 1, "op": "inverse", "rows": 2, "cols": 2, "rhs_cols": 0,
        "operands": [{"band": index} for index in range(4)],
    }
    solve_spec = _matrix_specs(python["matrix_solve"])
    assert len(solve_spec) == 1
    assert solve_spec[0] == {
        "v": 1, "op": "solve", "rows": 2, "cols": 2, "rhs_cols": 1,
        "operands": [{"band": index} for index in range(6)],
    }
    _evidence("matrix-workflow-parity.json", {
        "outputs": list(python), "all_graphs_equal": True,
        "python_network_attempts": 0, "scope": "Declared synthetic fixture; no service or Spark",
        "graphs": python,
    })


def test_dynamic_inverse_pseudoinverse_solve_masks_and_float32_nested_cast_match_references():
    local = _local_fixture()
    compiled, _encoded = _python_results(local)
    actual = {}
    for name, result in compiled.items():
        values, names = _numeric_result(result, local)
        assert names == OUTPUT_BANDS[name]
        actual[name] = values
    expected = _expected_matrices(local)
    for name in OUTPUT_BANDS:
        np.testing.assert_allclose(
            actual[name], expected[name], rtol=3e-13, atol=3e-13, equal_nan=True,
            err_msg=name,
        )

    # Exact rational controls protect row-major order and the two hand-solvable pixels.
    inverse = _fraction_inverse([[16_777_217, 0], [0, 1]])
    assert inverse == [[Fraction(1, 16_777_217), Fraction(0)],
                       [Fraction(0), Fraction(1)]]
    assert actual["matrix_inverse"][0, 0] == pytest.approx(
        float(inverse[0][0]), rel=0, abs=1e-22,
    )
    assert actual["matrix_solve"][:, 2] == pytest.approx([4.0, 3.0], abs=2e-13)
    assert actual["pseudoinverse_projection"][:, 1] == pytest.approx(
        [Fraction(4, 5), Fraction(2, 5), Fraction(2, 5), Fraction(1, 5)],
        abs=2e-13,
    )
    assert actual["pseudoinverse_prediction"][:, 1] == pytest.approx(
        [Fraction(34, 25), Fraction(17, 25)], abs=2e-13,
    )

    # Rank deficiency masks inverse, while the minimum-norm pseudoinverse is finite.
    assert np.isnan(actual["matrix_inverse"][:, 1]).all()
    assert np.isfinite(actual["matrix_pseudoinverse"][:, 1]).all()
    # One missing A cell masks every output cell; missing B masks solve only.
    for name in ("matrix_inverse", "matrix_pseudoinverse", "matrix_solve",
                 "inverse_reconstruction", "pseudoinverse_projection",
                 "pseudoinverse_prediction"):
        assert np.isnan(actual[name][:, 3]).all()
    assert np.isfinite(actual["inverse_reconstruction"][:, 4]).all()
    assert np.isnan(actual["matrix_solve"][:, 4]).all()
    # A nested Float32 cast rounds the source value before it returns to Float64.
    assert actual["float64_matrix"][0, 0] == 16_777_217.0
    assert actual["float32_then_float64_matrix"][0, 0] == 16_777_216.0
    assert actual["float32_then_float64_inverse"][0, 0] != actual["matrix_inverse"][0, 0]
    assert actual["float32_inverse"][0, 0] == float(np.float32(1 / 16_777_216))
    _evidence("matrix-workflow-values.json", {
        name: {"valid_values": int(np.isfinite(actual[name]).sum()),
               "masked_values": int(np.isnan(actual[name]).sum()),
               "max_absolute_error": float(np.max(np.abs(
                   (actual[name] - expected[name])[np.isfinite(expected[name])])))}
        for name in OUTPUT_BANDS
    })
