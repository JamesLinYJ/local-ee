"""Canonical public and wire contracts for mask-weight projections."""
from __future__ import annotations

import json
from decimal import Decimal
from fractions import Fraction
import math
from pathlib import Path
import struct
import sys

import pytest

from gee.backend import Processes
from gee.graph import validate
from gee.local_processes import validate_local_process
from gee.mask_weights_spec import (
    MASK_WEIGHT_ARITIES,
    decode_mask_weights_spec,
    mask_weights_process_spec,
    mask_weights_spec,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-mask-weights-wave64-v1.json"


def test_v1_wire_is_exact_canonical_json_and_closed():
    assert MASK_WEIGHT_ARITIES == {
        "validity": 1, "result_value": 1, "update": 2, "apply": 2,
    }
    for operation in ("validity", "result_value", "update", "apply"):
        wire = mask_weights_spec(operation)
        assert wire == f'{{"op":"{operation}","v":1}}'
        assert decode_mask_weights_spec(wire) == {"op": operation, "v": 1}


@pytest.mark.parametrize("operation", [None, True, 1, "", "multiply", "Validity"])
def test_unknown_operation_cannot_create_a_wire(operation):
    with pytest.raises(ValueError, match="Unsupported mask-weight operation"):
        mask_weights_spec(operation)


@pytest.mark.parametrize("wire", [
    "", " ", '{"op":"validity","op":"apply","v":1}',
    '{"op":"validity","v":1 }', '{"op":"validity","v":1,"extra":0}',
    '{"op":"unknown","v":1}', '{"op":"validity","v":2}',
    '{"op":1,"v":1}', '{"v":1,"op":"validity"}',
    '{"op":"validity","v":true}',
])
def test_noncanonical_duplicate_or_open_specs_are_rejected(wire):
    with pytest.raises(ValueError):
        decode_mask_weights_spec(wire)


@pytest.mark.parametrize("wire", ["é", "x" * 129])
def test_wire_must_be_bounded_ascii(wire):
    with pytest.raises(ValueError, match="bounded canonical ASCII"):
        decode_mask_weights_spec(wire)


def test_native_process_contract_is_registered_with_closed_ordered_inputs():
    expected = mask_weights_process_spec()
    registry = Processes().get_process_registry("1.2.0")
    actual = registry.get_spec("local_ee_mask_weights")
    assert actual["id"] == expected["id"]
    assert actual["experimental"] is True
    assert [row["name"] for row in actual["parameters"]] == ["data", "spec"]
    assert actual["returns"]["schema"]["subtype"] == "raster-cube"
    assert "Float64" in actual["returns"]["description"]

    arguments = {
        "data": {"from_node": "source"},
        "spec": mask_weights_spec("apply"),
    }
    validate_local_process("local_ee_mask_weights", arguments, 0)
    with pytest.raises(ValueError):
        validate_local_process("local_ee_mask_weights", arguments, 1)
    graph = {
        "source": {"process_id": "load_collection", "arguments": {"id": "sample"}},
        "weights": {"process_id": "local_ee_mask_weights", "arguments": arguments,
                    "result": True},
    }
    validate(graph)


@pytest.mark.parametrize("bad", [
    {"data": {"from_node": "source"}, "spec": mask_weights_spec("apply"), "extra": 1},
    {"data": {"from_node": "source"}, "spec": '{"op":"apply","v":1}'},
    {"data": {"from_parameter": "data"}, "spec": mask_weights_spec("apply")},
])
def test_public_process_rejects_extra_open_or_untrusted_arguments(bad):
    with pytest.raises(ValueError):
        validate_local_process("local_ee_mask_weights", bad, None)


def test_wave64_fixture_declares_valid_cases_and_invalid_wire_controls():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["schema"] == "local-ee-mask-weights-wave64/v1"
    assert fixture["sdk"] == "1.7.49"
    # Wave64 is retained as historical evidence; Wave66 adds a separate result projection.
    assert fixture["operations"] == ["validity", "update", "apply"]
    assert fixture["case_count"] == len(fixture["cases"]) + 1
    for row in fixture["cases"]:
        parsed = json.loads(row["spec"])
        assert row["spec"] == mask_weights_spec(parsed["op"])
    for wire in fixture["invalid_specs"]:
        with pytest.raises(ValueError):
            decode_mask_weights_spec(wire)


def _decode_number(value):
    if value == "NaN":
        return math.nan
    if value == "Infinity":
        return math.inf
    if value == "-Infinity":
        return -math.inf
    if value == "-0.0":
        return -0.0
    return float(value)


def _same_binary64(actual, expected):
    if math.isnan(actual) and math.isnan(expected):
        return True
    return struct.pack(">d", actual) == struct.pack(">d", expected)


def _check_weight(value, *, missing=False):
    if missing and math.isnan(value):
        return 0.0
    if not math.isfinite(value) or not Decimal.from_float(value).is_finite():
        raise ValueError("weight must be finite")
    if Decimal.from_float(value) < Decimal(0) or Decimal.from_float(value) > Decimal(1):
        raise ValueError("weight must be in [0,1]")
    return value


def _independent_reference(operation, bands):
    columns = [[_decode_number(value) for value in band] for band in bands]
    arity = {"validity": 1, "update": 2, "apply": 2}.get(operation)
    if (arity is None or len(columns) != arity or not columns[0]
            or any(len(column) != len(columns[0]) for column in columns)):
        raise ValueError("operation needs nonempty, equal-width bands with its exact arity")
    if operation == "validity":
        if any(not math.isnan(value) and not math.isfinite(value) for value in columns[0]):
            raise ValueError("validity rejects infinite values")
        return [0.0 if math.isnan(value) else 1.0 for value in columns[0]]
    if operation == "update":
        old_weights, new_masks = columns
        result = []
        for old_weight, new_mask in zip(old_weights, new_masks):
            _check_weight(old_weight)
            new_mask = _check_weight(new_mask, missing=True)
            result.append(0.0 if old_weight == 0.0 else new_mask)
        return result
    raw_values, weights = columns
    result = []
    for raw_value, weight in zip(raw_values, weights):
        _check_weight(weight)
        if not math.isnan(raw_value) and not math.isfinite(raw_value):
            raise ValueError("raw value must be finite or NoData")
        result.append(raw_value if weight > 0.0 else math.nan)
    return result


def test_fixture_matches_independent_binary64_reference_and_reject_controls():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert _decode_number(5e-324) == math.nextafter(0.0, 1.0)
    near_one = _decode_number(0.9999999990686774)
    assert Fraction.from_float(near_one) == Fraction(1) - Fraction(1, 2**30)
    assert _decode_number(1.7976931348623157e308) == sys.float_info.max
    valid_pixels = 0
    for row in fixture["cases"]:
        actual = _independent_reference(json.loads(row["spec"])["op"], row["bands"])
        expected = [_decode_number(value) for value in row["expected"]]
        assert len(actual) == len(expected)
        assert all(_same_binary64(left, right) for left, right in zip(actual, expected)), row["name"]
        valid_pixels += len(expected)
    for row in fixture["invalid_tile_cases"]:
        operation = json.loads(row["spec"])["op"]
        with pytest.raises(ValueError):
            _independent_reference(operation, row["bands"])

    composite = fixture["composite"]
    weights = [_decode_number(value) for value in composite["initial_weights"]]
    for mask in composite["new_masks"]:
        weights = _independent_reference("update", [
            ["-0.0" if value == 0.0 and math.copysign(1.0, value) < 0 else value
             for value in weights], mask,
        ])
    expected_weights = [_decode_number(value) for value in composite["expected_weights"]]
    assert all(_same_binary64(left, right) for left, right in zip(weights, expected_weights))
    values = _independent_reference("apply", [composite["raw_values"], composite["expected_weights"]])
    expected_values = [_decode_number(value) for value in composite["expected_values"]]
    assert all(_same_binary64(left, right) for left, right in zip(values, expected_values))
    assert valid_pixels + len(values) == fixture["pixel_count"]

