"""Column-list design assembly and multiresponse prediction with closed form."""
import importlib.util
import json
from pathlib import Path

import numpy as np
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


def load_example():
    fixture = json.loads((ROOT / "tests/fixtures/ee-list-regression-v1.json").read_text())
    spec = importlib.util.spec_from_file_location("list_regression_example",
        ROOT / "examples/14_GEE_python_list_polynomial_regression.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SYNTHETIC_VERSION == fixture["schema"]
    assert module.TIMES == fixture["times"]
    assert module.FIRST_RESPONSE == fixture["first_response"]
    assert module.SECOND_RESPONSE == fixture["second_response"]
    return fixture, module


def test_two_response_polynomial_prediction_and_orthogonal_residuals():
    fixture, example = load_example()
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        expression = example.build_prediction(ee, fixture["times"],
            fixture["first_response"], fixture["second_response"], fixture["target"])
        value = compile_expression(ee.serializer.encode(expression, for_cloud_api=False), [], {})["value"]
    assert value["rows"] == 6
    np.testing.assert_allclose(value["coefficients"], fixture["coefficients"], atol=1e-13, rtol=0)
    np.testing.assert_allclose(value["prediction"], fixture["prediction"], atol=1e-13, rtol=0)
    np.testing.assert_allclose(value["residual_rms"], np.sqrt([10/3, 40/3]), atol=1e-13, rtol=0)
    # Independent construction proves the expected least-squares minimizer:
    # residual is orthogonal to every design column, whose rank is three.
    x = np.asarray(fixture["times"])
    design = np.column_stack([np.ones(len(x)), x, x*x])
    residual = np.asarray(fixture["residual"])
    assert np.linalg.det(design.T @ design) > 0
    np.testing.assert_array_equal(design.T @ residual, [0, 0, 0])
    responses = np.column_stack([fixture["first_response"], fixture["second_response"]])
    np.testing.assert_array_equal(responses - design @ np.asarray(fixture["coefficients"]),
        np.column_stack([residual, 2*residual]))
    assert guard.evidence()["attempt_count"] == 0


def test_workflow_rejects_misaligned_columns_instead_of_silent_truncation():
    fixture, example = load_example()
    ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
    expression = example.build_prediction(ee, fixture["times"],
        fixture["first_response"][:-1], fixture["second_response"])
    assert compile_expression(ee.serializer.encode(expression, for_cloud_api=False), [], {})["value"] == {
        "error": "Input column lengths must match"}
