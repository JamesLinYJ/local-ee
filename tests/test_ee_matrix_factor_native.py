from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from ee_kernel_subprocess import run_bounded
from ee_matrix_factor_kernel_helpers import make_fixture


NATIVE_SOURCES = (
    "engine/ee_cell_conversion.scala",
    "engine/ee_reduce_support.scala",
    "engine/ee_matrix_values_spec.scala",
    "engine/ee_matrix_values_numeric.scala",
    "engine/ee_matrix_factorization.scala",
    "engine/ee_matrix_factorization_budget.scala",
    "engine/ee_neighborhood_exact.scala",
    "engine/ee_matrix_values_adapter.scala",
)


def test_factor_fixture_covers_native_policies_and_independent_oracles():
    fixture = make_fixture()
    cases = {row["label"]: row for row in fixture["cases"]}
    assert fixture["schema"] == "local-ee-matrix-factor-kernel-synthetic/v1"
    assert fixture["case_count"] == len(cases) >= 15
    assert {
        "cholesky_extreme_original_scale",
        "cholesky_subnormal_diagonal",
        "cholesky_near_spd",
        "cholesky_exact_symmetry_rejects",
        "cholesky_zero_pivot_masks_all",
        "cholesky_negative_pivot_masks_all",
        "cholesky_nan_masks_all",
        "cholesky_max_shape_64_cells",
        "lu_pivot_swap_and_first_tie",
        "lu_later_swap_preserves_prior_l",
        "lu_near_singular_exact_rational",
        "lu_singular_pivot_masks_all",
        "lu_singular_nonbinary_pivot_masks_all",
        "lu_dependent_3x3_masks_all",
        "lu_subnormal_pivot_is_preserved",
        "lu_overflow_masks_all_factors",
        "lu_max_shape_output_48_cells",
    }.issubset(cases)
    assert all(row["oracle"] == "fraction" for row in fixture["cases"] if row["op"] == "lu")
    assert all(row["oracle"] == "numpy" for row in fixture["cases"] if row["op"] == "cholesky")
    assert all(row["absolute_tolerance"] == row["relative_tolerance"] == 0.0
               for row in fixture["cases"] if row["op"] == "lu")
    assert cases["cholesky_max_shape_64_cells"]["rows"] ** 2 == 64
    assert cases["lu_max_shape_output_48_cells"]["rows"] ** 2 * 3 == 48
    for label, output_band in (
        ("cholesky_near_spd", 3),
        ("cholesky_extreme_original_scale", 3),
        ("cholesky_subnormal_diagonal", 0),
        ("lu_near_singular_exact_rational", 7),
        ("lu_subnormal_pivot_is_preserved", 7),
    ):
        case = cases[label]
        assert case["absolute_tolerance"] == 0.0
        assert case["require_nonzero"] == [[output_band, 0]]
        assert float.fromhex(case["expected"][output_band][0]) != 0.0
    assert len(fixture["invalid_specs"]) >= 7


def test_fraction_lu_oracles_reconstruct_permuted_inputs():
    fixture = make_fixture()
    for case in fixture["cases"]:
        if case["op"] != "lu" or case["expected"][0][0] == "NaN":
            continue
        size = case["rows"]
        source = np.array([[float.fromhex(case["input_bands"][row * size + col][0])
                            for col in range(size)] for row in range(size)])
        values = np.array([float.fromhex(band[0]) for band in case["expected"]])
        lower = values[:size * size].reshape(size, size)
        upper = values[size * size:2 * size * size].reshape(size, size)
        permutation = values[2 * size * size:].reshape(size, size)
        assert np.array_equal(np.diag(lower), np.ones(size))
        assert np.all(np.triu(lower, 1) == 0.0)
        assert np.all(np.tril(upper, -1) == 0.0)
        assert np.array_equal(np.sort(np.argmax(permutation, axis=1)), np.arange(size))
        assert np.allclose(permutation @ source, lower @ upper, rtol=2e-14, atol=2e-14)


