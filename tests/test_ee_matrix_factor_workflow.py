"""Offline Python/JavaScript factor graphs and independent pixel references."""
import json
import os
from pathlib import Path
import shutil

import numpy as np
import pytest

from ee_matrix_factor_workflow_helpers import (
    ITEM_ID, OUTPUT_BANDS, expected_outputs, example_module, make_ee,
    javascript_expressions, local_fixture, numeric_result, python_results,
)
from gee.ee_translate import compile_expression


def _evidence(name, value):
    if directory := os.environ.get("GEE_AUDIT_DIR"):
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _factor_specs(result):
    return [json.loads(node["arguments"]["spec"])
            for node in result["process_graph"].values()
            if node["process_id"] == "local_ee_matrix_values"]


def _sdk_calls(expressions):
    return [node for expression in expressions.values()
            for _key, node in expression.get("scope", [])
            if isinstance(node, dict) and node.get("type") == "Invocation"]


def _compile_javascript(local, expressions):
    return {
        name: compile_expression(expression, local["catalog"], local["items"])
        for name, expression in expressions.items()
    }


def test_offline_python_and_javascript_build_identical_factor_graphs():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for pinned JavaScript SDK graph parity")

    local = local_fixture()
    python_graphs, python_expressions, python_attempts = python_results(local)
    javascript, javascript_attempts = javascript_expressions()
    js_graphs = _compile_javascript(local, javascript)
    assert python_attempts == 0
    assert javascript_attempts == 0
    assert set(python_graphs) == set(javascript) == set(OUTPUT_BANDS)
    for name in OUTPUT_BANDS:
        assert python_graphs[name] == js_graphs[name], name
        assert python_graphs[name]["bands"] == OUTPUT_BANDS[name]
        assert python_graphs[name]["source_item_ids"] == [ITEM_ID]
        assert python_graphs[name]["properties"]["workflow"] == \
            example_module().SYNTHETIC_VERSION
        assert len(python_graphs[name]["process_graph"]) <= 500

    calls = _sdk_calls(python_expressions)
    factor_calls = [node for node in calls if node["functionName"] in {
        "Image.matrixCholeskyDecomposition", "Image.matrixLUDecomposition",
    }]
    assert factor_calls
    assert all(set(node["arguments"]) == {"image"} for node in factor_calls)
    assert {"Image.matrixCholeskyDecomposition", "Image.matrixLUDecomposition"} <= {
        node["functionName"] for node in factor_calls
    }
    assert {"Image.matrixTranspose", "Image.matrixMultiply", "Image.matrixSolve",
            "Image.matrixInverse"} <= {node["functionName"] for node in calls}

    # Selecting and flattening L/U/P separately must retain one shared native
    # result with logical array bands carried above its physical matrix cells.
    lu_spec = _factor_specs(python_graphs["lu_factors"])
    assert len(lu_spec) == 1
    assert lu_spec[0] == {
        "v": 1, "op": "lu", "rows": 2, "cols": 2, "rhs_cols": 0,
        "operands": [{"band": index} for index in range(4)],
    }
    cholesky_spec = _factor_specs(python_graphs["cholesky_L"])
    assert len(cholesky_spec) == 1
    assert cholesky_spec[0] == {
        "v": 1, "op": "cholesky", "rows": 2, "cols": 2, "rhs_cols": 0,
        "operands": [{"band": index} for index in range(4)],
    }
    _evidence("matrix-factors-graph-parity.json", {
        "fixture": example_module().SYNTHETIC_VERSION,
        "source_collection": "sentinel-2-l2a",
        "source_item_id": ITEM_ID,
        "source_values": "declared synthetic matrix bands; no private imagery",
        "outputs": list(python_graphs),
        "all_compiled_graphs_equal": True,
        "python_network_attempts": python_attempts,
        "javascript_network_attempts": javascript_attempts,
        "scope": "SDK serialization and local graph compilation only; no service or Spark",
    })


