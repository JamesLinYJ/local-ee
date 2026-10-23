"""Independent selection semantics and opt-in actual GeoTrellis tile checks."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import struct
import sys

import pytest

from ee_selection_kernel_helpers import MAX_FLOAT, MIN_SUBNORMAL, make_fixture, reference
from ee_kernel_subprocess import run_bounded


ROOT = Path(__file__).resolve().parents[1]


def _decoded(row: dict) -> list[float]:
    return [math.nan if value == "NaN" else float.fromhex(value)
            for value in row["expected"]]


def _same_binary64(left: float, right: float) -> bool:
    if math.isnan(left) or math.isnan(right):
        return math.isnan(left) and math.isnan(right)
    return struct.pack(">d", left) == struct.pack(">d", right)


def _case(fixture: dict, name: str) -> dict:
    return next(row for row in fixture["cases"] if row["name"] == name)


def test_selection_fixture_is_deterministic_canonical_and_independently_referenced():
    fixture = make_fixture()
    assert fixture == make_fixture()
    assert fixture["schema"] == "local-ee-selection-kernel-synthetic/v1"
    assert fixture["operations"] == ["select", "where_select"]
    assert fixture["case_count"] == len(fixture["cases"]) == 5
    assert fixture["pixel_count"] == sum(len(row["expected"]) for row in fixture["cases"])
    for row in fixture["cases"]:
        spec = json.loads(row["spec"])
        assert set(spec) == {"dtype", "op", "operands", "v"}
        assert spec["op"] in fixture["operations"] and len(spec["operands"]) == 3
        assert spec["dtype"] is None and spec["v"] == 1
        assert len(row["spec"].encode("ascii")) <= 1024
        assert row["expected"] == [
            "NaN" if math.isnan(value) else value.hex()
            for value in reference(row)
        ]


def test_selection_reference_masks_condition_or_selected_value_only():
    fixture = make_fixture()
    dynamic = _decoded(_case(fixture, "three-dynamic-bands-mask-extremes-and-signed-zero"))
    assert dynamic[0] == MAX_FLOAT
    assert dynamic[1] == MIN_SUBNORMAL
    assert dynamic[2] == -MAX_FLOAT
    assert dynamic[3] == MIN_SUBNORMAL
    assert math.isnan(dynamic[5])  # NoData condition.
    assert dynamic[6] == 6.5  # Unselected reject branch is NoData.
    assert dynamic[7] == -9.0  # Unselected accept branch is NoData.
    assert math.isnan(dynamic[10])  # Selected accept branch is NoData.
    assert math.copysign(1.0, dynamic[4]) == -1.0
    assert math.copysign(1.0, dynamic[8]) == -1.0
    assert math.copysign(1.0, dynamic[9]) == -1.0

    constants = _decoded(_case(fixture, "constant-selected-branches-and-condition-mask"))
    assert constants[:4] == [1.25, -0.0, -0.0, 1.25]
    assert math.isnan(constants[4])
    assert math.copysign(1.0, constants[1]) == math.copysign(1.0, constants[2]) == -1.0

    constant_condition = _decoded(
        _case(fixture, "constant-subnormal-condition-with-two-dynamic-branches"),
    )
    assert constant_condition[0] == MAX_FLOAT
    assert constant_condition[1] == MIN_SUBNORMAL
    assert math.copysign(1.0, constant_condition[2]) == -1.0
    assert math.isnan(constant_condition[3])
    assert constant_condition[4] == 4.0


def test_where_selection_falls_back_on_missing_condition_or_replacement():
    fixture = make_fixture()
    dynamic = _decoded(_case(
        fixture, "where-dynamic-bands-fallback-masks-extremes-and-signed-zero",
    ))
    assert dynamic[0] == MAX_FLOAT
    assert dynamic[1] == -MAX_FLOAT  # Missing replacement preserves original.
    assert dynamic[2] == -MAX_FLOAT
    assert math.copysign(1.0, dynamic[3]) == -1.0
    assert dynamic[4] == 4.0  # Missing replacement preserves original.
    assert dynamic[5] == 5.0  # Missing condition preserves original.
    assert dynamic[6] == 6.0  # Missing condition preserves original.
    assert math.isnan(dynamic[7])  # Missing original always masks.
    assert dynamic[8] == 0.0 and math.copysign(1.0, dynamic[8]) == 1.0
    assert dynamic[9] == MIN_SUBNORMAL
    assert math.isnan(dynamic[10])  # Missing original always masks.
    assert dynamic[11] == 9.0  # Nonzero subnormal condition selects replacement.
    assert dynamic[12] == -MIN_SUBNORMAL
    assert dynamic[13] == -MAX_FLOAT

    constants = _decoded(_case(fixture, "where-constant-branches-subnormal-condition"))
    assert math.copysign(1.0, constants[0]) == -1.0
    assert constants[1] == MAX_FLOAT and constants[2] == MAX_FLOAT
    assert math.copysign(1.0, constants[3]) == -1.0


def test_invalid_specs_cover_arity_band_domain_dtype_and_constants():
    fixture = make_fixture()
    assert len(fixture["invalid_specs"]) >= 15
    decoded = [json.loads(text) for text in fixture["invalid_specs"]]
    assert any(row["op"] == "select" and len(row["operands"]) == 4 for row in decoded)
    assert any(row["op"] == "select" and row["dtype"] is not None for row in decoded)
    assert any(
        row["op"] == "select" and any(
            operand.get("band") == 3 for operand in row["operands"]
        ) for row in decoded
    )
    assert any(row["op"] == "where_select" and len(row["operands"]) == 2 for row in decoded)
    assert any(row["op"] == "where_select" and len(row["operands"]) == 4 for row in decoded)
    assert any(row["op"] == "where_select" and row["dtype"] is not None for row in decoded)
    assert any(row["op"] == "where_select" and any(
        operand.get("band") == 3 for operand in row["operands"]
    ) for row in decoded)
    assert any(row["op"] == "add" and len(row["operands"]) == 3 for row in decoded)
    assert any(row["op"] == "add" and any(
        operand.get("band") == 2 for operand in row["operands"]
    ) for row in decoded)
    assert len(fixture["invalid_tile_cases"]) >= 6
    assert {row["name"] for row in fixture["invalid_tile_cases"]} >= {
        "positive-infinity-in-unselected-branch",
        "negative-infinity-in-unselected-branch",
        "input-band-count-does-not-match-spec",
        "where-positive-infinity-in-unused-replacement",
        "where-negative-infinity-with-missing-condition",
        "where-input-band-count-does-not-match-spec",
    }


def test_native_contract_is_closed_ternary_and_preserves_old_operation_arity():
    native = (ROOT / "engine/ee_float64_values.scala").read_text(encoding="utf-8")
    spec = (ROOT / "engine/ee_integer_values_spec.scala").read_text(encoding="utf-8")
    assert '"select" -> 3' in native
    assert '"select" -> 3L' in native
    assert '"where_select" -> 3' in native
    assert '"where_select" -> 3L' in native
    assert "new Array[Double](requiredBands)" in native
    assert "!ConditionalOperations(spec.op) && value.isNaN" in native
    assert "LocalEeFloat64Values.ConditionalOperations(selectedOperation)" in spec
    assert "count < 3" in spec
    assert "val maxBandIndex = if (LocalEeFloat64Values.ConditionalOperations(selectedOperation)) 2 else 1" in spec
    assert "STRICT_DUPLICATE_DETECTION" in spec and "canonicalJson(result)" in spec
    assert "SparkContext" not in native and "ServiceLoader" not in native


def test_actual_geo_trellis_selection_tiles_match_independent_reference():
    if os.environ.get("LOCAL_EE_RUN_SELECTION_KERNEL_TEST") != "1":
        pytest.skip("opt-in trusted GeoTrellis selection probe; no SparkContext or service")
    manifest = os.environ.get("LOCAL_EE_SELECTION_ADAPTER_MANIFEST")
    if not manifest:
        pytest.skip("selection probe needs LOCAL_EE_SELECTION_ADAPTER_MANIFEST")

    result = run_bounded(
        [sys.executable, str(ROOT / "scripts/probe_selection_native.py"),
         "--manifest", manifest],
        cwd=str(ROOT), timeout=300,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    summary = json.loads(result.stdout)
    fixture = make_fixture()
    assert summary["fixture_schema"] == fixture["schema"]
    assert summary["case_count"] == fixture["case_count"] == 5
    assert summary["pixel_count"] == fixture["pixel_count"] == 40
    assert summary["invalid_spec_count"] == len(fixture["invalid_specs"])
    assert summary["invalid_tile_count"] == len(fixture["invalid_tile_cases"])
    assert "SELECTION_KERNEL_OK cases=5 pixels=40" in summary["summary"]
    assert "operations=select,where_select" in summary["summary"]
