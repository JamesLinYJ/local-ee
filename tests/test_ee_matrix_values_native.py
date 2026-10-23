from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from ee_matrix_values_kernel_helpers import make_fixture
from ee_kernel_subprocess import run_bounded


NATIVE_SOURCES = (
    "engine/ee_cell_conversion.scala",
    "engine/ee_reduce_support.scala",
    "engine/ee_matrix_values_spec.scala",
    "engine/ee_matrix_values_numeric.scala",
    "engine/ee_matrix_values_adapter.scala",
)


def _float(text: str) -> float:
    return float.fromhex(text)


def test_independent_matrix_fixture_covers_shapes_masks_and_extremes():
    fixture = make_fixture()
    cases = {row["label"]: row for row in fixture["cases"]}
    assert fixture["schema"] == "local-ee-matrix-values-synthetic/v1"
    assert fixture["case_count"] == len(cases) >= 15
    assert {
        "solve_tall_multi_rhs_and_mask",
        "solve_wide_minimum_norm",
        "solve_rank_deficient_minimum_norm",
        "inverse_fraction_and_singular_mask",
        "pinverse_tall",
        "pinverse_wide",
        "zero_matrix_solve",
        "zero_matrix_pinverse",
        "subnormal_matrix_and_scaled_rhs",
        "tiny_a_tiny_and_huge_rhs_columns",
        "huge_orthogonal_rhs_component",
        "overflowing_scale_ratio_with_finite_result",
        "overflow_result_masks_whole_matrix",
        "large_common_baseline_fraction_intercept_slope",
        "local_rank_threshold_below_exact_above",
        "constant_operand_wire",
        "max_shape_and_band_63",
        "max_solve_input_cells_64",
    }.issubset(cases)
    assert cases["large_common_baseline_fraction_intercept_slope"]["oracle"] == "fraction"
    baseline = cases["large_common_baseline_fraction_intercept_slope"]["expected"]
    baseline_case = cases["large_common_baseline_fraction_intercept_slope"]
    assert baseline_case["absolute_tolerance"] == 1e-10
    assert baseline_case["relative_tolerance"] == 0.0
    next_intercept = float.fromhex("0x1.0000000000001p+40")
    assert next_intercept - 2.0 ** 40 > baseline_case["absolute_tolerance"]
    assert _float(baseline[0][0]) == 2.0 ** 40
    assert _float(baseline[1][0]) == 3.0
    tiny = cases["tiny_a_tiny_and_huge_rhs_columns"]["expected"]
    assert cases["tiny_a_tiny_and_huge_rhs_columns"]["absolute_tolerance"] == 0.0
    assert cases["tiny_a_tiny_and_huge_rhs_columns"]["require_nonzero"] == [[0, 0], [3, 0]]
    assert _float(tiny[0][0]) > 0.0
    assert _float(tiny[3][0]) == pytest.approx(1e308, rel=1e-14)
    orthogonal = cases["huge_orthogonal_rhs_component"]["expected"]
    assert cases["huge_orthogonal_rhs_component"]["absolute_tolerance"] == 0.0
    assert cases["huge_orthogonal_rhs_component"]["require_nonzero"] == [[0, 0]]
    assert _float(orthogonal[0][0]) == pytest.approx(4.940656458412465e-16, rel=1e-14)
    boundary = cases["local_rank_threshold_below_exact_above"]["expected"]
    assert _float(boundary[3][0]) == 0.0
    assert _float(boundary[3][1]) == 0.0
    assert _float(boundary[3][2]) > 0.0
    assert all(value == "NaN" for band in
               cases["overflow_result_masks_whole_matrix"]["expected"] for value in band)
    assert len(fixture["invalid_specs"]) >= 15


