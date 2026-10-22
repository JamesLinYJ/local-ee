"""SDK-to-compiler synthetic unmixing workflow and independent rational checks."""
from copy import deepcopy
from fractions import Fraction
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "examples/17_GEE_python_matrix_unmixing.py"


def fixture():
    return json.loads((ROOT / "tests/fixtures/ee-matrix-unmixing-v1.json").read_text())


def load_example():
    spec = importlib.util.spec_from_file_location("matrix_unmixing_example", EXAMPLE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def output(ee, value):
    return compile_expression(encode(ee, value), [], {})["value"]


def invocation_names(expression):
    return {
        node.get("functionName")
        for _, node in expression.get("scope", [])
        if isinstance(node, dict) and node.get("type") == "Invocation"
    }


def add_unknown_argument(expression, name):
    result = deepcopy(expression)
    for _, node in result.get("scope", []):
        if isinstance(node, dict) and node.get("functionName") == name:
            node["arguments"]["unexpected"] = 1
            return result
    raise AssertionError(f"Missing serialized invocation {name}")


def rational_matrix(values):
    return [[Fraction(str(value)) for value in row] for row in values]


def test_real_sdk_dictionary_array_qr_lu_svd_pipeline_is_offline_and_numerically_correct():
    data = fixture()
    example = load_example()
    assert example.SYNTHETIC_VERSION == data["schema"]

    with OfflineGuard() as guard:
        ee = make_ee()
        expression = example.build_unmixing(ee, data["mixing_matrix"], data["observations"])
        encoded = encode(ee, expression)
        value = compile_expression(encoded, [], {})["value"]

    assert guard.evidence()["attempt_count"] == 0
    assert set(value) == {"observations", "qr", "lu", "svd"}
    assert isinstance(value["observations"], list)
    assert isinstance(value["qr"]["abundances"], list)
    assert {"Array.matrixQRDecomposition", "Array.matrixLUDecomposition",
            "Array.matrixSingularValueDecomposition", "Dictionary.get",
            "Array.matrixMultiply", "Array.matrixSolve", "Array.get"} <= invocation_names(encoded)

    mixing = np.asarray(data["mixing_matrix"], dtype=float)
    observations = np.asarray(data["observations"], dtype=float)
    expected = rational_matrix(data["true_abundances"])
    noisy_expected = [
        Fraction("0.4") + Fraction(7, 360),
        Fraction("0.4") - Fraction(13, 360),
        Fraction("0.2") + Fraction(1, 60),
    ]
    for row, number in enumerate(noisy_expected):
        expected[row][data["noise"]["sample_index"]] = number
    expected_float = np.asarray([[float(value) for value in row] for row in expected])

    for method in ("qr", "lu", "svd"):
        result = value[method]
        abundance = np.asarray(result["abundances"], dtype=float)
        reconstruction = np.asarray(result["reconstruction"], dtype=float)
        np.testing.assert_allclose(abundance, expected_float, atol=3e-13, rtol=0)
        np.testing.assert_allclose(reconstruction, observations, atol=3e-13, rtol=0)
        np.testing.assert_allclose(result["factorization_residual"], 0, atol=3e-13, rtol=0)

    assert value["qr"]["noisy_sample_component_0"] == pytest.approx(
        float(noisy_expected[0]), abs=3e-13
    )
    np.testing.assert_allclose(value["lu"]["P"] @ mixing,
                               np.asarray(value["lu"]["L"]) @ np.asarray(value["lu"]["U"]),
                               atol=3e-13, rtol=0)
    u, singular, v = (np.asarray(value["svd"][key]) for key in ("U", "S", "V"))
    np.testing.assert_allclose(u.T @ u, np.eye(3), atol=3e-13, rtol=0)
    np.testing.assert_allclose(v.T @ v, np.eye(3), atol=3e-13, rtol=0)
    np.testing.assert_allclose(u @ singular @ v.T, mixing, atol=3e-13, rtol=0)
    # The public compiler result is genuine nested JSON data, not StaticArray IR.
    json.dumps(value, allow_nan=False)


def test_fixture_observations_and_noisy_solution_follow_exact_fraction_reference():
    data = fixture()
    mixing = rational_matrix(data["mixing_matrix"])
    truth = rational_matrix(data["true_abundances"])
    observations = rational_matrix(data["observations"])
    assert all(value > 0 for row in mixing for value in row)
    assert sum(mixing[row][column] * mixing[row][column]
               for row in range(3) for column in range(3)) > 0
    assert sum(mixing[row][0] * mixing[row][1] for row in range(3)) > 0
    assert all(sum(truth[row][sample] for row in range(3)) == 1 for sample in range(4))
    determinant = (
        mixing[0][0] * (mixing[1][1] * mixing[2][2] - mixing[1][2] * mixing[2][1])
        - mixing[0][1] * (mixing[1][0] * mixing[2][2] - mixing[1][2] * mixing[2][0])
        + mixing[0][2] * (mixing[1][0] * mixing[2][1] - mixing[1][1] * mixing[2][0])
    )
    assert determinant == Fraction(9, 25)
    assert str(determinant) == data["independent_reference"]["determinant"]
    for band in range(3):
        for sample in range(4):
            predicted = sum(mixing[band][component] * truth[component][sample]
                            for component in range(3))
            if sample == data["noise"]["sample_index"]:
                predicted += Fraction(str(data["noise"]["additive_by_band"][band]))
            assert observations[band][sample] == predicted

    inverse = rational_matrix([
        [Fraction(47, 36), Fraction(-13, 36), Fraction(-1, 12)],
        [Fraction(-5, 36), Fraction(55, 36), Fraction(-5, 12)],
        [Fraction(-1, 6), Fraction(-1, 6), Fraction(3, 2)],
    ])
    assert [[str(value) for value in row] for row in inverse] == data[
        "independent_reference"]["inverse_mixing_matrix"]
    for row in range(3):
        for column in range(3):
            assert sum(mixing[row][index] * inverse[index][column] for index in range(3)) == int(
                row == column
            )
    noise = [Fraction(1, 100), Fraction(-2, 100), Fraction(1, 100)]
    delta = [sum(inverse[row][column] * noise[column] for column in range(3))
             for row in range(3)]
    assert delta == [Fraction(7, 360), Fraction(-13, 360), Fraction(1, 60)]
    assert [str(value) for value in delta] == data["independent_reference"]["noise_abundance_delta"]
    assert [str(truth[row][3] + delta[row]) for row in range(3)] == data[
        "independent_reference"]["noisy_sample_abundances"]


def test_lu_rejects_exact_zero_pivot_and_decompositions_require_square_matrices():
    ee = make_ee()
    with pytest.raises(UnsupportedEEError, match="zero pivot"):
        output(ee, ee.Array([[1, 2], [2, 4]]).matrixLUDecomposition())
    nonsquare = ee.Array([[1, 2, 3], [4, 5, 6]])
    for method in ("matrixQRDecomposition", "matrixLUDecomposition",
                   "matrixSingularValueDecomposition"):
        with pytest.raises(UnsupportedEEError, match="square matrix"):
            output(ee, getattr(nonsquare, method)())


def test_unknown_decomposition_arguments_and_shared_work_budget_are_rejected():
    ee = make_ee()
    encoded = encode(ee, ee.Array([[1, 0], [0, 1]]).matrixQRDecomposition())
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(add_unknown_argument(encoded, "Array.matrixQRDecomposition"), [], {})

    matrix = ee.Array(np.eye(18).tolist())
    repeated = ee.Dictionary({
        "first": matrix.matrixQRDecomposition(),
        "second": matrix.matrixQRDecomposition(),
    })
    with pytest.raises(UnsupportedEEError, match="work budget"):
        output(ee, repeated)