def test_factor_values_reconstruct_and_flow_through_bounded_inverse_and_solve_chains():
    local = local_fixture()
    compiled, _expressions, _attempts = python_results(local)
    actual = {}
    for name, result in compiled.items():
        values, names, timed = numeric_result(result, local)
        assert names == OUTPUT_BANDS[name]
        assert timed is False
        actual[name] = values

    expected = expected_outputs(local)
    metrics = {}
    for name in OUTPUT_BANDS:
        np.testing.assert_allclose(
            actual[name], expected[name], rtol=5e-13, atol=5e-300,
            equal_nan=True, err_msg=name,
        )
        np.testing.assert_array_equal(np.isnan(actual[name]), np.isnan(expected[name]))
        np.testing.assert_array_equal(np.isinf(actual[name]), np.isinf(expected[name]))
        valid = np.isfinite(expected[name])
        errors = np.abs(actual[name][valid] - expected[name][valid])
        metrics[name] = {
            "valid_values": int(valid.sum()),
            "masked_values": int(np.isnan(expected[name]).sum()),
            "float32_overflow_values": int(np.isinf(expected[name]).sum()),
            "max_absolute_error": float(errors.max()) if errors.size else 0.0,
        }

    np.testing.assert_allclose(actual["cholesky_L"][:, 1], [2, 0, 6, 1], atol=0)
    np.testing.assert_allclose(actual["cholesky_reconstruction"][:, 1],
                               [4, 12, 12, 37], atol=0)
    assert actual["lu_factors"][8:, 1].tolist() == [0, 1, 1, 0]
    np.testing.assert_allclose(actual["lu_left_product"][:, 2],
                               actual["lu_right_product"][:, 2], atol=2e-15)
    # The nested Float32 cast rounds 16,777,217 before factorization. A
    # later Double cast keeps the Float32 source rounding but computes sqrt(2)
    # at Float64 precision for the fractional SPD sample.
    assert actual["cholesky_L"][0, 0] != actual["cholesky_float32_L"][0, 0]
    assert actual["cholesky_float32_L"][0, 7] != \
        actual["cholesky_float32_then_double_L"][0, 7]

    # Invalid asymmetric, non-positive, incomplete and overflowing matrices
    # invalidate every factor cell. An RHS mask affects only the solve chain.
    for name in ("cholesky_L", "lu_factors", "lu_left_product", "lu_right_product"):
        assert np.isnan(actual[name][:, 4]).all()
    for pixel in (2, 3, 6):
        assert np.isnan(actual["cholesky_L"][:, pixel]).all()
    for pixel in (3,):
        assert np.isnan(actual["lu_factors"][:, pixel]).all()
    assert np.isfinite(actual["lu_factors"][:, 6]).all()
    assert np.isinf(actual["lu_float32_U"][3, 6])
    assert np.isfinite(actual["cholesky_L"][:, 5]).all()
    assert np.isnan(actual["cholesky_solve_from_factors"][:, 5]).all()

    # Both the selected U inverse and the complete factor inverse are actual
    # compositions; the latter has an independent Fraction check below.
    upper = actual["lu_factors"][4:8, 1].reshape(2, 2)
    np.testing.assert_allclose(actual["lu_upper_inverse"][:, 1],
                               np.linalg.inv(upper).reshape(-1),
                               rtol=3e-13, atol=3e-13)
    np.testing.assert_allclose(actual["cholesky_solve_from_factors"][:, 1], [-2, 1],
                               atol=3e-13)
    _evidence("matrix-factors-values.json", {
        "fixture": example_module().SYNTHETIC_VERSION,
        "source_item_id": ITEM_ID,
        "source_values": "declared synthetic matrix bands; no private imagery",
        "results": metrics,
        "cholesky_valid_pixels": int(np.isfinite(actual["cholesky_L"][0]).sum()),
        "lu_valid_pixels": int(np.isfinite(actual["lu_factors"][0]).sum()),
        "source_infinity_policy": "rejected before the factor reference is called",
        "scope": "independent Fraction/Decimal graph reference; no Google comparison",
    })


def test_full_lu_inverse_composition_shares_factors_and_matches_exact_inverse():
    from fractions import Fraction
    from scripts.ee_python_api.offline import OfflineGuard

    local = local_fixture()
    example = example_module()
    with OfflineGuard() as guard:
        ee = make_ee()
        expression = example.full_lu_inverse_expression(
            ee, ee.ImageCollection("sentinel-2-l2a").first(),
        ).arrayFlatten([["R0", "R1"], ["C0", "C1"]])
        result = compile_expression(
            ee.serializer.encode(expression, for_cloud_api=False),
            local["catalog"], local["items"],
        )
    assert guard.evidence()["attempt_count"] == 0
    assert len(result["process_graph"]) <= 500
    specs = _factor_specs(result)
    assert sum(spec["op"] == "lu" for spec in specs) == 1
    assert sum(spec["op"] == "inverse" for spec in specs) == 2
    actual, bands, timed = numeric_result(result, local)
    assert bands == ["R0_C0", "R0_C1", "R1_C0", "R1_C1"] and timed is False
    source = local["arrays"][ITEM_ID]
    max_error = 0.0
    for pixel in (0, 1, 2, 7):
        a, b, c, d = (Fraction.from_float(float(source[name][pixel]))
                      for name in ("m00", "m01", "m10", "m11"))
        determinant = a * d - b * c
        expected = np.array([float(d / determinant), float(-b / determinant),
                             float(-c / determinant), float(a / determinant)])
        np.testing.assert_allclose(actual[:, pixel], expected, rtol=0, atol=3e-12)
        max_error = max(max_error, float(np.max(np.abs(actual[:, pixel] - expected))))
    assert np.isnan(actual[:, 3]).all() and np.isnan(actual[:, 4]).all()
    _evidence("full-lu-inverse-wave55.json", {
        "nodes": len(result["process_graph"]), "LU_producers": 1,
        "inverse_producers": 2, "finite_values": 16, "max_absolute_error": max_error,
        "scope": "Actual SDK factor composition and independent Fraction inverse; no Spark or Google",
    })