def test_native_sources_and_builder_preserve_the_matrix_values_contract():
    sources = {name: (ROOT / name).read_text(encoding="utf-8") for name in NATIVE_SOURCES}
    spec = sources["engine/ee_matrix_values_spec.scala"]
    numeric = sources["engine/ee_matrix_values_numeric.scala"]
    adapter = sources["engine/ee_matrix_values_adapter.scala"]
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text(encoding="utf-8")
    probe = (ROOT / "scripts/probe_matrix_values_native.py").read_text(encoding="utf-8")
    probe_source = (ROOT / "tests/fixtures/ee-matrix-values-kernel-probe.scala").read_text(
        encoding="utf-8")

    assert "STRICT_DUPLICATE_DETECTION" in spec
    assert "canonical compact sorted-key JSON" in spec
    assert "private val MaxBytes = 8192" in spec
    assert "inputCells <= 64" in spec and "outputCells <= 64" in spec
    assert '"matrix values band index", 0, 63' in spec
    assert "band references must be contiguous from band 0" in spec
    assert "LocalEeReduceSupport.copyAsDouble(input, spec.inputBands, cols, rows)" in numeric
    assert "def validateTileShape(" in numeric
    assert "new SingularValueDecomposition" in numeric and "decomposition.getRank" in numeric
    assert "v.getEntry(row, singularIndex) / singular(singularIndex)" in numeric
    assert "new BigDecimal(coefficient).multiply(centered)" in numeric
    assert "new BigDecimal(rhsValue)" in numeric
    assert "constantColumn(matrix, spec)" in numeric
    assert "rhsScale" not in numeric
    assert "id = \"local_ee_matrix_values\"" in adapter
    assert "input.names == expectedBandNames" in adapter
    assert "validateTileShape(tile, spec, cols, rows)" in adapter
    assert "s\"matrix$index\"" in adapter
    assert "MaxTileWork = 100000000L" in adapter
    assert "MaxTotalWork = 1000000000L" in adapter
    assert "MaxTileKeys = 100000L" in adapter
    assert "bigDecimalProducts" in adapter and "bigDecimalDivisions" in adapter
    for source in NATIVE_SOURCES:
        assert source in builder
    assert "LocalEeMatrixValuesCubeProcessProvider" in builder
    assert "LocalEeMatrixValuesNumeric.applyTile" in probe
    assert "ee-matrix-values-kernel-probe.scala" in probe
    assert "new SparkContext" not in probe_source and "ServiceLoader.load" not in probe_source
    assert "requiredNonzero" in probe_source and "checkTileValidation" in probe_source
    assert "new SparkContext" not in probe and "ServiceLoader.load" not in probe


def _write_current_source_manifest(tmp_path: Path) -> Path:
    from scripts.build_integer_adapter import SERVICE_ENTRY, SERVICE_NAME, SOURCES
    from scripts.probe_matrix_values_native import sha256

    jar = tmp_path / "synthetic-local-adapter.jar"
    jar.write_bytes(b"synthetic portable manifest-control artifact")
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


def test_native_manifest_binds_exact_current_sources_and_provider(tmp_path: Path):
    from scripts.build_integer_adapter import SOURCES
    from scripts.probe_matrix_values_native import _checked_manifest

    manifest_path = _write_current_source_manifest(tmp_path)
    manifest, jar = _checked_manifest(manifest_path)
    assert set(manifest["sources"]) == {str(path.relative_to(ROOT)) for path in SOURCES}
    assert jar.read_bytes() == b"synthetic portable manifest-control artifact"

    damaged = json.loads(manifest_path.read_text(encoding="utf-8"))
    del damaged["sources"]["engine/ee_matrix_values_numeric.scala"]
    manifest_path.write_text(json.dumps(damaged), encoding="utf-8")
    with pytest.raises(ValueError, match="source set differs"):
        _checked_manifest(manifest_path)


def test_actual_matrix_values_tiles_match_independent_oracles():
    if os.environ.get("LOCAL_EE_RUN_MATRIX_VALUES_KERNEL_TEST") != "1":
        pytest.skip("opt-in trusted GeoTrellis tile probe; no SparkContext, service, or user code")
    manifest = os.environ.get("LOCAL_EE_MATRIX_VALUES_ADAPTER_MANIFEST")
    if not manifest:
        pytest.skip("native matrix-values probe needs LOCAL_EE_MATRIX_VALUES_ADAPTER_MANIFEST")

    result = run_bounded(
        [sys.executable, str(ROOT / "scripts/probe_matrix_values_native.py"),
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
    assert summary["fraction_oracle_cases"] >= 2
    assert "rank_policy=commons-math-3.6.1" in summary["summary"]
