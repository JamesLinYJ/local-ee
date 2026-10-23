"""Rectangular static QR/SVD factors retain compact shape and bounded work."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_core import MAX_ARRAY_WORK, StaticArray
from gee.compat.earthengine.array_decompositions import invoke_decomposition
from gee.compat.earthengine.decoder import Translator
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


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


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def output(ee, value):
    return compile_expression(encode(ee, value), [], {})["value"]


def _check_qr(source, factors):
    rows, cols = source.shape
    rank = min(rows, cols)
    q, r = (np.asarray(factors[key]) for key in ("Q", "R"))
    assert q.shape == (rows, rank)
    assert r.shape == (rank, cols)
    np.testing.assert_allclose(q.T @ q, np.eye(rank), atol=4e-14, rtol=4e-14)
    np.testing.assert_allclose(q @ r, source, atol=4e-13, rtol=4e-14)


def _check_svd(source, factors):
    rows, cols = source.shape
    rank = min(rows, cols)
    u, s, v = (np.asarray(factors[key]) for key in ("U", "S", "V"))
    assert u.shape == (rows, rank)
    assert s.shape == (rank, rank)
    assert v.shape == (cols, rank)
    np.testing.assert_allclose(u.T @ u, np.eye(rank), atol=4e-14, rtol=4e-14)
    np.testing.assert_allclose(v.T @ v, np.eye(rank), atol=4e-14, rtol=4e-14)
    np.testing.assert_allclose(s, np.diag(np.diag(s)), atol=4e-14)
    assert np.all(np.diag(s) >= 0)
    assert np.all(np.diff(np.diag(s)) <= 0)
    np.testing.assert_allclose(u @ s @ v.T, source, atol=4e-13, rtol=4e-14)


@pytest.mark.parametrize("source", [
    np.array([[1.0, -2.0, 3.0], [4.0, 1.0, -1.0]]),
    np.array([[1.0, 2.0], [-2.0, 1.0], [0.5, 3.0]]),
])
def test_sdk_rectangular_qr_and_svd_return_reduced_shapes(ee, source):
    matrix = ee.Array(source.tolist())
    qr_expression = encode(ee, matrix.matrixQRDecomposition())
    svd_expression = encode(ee, matrix.matrixSingularValueDecomposition())
    for expression, algorithm in (
            (qr_expression, "Array.matrixQRDecomposition"),
            (svd_expression, "Array.matrixSingularValueDecomposition")):
        calls = [node for _, node in expression.get("scope", [])
                 if isinstance(node, dict) and node.get("type") == "Invocation"
                 and node.get("functionName") == algorithm]
        assert len(calls) == 1
        assert set(calls[0]["arguments"]) == {"array"}
    _check_qr(source, output(ee, matrix.matrixQRDecomposition()))
    _check_svd(source, output(ee, matrix.matrixSingularValueDecomposition()))


@pytest.mark.parametrize("source", [
    np.array([[1.0, 2.0, 3.0], [2.0, 4.0, 6.0]]),
    np.zeros((3, 2)),
])
def test_rectangular_rank_deficient_and_zero_matrices_are_valid(ee, source):
    _check_qr(source, output(ee, ee.Array(source.tolist()).matrixQRDecomposition()))
    _check_svd(source, output(ee, ee.Array(source.tolist()).matrixSingularValueDecomposition()))


def test_square_lu_contract_and_other_invalid_static_shapes_are_unchanged(ee):
    with pytest.raises(UnsupportedEEError, match="square matrix"):
        output(ee, ee.Array([[1, 2, 3], [4, 5, 6]]).matrixLUDecomposition())
    with pytest.raises(UnsupportedEEError):
        output(ee, ee.Array([1, 2, 3]).matrixQRDecomposition())
    with pytest.raises(UnsupportedEEError):
        output(ee, ee.Array([]).matrixSingularValueDecomposition())
    with pytest.raises(UnsupportedEEError):
        output(ee, ee.Array([[True, False]]).matrixQRDecomposition())


def test_rectangular_work_and_square_work_precharge_costs():
    source = np.arange(1.0, 7.0).reshape((3, 2))
    for name, work in (
            ("Array.matrixQRDecomposition", 4 * 3 * 2 * 2 + 6 * 3 * 2),
            ("Array.matrixSingularValueDecomposition", 8 * 3 * 2 * 2 + 6 * 3 * 2)):
        translator = Translator([], {}, {})
        invoke_decomposition(
            translator, name, {"array": StaticArray(source.copy())},
        )
        assert translator.steps == work

    square = np.eye(3)
    for name, work in (
            ("Array.matrixQRDecomposition", 4 * 3**3 + 6 * 3**2),
            ("Array.matrixLUDecomposition", 2 * 3**3 + 6 * 3**2),
            ("Array.matrixSingularValueDecomposition", 8 * 3**3 + 6 * 3**2)):
        translator = Translator([], {}, {})
        invoke_decomposition(
            translator, name, {"array": StaticArray(square.copy())},
        )
        assert translator.steps == work


@pytest.mark.parametrize("name,n", [
    ("Array.matrixQRDecomposition", 71),
    ("Array.matrixSingularValueDecomposition", 58),
])
def test_combined_compact_output_limit_precedes_numpy_allocations(name, n, monkeypatch):
    source = StaticArray(np.eye(n))

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("NumPy allocation/factorization ran before output preflight")

    monkeypatch.setattr(np, "asarray", should_not_run)
    monkeypatch.setattr(np.linalg, "qr", should_not_run)
    monkeypatch.setattr(np.linalg, "svd", should_not_run)
    with pytest.raises(UnsupportedEEError, match="combined result exceeds 10000 cells"):
        invoke_decomposition(Translator([], {}, {}), name, {"array": source})


def test_rectangular_work_budget_precedes_float_copy_and_numpy_calls(monkeypatch):
    source = StaticArray(np.arange(1.0, 7.0).reshape((3, 2)))
    work = 8 * 3 * 2 * 2 + 6 * 3 * 2
    translator = Translator([], {}, {})
    translator.steps = MAX_ARRAY_WORK - work + 1

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("NumPy allocation/factorization ran before work preflight")

    monkeypatch.setattr(np, "asarray", should_not_run)
    monkeypatch.setattr(np.linalg, "qr", should_not_run)
    monkeypatch.setattr(np.linalg, "svd", should_not_run)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_decomposition(
            translator, "Array.matrixSingularValueDecomposition",
            {"array": source},
        )
    assert translator.steps == MAX_ARRAY_WORK - work + 1


def test_rectangular_input_is_untouched_and_results_are_owned_readonly_arrays():
    original = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 7.0]])
    before = original.copy()
    original.setflags(write=False)
    result = invoke_decomposition(
        Translator([], {}, {}), "Array.matrixSingularValueDecomposition",
        {"array": StaticArray(original)},
    )
    np.testing.assert_array_equal(original, before)
    assert set(result) == {"U", "S", "V"}
    for factor in result.values():
        assert isinstance(factor, StaticArray)
        assert not factor.data.flags.writeable
        assert not np.shares_memory(original, factor.data)