def test_native_contract_keeps_the_frozen_wire_budget_and_key_path():
    spec = (ROOT / "engine/ee_matrix_values_spec.scala").read_text(encoding="utf-8")
    numeric = (ROOT / "engine/ee_matrix_values_numeric.scala").read_text(encoding="utf-8")
    factor = (ROOT / "engine/ee_matrix_factorization.scala").read_text(encoding="utf-8")
    factor_budget = (ROOT / "engine/ee_matrix_factorization_budget.scala").read_text(encoding="utf-8")
    adapter = (ROOT / "engine/ee_matrix_values_adapter.scala").read_text(encoding="utf-8")
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text(encoding="utf-8")
    probe = (ROOT / "scripts/probe_matrix_factor_native.py").read_text(encoding="utf-8")
    probe_source = (ROOT / "tests/fixtures/ee-matrix-factor-kernel-probe.scala").read_text(
        encoding="utf-8")

    assert 'Set("solve", "inverse", "pinverse", "cholesky", "lu", "qr", "svd")' in spec
    assert 'Set("inverse", "cholesky", "lu")(selectedOperation)' in spec
    assert 'case "lu" => Math.multiplyExact(Math.multiplyExact(selectedRows, selectedCols), 3)' in spec
    assert "inputCells <= 64" in spec and "outputCells <= 64" in spec
    assert "private val Fields = Set(\"cols\", \"op\", \"operands\", \"rhs_cols\", \"rows\", \"v\")" in spec
    assert "LocalEeReduceSupport.copyAsDouble(input, spec.inputBands, cols, rows)" in numeric
    assert "LocalEeMatrixFactorization.evaluate(values, spec)" in numeric
    assert "matrix(row)(col) = new BigDecimal(value)" in factor
    assert "residual.sqrt(ArithmeticContext)" in factor
    assert "magnitude.compareTo(selectedMagnitude) > 0" in factor
    assert "upper(row)(pivot).divide(upper(pivot)(pivot))" in factor
    assert "LocalEeNeighborhoodExact.roundedRational" in factor
    assert "private def exactFraction(value: Double): BigFraction" in factor
    assert "new BigFraction(unscaled, BigInteger.TEN.pow(scale))" in factor
    assert "value.getNumerator" in factor and "value.getDenominator" in factor
    assert "permutation(rowIndex) == col" in factor
    assert "matrixScale" not in factor and "SingularValueDecomposition" not in factor
    assert 'if (spec.op == "cholesky")' in adapter
    assert 'if (spec.op == "lu")' in adapter
    assert "LocalEeMatrixFactorizationBudget.admitSource" in adapter
    assert "rawIntermediateBits" in factor_budget and "limbSquare" in factor_budget
    assert "source.map { case (_, tile) =>" in factor_budget
    assert ".fold((EmptyEnvelope, 0L))" in factor_budget
    assert "RationalBitBound" in factor_budget
    assert "MaxTileWork = 100000000L" in adapter
    assert "MaxTotalWork = 1000000000L" in adapter
    assert "MaxTileKeys = 100000L" in adapter
    assert "engine/ee_matrix_factorization.scala" in builder
    assert "engine/ee_matrix_factorization_budget.scala" in builder
    assert "ee-matrix-factor-kernel-probe.scala" in probe
    assert "new SparkContext" not in probe and "ServiceLoader.load" not in probe
    assert "new SparkContext" not in probe_source and "ServiceLoader.load" not in probe_source
    assert "input.source.map { case (key, tile) =>" in adapter
    assert "key -> LocalEeMatrixValuesNumeric.applyTile(tile, spec)" in adapter
    assert "val times = input.times.toSet" in adapter
    assert "val grid = input.grid" in adapter
    assert "minSpatial" in adapter and "maxSpatial" in adapter


def _write_current_source_manifest(tmp_path: Path) -> Path:
    from scripts.build_integer_adapter import SERVICE_ENTRY, SERVICE_NAME, SOURCES
    from scripts.probe_matrix_factor_native import sha256

    jar = tmp_path / "synthetic-local-adapter.jar"
    jar.write_bytes(b"synthetic factor probe manifest control")
    manifest = {
        "adapter": "local-ee-integer-adapter",
        "build_script_sha256": sha256(ROOT / "scripts/build_integer_adapter.py"),
        "jar": str(jar),
        "jar_sha256": sha256(jar),
        "services": {SERVICE_NAME: SERVICE_ENTRY.strip()},
        "sources": {str(path.relative_to(ROOT)): sha256(path) for path in SOURCES},
    }
    path = tmp_path / "synthetic-local-adapter.manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_factor_probe_binds_the_exact_adapter_manifest(tmp_path: Path):
    from scripts.build_integer_adapter import SOURCES
    from scripts.probe_matrix_factor_native import _checked_manifest

    manifest_path = _write_current_source_manifest(tmp_path)
    manifest, jar = _checked_manifest(manifest_path)
    assert set(manifest["sources"]) == {str(path.relative_to(ROOT)) for path in SOURCES}
    assert jar.read_bytes() == b"synthetic factor probe manifest control"

    damaged = json.loads(manifest_path.read_text(encoding="utf-8"))
    damaged["sources"]["engine/ee_matrix_factorization.scala"] = "0" * 64
    manifest_path.write_text(json.dumps(damaged), encoding="utf-8")
    with pytest.raises(ValueError, match="current native source"):
        _checked_manifest(manifest_path)


def test_actual_factor_tiles_match_independent_oracles():
    if os.environ.get("LOCAL_EE_RUN_MATRIX_FACTOR_KERNEL_TEST") != "1":
        pytest.skip("opt-in trusted GeoTrellis tile probe; no SparkContext, service, or user code")
    manifest = os.environ.get("LOCAL_EE_MATRIX_FACTOR_ADAPTER_MANIFEST")
    if not manifest:
        pytest.skip("native matrix-factor probe needs LOCAL_EE_MATRIX_FACTOR_ADAPTER_MANIFEST")

    result = run_bounded(
        [sys.executable, str(ROOT / "scripts/probe_matrix_factor_native.py"),
         "--manifest", manifest],
        cwd=str(ROOT), timeout=300,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    summary = json.loads(result.stdout)
    fixture = make_fixture()
    assert summary["fixture_schema"] == fixture["schema"]
    assert summary["case_count"] == fixture["case_count"]
    assert summary["pixel_count"] == fixture["pixel_count"]
    assert summary["invalid_spec_count"] == len(fixture["invalid_specs"])
    assert summary["fraction_oracle_cases"] == 9
    assert summary["numpy_oracle_cases"] == 9
    assert "whole_factor_mask=true" in summary["summary"]
    assert "lu2_integer_128_work=" in summary["summary"]
    assert "lu2_fractional_256_work=" in summary["summary"]
    assert "lu2_extreme_1_work=" in summary["summary"]
    assert "envelope_checks=6" in summary["summary"]
    assert "lu_envelope_merge=pass" in summary["summary"]
    assert "lu2_negative_1_work=" in summary["summary"]
    assert "lu2_zero_widened_1_work=" in summary["summary"]
