"""Strict wire and resource boundaries for static matrix factorizations."""
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_core import StaticArray
from gee.compat.earthengine.array_decompositions import invoke_decomposition
from gee.compat.earthengine.decoder import Translator
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
METHODS = (
    "matrixQRDecomposition",
    "matrixLUDecomposition",
    "matrixSingularValueDecomposition",
)
ALGORITHMS = {
    "matrixQRDecomposition": "Array.matrixQRDecomposition",
    "matrixLUDecomposition": "Array.matrixLUDecomposition",
    "matrixSingularValueDecomposition": "Array.matrixSingularValueDecomposition",
}


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def output(ee, value):
    encoded = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(encoded, [], {})["value"]


def invocation(name, arguments):
    return {"type": "Invocation", "functionName": name, "arguments": arguments}


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("scalar", [7, -7])
def test_one_by_one_positive_and_negative_inputs_preserve_each_factorization(ee, method, scalar):
    source = np.array([[scalar]], dtype=float)
    factors = output(ee, getattr(ee.Array([[scalar]]), method)())
    if method == "matrixQRDecomposition":
        left, right = np.asarray(factors["Q"]), np.asarray(factors["R"])
        np.testing.assert_allclose(left.T @ left, [[1]], atol=1e-15)
        np.testing.assert_allclose(left @ right, source, atol=1e-15)
    elif method == "matrixLUDecomposition":
        left, right, permutation = (np.asarray(factors[key]) for key in ("L", "U", "P"))
        np.testing.assert_array_equal(left, [[1]])
        np.testing.assert_array_equal(permutation, [[1]])
        np.testing.assert_array_equal(right, source)
        np.testing.assert_array_equal(permutation @ source, left @ right)
    else:
        left, singular, right = (np.asarray(factors[key]) for key in ("U", "S", "V"))
        np.testing.assert_allclose(left.T @ left, [[1]], atol=1e-15)
        np.testing.assert_allclose(right.T @ right, [[1]], atol=1e-15)
        np.testing.assert_allclose(singular, [[abs(scalar)]], atol=1e-15)
        np.testing.assert_allclose(left @ singular @ right.T, source, atol=1e-15)


@pytest.mark.parametrize("method", METHODS)
def test_required_argument_unknown_argument_and_wrong_key_are_rejected(ee, method):
    algorithm = ALGORITHMS[method]
    with pytest.raises(UnsupportedEEError):
        compile_expression(invocation(algorithm, {}), [], {})
    with pytest.raises(UnsupportedEEError):
        compile_expression(invocation(algorithm, {"input": [[1, 0], [0, 1]]}), [], {})
    with pytest.raises(UnsupportedEEError):
        compile_expression(invocation(algorithm, {
            "array": ee.serializer.encode(ee.Array([[1, 0], [0, 1]]), for_cloud_api=False),
            "ignored": 1,
        }), [], {})


@pytest.mark.parametrize("method", METHODS)
def test_raw_lists_scalars_strings_and_rasters_are_not_promoted_to_static_arrays(ee, method):
    algorithm = ALGORITHMS[method]
    for value in ([[1, 0], [0, 1]], 3, "matrix", True):
        with pytest.raises(UnsupportedEEError):
            compile_expression(invocation(algorithm, {"array": value}), [], {})

    # Array's documented input kind is Array; a real SDK Image must not be
    # confused with its static pixel/list representation by this code path.
    raster_expression = ee.serializer.encode(ee.Image.constant(3), for_cloud_api=False)
    with pytest.raises(UnsupportedEEError):
        compile_expression(invocation(algorithm, {"array": raster_expression}), [], {})


@pytest.mark.parametrize("method", METHODS)
def test_rank_nonsquare_empty_boolean_and_nonfinite_inputs_reject(ee, method):
    for values in ([1, 2], [[1, 2, 3], [4, 5, 6]]):
        with pytest.raises(UnsupportedEEError):
            output(ee, getattr(ee.Array(values), method)())

    # The pinned SDK can serialize an empty Array expression, but the static
    # compiler deliberately cannot infer an empty array's element type.
    with pytest.raises(UnsupportedEEError):
        output(ee, getattr(ee.Array([]), method)())
    with pytest.raises(UnsupportedEEError):
        output(ee, getattr(ee.Array([[True]]), method)())
    with pytest.raises(UnsupportedEEError):
        output(ee, getattr(ee.Array([[float("inf")]]), method)())


