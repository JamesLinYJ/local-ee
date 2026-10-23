from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from ee_matrix_orthogonal_kernel_helpers import make_fixture
from ee_kernel_subprocess import run_bounded


NATIVE_SOURCES = (
    "engine/ee_cell_conversion.scala",
    "engine/ee_reduce_support.scala",
    "engine/ee_matrix_values_spec.scala",
    "engine/ee_matrix_values_numeric.scala",
    "engine/ee_matrix_orthogonal.scala",
    "engine/ee_matrix_svd_native.scala",
    "engine/ee_matrix_svd_jacobi.scala",
    "engine/ee_matrix_orthogonal_rank.scala",
    "engine/ee_matrix_orthogonal_budget.scala",
    "engine/ee_matrix_factorization.scala",
    "engine/ee_matrix_factorization_budget.scala",
    "engine/ee_matrix_values_adapter.scala",
)


def test_orthogonal_fixture_covers_compact_shapes_and_numeric_edges():
    fixture = make_fixture()
    cases = {row["label"]: row for row in fixture["cases"]}
    assert fixture["schema"] == "local-ee-matrix-orthogonal-kernel-synthetic/v1"
    assert fixture["case_count"] == len(cases) >= 20
    assert {
        "qr_square", "qr_tall", "qr_wide", "qr_rank_deficient", "qr_zero",
        "qr_tiny_trailing_diagonal", "qr_extreme_magnitude",
        "qr_8x4_mixed_extreme_outside_budget",
        "svd_square", "svd_tall", "svd_wide", "svd_rank_deficient", "svd_zero",
        "svd_repeated_singular_values", "svd_near_full_rank_exact_rank",
        "svd_extreme_diagonal_keeps_subnormal", "svd_reduction_overflow_fallback",
        "svd_subnormal_right_rotation", "svd_rank_deficient_tiny_active_direction",
        "svd_8x4_output_exactly_64", "svd_4x8_output_exactly_64",
        "svd_norm_overflow_masks_whole_factor", "svd_nan_masks_whole_factor",
    }.issubset(cases)
    assert cases["svd_rank_deficient_tiny_active_direction"]["rank"] == 2
    tiny_reference = cases["svd_rank_deficient_tiny_active_direction"]["singular_values"]
    assert float.fromhex(tiny_reference[1]) > 0.0
    assert cases["svd_extreme_diagonal_keeps_subnormal"]["input_bands"][3][0] == float.fromhex(
        "0x0.0000000000001p-1022").hex()
    assert all(
        (case["rows"] * min(case["rows"], case["cols"]) +
         min(case["rows"], case["cols"]) * case["cols"])
        if case["op"] == "qr" else
        (case["rows"] * min(case["rows"], case["cols"]) +
         min(case["rows"], case["cols"]) ** 2 +
         case["cols"] * min(case["rows"], case["cols"])) <= 64
        for case in fixture["cases"])
    assert len(fixture["invalid_specs"]) >= 6


