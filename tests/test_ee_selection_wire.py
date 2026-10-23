"""Strict ternary select admission in the bounded Float64 wire."""
import pytest

from gee.float64_values_contract import FLOAT64_ARITIES, evaluate_float64_values
from gee.integer_values_spec import (
    MAX_BYTES,
    constant_operand,
    decode_integer_values_spec,
    integer_values_process_spec,
    prepare_integer_values_spec,
)


def _select(operands):
    return prepare_integer_values_spec("select", operands)


def _where_select(operands):
    return prepare_integer_values_spec("where_select", operands)


@pytest.mark.parametrize("operation,prepare", [
    ("select", _select), ("where_select", _where_select),
])
def test_internal_ternary_operations_have_exactly_three_operands_and_canonical_three_band_wire(
        operation, prepare):
    operands = [{"band": 0}, {"band": 1}, {"band": 2}]
    text = prepare(operands)

    assert FLOAT64_ARITIES[operation] == 3
    assert decode_integer_values_spec(text) == {
        "dtype": None, "op": operation, "operands": operands, "v": 1,
    }
    for wrong_arity in (operands[:2], operands + [{"band": 3}]):
        with pytest.raises(ValueError, match="exactly 3 operands"):
            prepare_integer_values_spec(operation, wrong_arity)


@pytest.mark.parametrize("operation,prepare", [
    ("select", _select), ("where_select", _where_select),
])
def test_internal_ternary_allows_finite_constants_but_rejects_invalid_constants_in_any_position(
        operation, prepare):
    operands = [{"band": 0}, constant_operand(-0.0), {"band": 1}]
    decoded = decode_integer_values_spec(prepare(operands))
    assert decoded["operands"][1] == {"constant": "8000000000000000"}

    invalid_constants = ("7ff0000000000000", "fff0000000000000", "7ff8000000000000")
    for index in range(3):
        for encoded in invalid_constants:
            candidate = [{"band": 0}, {"band": 1}, {"band": 2}]
            candidate[index] = {"constant": encoded}
            with pytest.raises(ValueError, match="finite"):
                prepare_integer_values_spec(operation, candidate)


@pytest.mark.parametrize("prepare", [_select, _where_select])
def test_internal_ternary_band_references_are_contiguous_and_limited_to_zero_through_two(prepare):
    with pytest.raises(ValueError, match="band index must be 0, 1, or 2"):
        prepare([{"band": 0}, {"band": 1}, {"band": 3}])
    with pytest.raises(ValueError, match="contiguous from 0"):
        prepare([{"band": 0}, {"band": 2}, constant_operand(3)])


@pytest.mark.parametrize("operation,operands", [
    ("add", [{"band": 0}, {"band": 2}]),
    ("min2", [{"band": 0}, {"band": 1}, {"band": 2}]),
    ("absolute", [{"band": 0}, {"band": 2}]),
])
def test_other_operations_cannot_consume_a_third_operand_or_band(operation, operands):
    with pytest.raises(ValueError):
        prepare_integer_values_spec(operation, operands)


def test_process_contract_keeps_the_existing_1024_byte_limit_and_documents_selection_masks():
    process = integer_values_process_spec()
    spec_schema = process["parameters"][1]["schema"]

    assert MAX_BYTES == spec_schema["maxLength"] == 1024
    assert "unselected branch's NoData does not mask the result" in process["description"]
    assert "condition or replacement NoData retains the original value" in process["description"]
    with pytest.raises(ValueError, match="at most 1024 ASCII bytes"):
        decode_integer_values_spec(" " * 1025)


def test_constant_select_fold_uses_nonzero_condition_without_rounding_selected_values():
    assert evaluate_float64_values("select", [1.0, 0.1, 0.2]) == 0.1
    assert evaluate_float64_values("select", [-1.0, 0.1, 0.2]) == 0.1
    assert evaluate_float64_values("select", [-0.0, 0.1, 0.2]) == 0.2
    assert evaluate_float64_values("where_select", [1.0, 0.1, 0.2]) == 0.1
    assert evaluate_float64_values("where_select", [-1.0, 0.1, 0.2]) == 0.1
    assert evaluate_float64_values("where_select", [-0.0, 0.1, 0.2]) == 0.2


def test_public_where_name_remains_outside_the_internal_wire():
    with pytest.raises(ValueError, match="Unsupported integer image operation"):
        prepare_integer_values_spec("where", [{"band": 0}, {"band": 1}, {"band": 2}])