def test_explicit_pixel_type_array_constructor_is_not_silently_cast(ee):
    expression = invocation("Array.matrixQRDecomposition", {
        "array": invocation("Array", {"values": [[1]], "pixelType": "int8"}),
    })
    with pytest.raises(UnsupportedEEError):
        compile_expression(expression, [], {})


@pytest.mark.parametrize("method", METHODS)
def test_lu_rejects_exact_zero_pivot_while_other_factorizations_handle_singular_matrix(ee, method):
    value = getattr(ee.Array([[1, 2], [2, 4]]), method)()
    if method == "matrixLUDecomposition":
        with pytest.raises(UnsupportedEEError, match="zero pivot"):
            output(ee, value)
    else:
        factors = output(ee, value)
        if method == "matrixQRDecomposition":
            reconstructed = np.asarray(factors["Q"]) @ np.asarray(factors["R"])
        else:
            reconstructed = (np.asarray(factors["U"]) @ np.asarray(factors["S"])
                             @ np.asarray(factors["V"]).T)
        np.testing.assert_allclose(reconstructed, [[1, 2], [2, 4]], atol=2e-14)


@pytest.mark.parametrize("method,matrix", [
    ("matrixQRDecomposition", [[1e308, 1e308], [1e308, 1e308]]),
    ("matrixSingularValueDecomposition", [[1e308, 1e308], [1e308, 1e308]]),
])
def test_finite_input_that_overflows_a_computed_factor_is_rejected(ee, method, matrix):
    with pytest.raises(UnsupportedEEError, match="finite"):
        output(ee, getattr(ee.Array(matrix), method)())


@pytest.mark.parametrize("method,n", [
    ("matrixQRDecomposition", 71),
    ("matrixLUDecomposition", 58),
    ("matrixSingularValueDecomposition", 58),
])
def test_combined_factor_output_cell_limit_is_checked_before_factorization(ee, method, n,
                                                                          monkeypatch):
    def should_not_run(*_args, **_kwargs):
        raise AssertionError("factorization ran before output-cell preflight")

    monkeypatch.setattr(np.linalg, "qr", should_not_run)
    monkeypatch.setattr(np.linalg, "svd", should_not_run)
    values = np.eye(n).tolist()
    with pytest.raises(UnsupportedEEError, match="combined result exceeds 10000 cells"):
        output(ee, getattr(ee.Array(values), method)())


@pytest.mark.parametrize("method,n", [
    ("matrixQRDecomposition", 23),
    ("matrixLUDecomposition", 29),
    ("matrixSingularValueDecomposition", 19),
])
def test_shared_factorization_work_budget_precedes_numpy_calls(ee, method, n, monkeypatch):
    def should_not_run(*_args, **_kwargs):
        raise AssertionError("factorization ran before work-budget preflight")

    monkeypatch.setattr(np.linalg, "qr", should_not_run)
    monkeypatch.setattr(np.linalg, "svd", should_not_run)
    values = np.eye(n).tolist()
    with pytest.raises(UnsupportedEEError, match="work budget"):
        output(ee, getattr(ee.Array(values), method)())


def test_factorization_keeps_the_input_untouched_and_returns_readonly_arrays():
    original = np.array([[12.0, -51.0, 4.0], [6.0, 167.0, -68.0], [-4.0, 24.0, -41.0]])
    before = original.copy()
    original.setflags(write=False)
    source = StaticArray(original)
    result = invoke_decomposition(Translator([], {}, {}), "Array.matrixQRDecomposition",
                                  {"array": source})
    np.testing.assert_array_equal(original, before)
    assert not source.data.flags.writeable
    for factor in result.values():
        assert isinstance(factor, StaticArray)
        assert not factor.data.flags.writeable
        with pytest.raises(ValueError):
            factor.data[0, 0] = 10


def test_preexisting_compilation_work_is_charged_before_factorization(monkeypatch):
    def should_not_run(*_args, **_kwargs):
        raise AssertionError("factorization ran before shared-work preflight")

    monkeypatch.setattr(np.linalg, "qr", should_not_run)
    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_decomposition(translator, "Array.matrixQRDecomposition", {
            "array": StaticArray(np.array([[1.0]])),
        })
    assert translator.steps == 49_999