def test_native_sources_register_orthogonal_budget_and_standalone_probe():
    sources = {name: (ROOT / name).read_text(encoding="utf-8") for name in NATIVE_SOURCES}
    spec = sources["engine/ee_matrix_values_spec.scala"]
    numeric = sources["engine/ee_matrix_values_numeric.scala"]
    orthogonal = sources["engine/ee_matrix_orthogonal.scala"]
    native_svd = sources["engine/ee_matrix_svd_native.scala"]
    jacobi = sources["engine/ee_matrix_svd_jacobi.scala"]
    rank = sources["engine/ee_matrix_orthogonal_rank.scala"]
    budget = sources["engine/ee_matrix_orthogonal_budget.scala"]
    adapter = sources["engine/ee_matrix_values_adapter.scala"]
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text(encoding="utf-8")
    probe = (ROOT / "scripts/probe_matrix_orthogonal_native.py").read_text(encoding="utf-8")
    fixture = (ROOT / "tests/fixtures/ee-matrix-orthogonal-kernel-probe.scala").read_text(
        encoding="utf-8")

    assert '"qr", "svd"' in spec
    assert "inputCells <= 64" in spec and "outputCells <= 64" in spec
    assert "LocalEeMatrixOrthogonal.evaluate(values, spec)" in numeric
    assert "java.lang.Math.hypot" in orthogonal
    assert "new SingularValueDecomposition" in native_svd
    assert "spectrumMatches" in native_svd and "exactRank" in native_svd
    assert "while (!converged && sweep < 32)" in jacobi
    assert "roundedLeft.multiply(roundedRight, Arithmetic)" in jacobi
    assert "Bareiss" in rank and "gramCoefficients" in rank
    assert "RationalBitBound" in budget and "DecimalEnvelopeExceeded" in budget
    assert "sourceRoundWork" in budget and "else 160L" in budget
    assert 'if (spec.op == "svd")' in budget
    assert "LocalEeMatrixOrthogonalBudget.admitSource" in adapter
    assert "requireWithinEnvelope" in adapter
    for source in NATIVE_SOURCES:
        assert source in builder
    assert "ee-matrix-orthogonal-kernel-probe.scala" in probe
    assert "LocalEeMatrixValuesNumeric.applyTile" in fixture
    assert "new SparkContext" not in probe and "ServiceLoader.load" not in probe
    assert "new SparkContext" not in fixture and "ServiceLoader.load" not in fixture
    assert "singular value" in fixture and "max_svd2_square_side" in fixture
    assert "checkJacobiSubnormalIdentity" in fixture


def _write_current_source_manifest(tmp_path: Path) -> Path:
    from scripts.build_integer_adapter import SERVICE_ENTRY, SERVICE_NAME, SOURCES
    from scripts.probe_matrix_orthogonal_native import sha256

    jar = tmp_path / "synthetic-local-adapter.jar"
    jar.write_bytes(b"synthetic orthogonal probe manifest-control artifact")
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


def test_probe_manifest_binds_exact_sources_and_provider(tmp_path: Path):
    from scripts.build_integer_adapter import SOURCES
    from scripts.probe_matrix_orthogonal_native import _checked_manifest

    manifest_path = _write_current_source_manifest(tmp_path)
    manifest, jar = _checked_manifest(manifest_path)
    assert set(manifest["sources"]) == {str(path.relative_to(ROOT)) for path in SOURCES}
    assert jar.read_bytes() == b"synthetic orthogonal probe manifest-control artifact"

    damaged = json.loads(manifest_path.read_text(encoding="utf-8"))
    del damaged["sources"]["engine/ee_matrix_orthogonal_rank.scala"]
    manifest_path.write_text(json.dumps(damaged), encoding="utf-8")
    with pytest.raises(ValueError, match="source set differs"):
        _checked_manifest(manifest_path)


def test_actual_orthogonal_geotrellis_tiles_pass_native_probe():
    if os.environ.get("LOCAL_EE_RUN_MATRIX_ORTHOGONAL_KERNEL_TEST") != "1":
        pytest.skip("opt-in trusted GeoTrellis tile probe; no SparkContext, service, or user code")
    manifest = os.environ.get("LOCAL_EE_MATRIX_ORTHOGONAL_ADAPTER_MANIFEST")
    if not manifest:
        pytest.skip("native orthogonal probe needs LOCAL_EE_MATRIX_ORTHOGONAL_ADAPTER_MANIFEST")

    result = run_bounded(
        [sys.executable, str(ROOT / "scripts/probe_matrix_orthogonal_native.py"),
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
    assert f"admitted={fixture['case_count'] - 1}" in summary["summary"]
    assert "direct_kernel_only=1" in summary["summary"]
    assert "qr8x4_extreme_rejected=true" in summary["summary"]
    assert "output64_both_orientations=true" in summary["summary"]
