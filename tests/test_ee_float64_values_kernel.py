"""Independent numerical contracts and opt-in actual GeoTrellis tile checks."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys

import pytest

from ee_float64_values_kernel_helpers import OPERATIONS, make_fixture, reference
from ee_float64_values_oracle import evaluate
from ee_kernel_subprocess import run_bounded


ROOT = Path(__file__).resolve().parents[1]


def _expected(case: dict) -> list[float | None]:
    return [None if value == "NaN" else float.fromhex(value) for value in case["expected"]]


def _case(fixture: dict, name: str) -> dict:
    return next(row for row in fixture["cases"] if row["name"] == name)


def test_fixture_is_deterministic_and_exercises_all_22_operations():
    fixture = make_fixture()
    assert fixture == make_fixture()
    assert fixture["schema"] == "local-ee-float64-values-synthetic/v1"
    assert fixture["operations"] == list(OPERATIONS) and len(OPERATIONS) == 22
    assert fixture["case_count"] == len(fixture["cases"])
    assert fixture["pixel_count"] == sum(len(row["expected"]) for row in fixture["cases"])
    assert {json.loads(row["spec"])["op"] for row in fixture["cases"]} == set(OPERATIONS)
    assert all(reference(row) == _expected(row) for row in fixture["cases"])
    assert {row["input_type"] for row in fixture["cases"]} >= {
        "double", "int-sentinel-0", "int-constant-nodata",
    }


def test_fraction_oracle_covers_binary64_rounding_overflow_and_signed_zero():
    fixture = make_fixture()
    added = _expected(_case(fixture, "add-exact-cancellation-overflow-and-high-bits"))
    assert added[0] == float((1 << 24) + 1)
    assert added[1] == float(1 << 53)  # exact halfway result rounds to even
    assert added[2] == math.nextafter(float(1 << 53), math.inf)
    assert added[3] is None  # finite inputs with an overflowing result become NoData
    assert added[4] == 0.0 and math.copysign(1.0, added[4]) == 1.0
    assert added[5] == 2.0 * math.ulp(0.0)
    assert added[6] == 0.0 and math.copysign(1.0, added[6]) == 1.0

    divided = _expected(_case(fixture, "divide-zero-policy-subnormal-and-overflow"))
    assert divided[1:4] == [0.0, 0.0, 0.0]
    assert math.copysign(1.0, divided[1]) == math.copysign(1.0, divided[2]) == 1.0
    assert divided[4] is None
    assert divided[5] == 0.0
    assert divided[6] == 0.0 and math.copysign(1.0, divided[6]) == -1.0

    rounded = _expected(_case(fixture, "round-ties-to-positive-infinity"))
    assert rounded[:8] == [-2.0, -1.0, 0.0, 0.0, 0.0, 1.0, 2.0, 3.0]
    assert rounded[-2:] == [float(1 << 53), float((1 << 24) + 1)]


def test_decimal_transcendental_oracle_and_masks_cover_subnormals_and_large_angles():
    fixture = make_fixture()
    expected_sqrt = _expected(_case(fixture, "sqrt-domain-subnormal-and-maximum"))
    assert expected_sqrt[0] is None and math.copysign(1.0, expected_sqrt[1]) == -1.0
    assert expected_sqrt[2] == math.sqrt(math.ulp(0.0))
    for operation in ("sin", "cos", "tan"):
        case = _case(fixture, f"{operation}-decimal-reference-large-negative")
        values = [float.fromhex(encoded) for encoded in case["bands"][0]]
        expected = _expected(case)
        for value, target in zip(values, expected):
            if target is None:
                continue
            actual = getattr(math, operation)(value)
            assert abs(actual - target) <= case["tolerance_ulps"] * math.ulp(target)

    equality_mask_case = _case(fixture, "integer-user-nodata-sentinel-preserves-int-min")
    assert _expected(equality_mask_case) == [2147483648.0, None, 123.0]
    assert _expected(_case(fixture, "integer-constant-nodata-minimum-remains-masked")) == [
        None, 123.0, 0.0,
    ]
    assert len(fixture["invalid_specs"]) >= 15
    assert {row["name"] for row in fixture["invalid_tile_cases"]} == {
        "source-positive-infinity-rejected", "source-negative-infinity-rejected",
    }


def test_thermal_ndvi_and_integer_qa_arithmetic_expectations_come_from_raw_inputs():
    composites = make_fixture()["composites"]
    thermal = composites["thermal_celsius_to_kelvin"]
    celsius = [float.fromhex(value) if value != "NaN" else None for value in thermal["raw_celsius"]]
    expected_kelvin = [None if value is None else evaluate("add", [value, 273.15])
                       for value in celsius]
    assert [None if value == "NaN" else float.fromhex(value)
            for value in thermal["expected_kelvin"]] == expected_kelvin
    assert expected_kelvin[0] == 0.0
    assert expected_kelvin[-1] is None

    ndvi = composites["ndvi_float64"]
    assert ndvi["expected_ndvi"][6:] == ["NaN", "NaN"]
    assert float.fromhex(ndvi["expected_denominator"][5]) == 0.0
    assert float.fromhex(ndvi["expected_ndvi"][5]) == 0.0

    qa = composites["qa_integer_result_arithmetic"]
    raw_qa = [None if value == "NaN" else int(float.fromhex(value))
              for value in qa["raw_qa"]]
    masked = [None if value is None else float(value & 3) for value in raw_qa]
    adjusted = [None if value is None else evaluate("add", [value, 0.25]) for value in masked]
    assert qa["expected_masked"] == ["NaN" if value is None else value.hex() for value in masked]
    assert qa["expected_adjusted"] == ["NaN" if value is None else value.hex() for value in adjusted]


def test_native_contract_is_closed_and_routes_float64_ops_through_actual_tile_kernel():
    native = (ROOT / "engine/ee_float64_values.scala").read_text(encoding="utf-8")
    dispatcher = (ROOT / "engine/ee_integer_values_numeric.scala").read_text(encoding="utf-8")
    spec = (ROOT / "engine/ee_integer_values_spec.scala").read_text(encoding="utf-8")
    assert "def applyTile(input: MultibandTile, spec: LocalEeIntegerValuesSpec.Value): Tile" in native
    assert "OperationArities" in native and "OperationWorkWeights" in native
    assert "LocalEeFloat64Values.applyTile(input, spec)" in dispatcher
    assert "LocalEeIntegerValuesSpec.parse(wire)" in (ROOT / "engine/ee_integer_values_adapter.scala").read_text()
    assert "STRICT_DUPLICATE_DETECTION" in spec and "canonicalJson(result)" in spec
    assert "SparkContext" not in native and "ServiceLoader" not in native


def test_actual_float64_tiles_match_independent_oracle_and_composite_chains():
    if os.environ.get("LOCAL_EE_RUN_FLOAT64_VALUES_KERNEL_TEST") != "1":
        pytest.skip("opt-in trusted GeoTrellis tile probe; no SparkContext, service, or user code")
    manifest = os.environ.get("LOCAL_EE_FLOAT64_VALUES_ADAPTER_MANIFEST")
    if not manifest:
        pytest.skip("native Float64-values probe needs LOCAL_EE_FLOAT64_VALUES_ADAPTER_MANIFEST")

    result = run_bounded(
        [sys.executable, str(ROOT / "scripts/probe_float64_values_native.py"),
         "--manifest", manifest],
        cwd=str(ROOT), timeout=300,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    summary = json.loads(result.stdout)
    fixture = make_fixture()
    assert summary["fixture_schema"] == fixture["schema"]
    assert summary["case_count"] == fixture["case_count"]
    assert summary["pixel_count"] == fixture["pixel_count"]
    assert summary["operation_count"] == len(OPERATIONS) == 22
    assert summary["invalid_spec_count"] == len(fixture["invalid_specs"])
    assert summary["invalid_tile_count"] == len(fixture["invalid_tile_cases"])
    assert summary["max_observed_ulps"] <= max(
        row["tolerance_ulps"] for row in fixture["cases"]
    )
    assert set(summary["tolerance_ulps_by_operation"]) == set(OPERATIONS)
    assert summary["composite_stage_count"] == 6
    assert summary["composite_pixel_count"] == 44
