"""Portable finite constants and strict v1 admission for core Float64 raster math."""
import math
from fractions import Fraction

import pytest

from gee.float64_values_contract import FLOAT64_ARITIES, evaluate_float64_values
from gee.integer_values_spec import constant_operand, decode_integer_values_spec, prepare_integer_values_spec


UNARY = {"absolute", "sqrt", "log", "log10", "exp", "round", "floor", "ceil", "sin", "cos", "tan", "not"}
BINARY = {"add", "subtract", "multiply", "divide", "power", "mod", "min2", "max2", "and", "or"}


def test_closed_twenty_two_operation_arities_have_no_implicit_callbacks():
    assert set(FLOAT64_ARITIES) == UNARY | BINARY
    assert {op for op, arity in FLOAT64_ARITIES.items() if arity == 1} == UNARY
    assert {op for op, arity in FLOAT64_ARITIES.items() if arity == 2} == BINARY


@pytest.mark.parametrize("operation", sorted(UNARY | BINARY))
def test_wire_accepts_finite_fractional_extreme_constants_but_rejects_wrong_arity(operation):
    count = 1 if operation in UNARY else 2
    operands = [{"band": 0}]
    if count == 2:
        operands.append(constant_operand(-1.7976931348623157e308))
    text = prepare_integer_values_spec(operation, operands)
    assert decode_integer_values_spec(text)["op"] == operation
    wrong = operands + [{"band": 0}] if count == 1 else operands[:1]
    with pytest.raises(ValueError):
        prepare_integer_values_spec(operation, wrong)
    with pytest.raises(ValueError):
        prepare_integer_values_spec(operation, operands, "int32")


@pytest.mark.parametrize("operation,values,expected", [
    ("add", [2**24, 1], 2**24 + 1),
    ("subtract", [2**53, 2**53 - 1], 1),
    ("multiply", [0.1, 0.3], float(Fraction(0.1) * Fraction(0.3))),
    ("divide", [1.0, 10.0], float(Fraction(1, 10))),
    ("divide", [1.0, -0.0], 0.0), ("divide", [0.0, 0.0], 0.0),
    ("mod", [-5.5, 2], -1.5), ("mod", [5.5, -2], 1.5),
    ("power", [-2, 3], -8), ("min2", [-1e300, 1e300], -1e300),
    ("max2", [-1e300, 1e300], 1e300),
    ("round", [2**52 - 1], float(2**52 - 1)),
    ("round", [2**52 + 1.0], 2**52 + 1.0),
    ("round", [-1.5], -1.0), ("round", [-0.5], 0.0),
    ("round", [-math.ulp(0.0)], 0.0),
    ("floor", [-math.ulp(0.0)], -1.0), ("ceil", [math.ulp(0.0)], 1.0),
    ("and", [math.ulp(0.0), -math.ulp(0.0)], 1),
    ("or", [-0.0, -math.ulp(0.0)], 1), ("not", [-0.0], 1),
    ("not", [math.ulp(0.0)], 0),
])
def test_finite_scalar_folds_preserve_binary64_and_local_edge_policies(operation, values, expected):
    assert evaluate_float64_values(operation, values) == expected


@pytest.mark.parametrize("operation,values", [
    ("add", [1.7976931348623157e308, 1.7976931348623157e308]),
    ("multiply", [1.7976931348623157e308, 2]),
    ("divide", [1.7976931348623157e308, math.ulp(0.0)]),
    ("sqrt", [-1]), ("log", [0]), ("log10", [-1]),
    ("exp", [1000]), ("power", [-1, 0.5]), ("power", [0, -1]),
    ("mod", [1, 0]),
])
def test_domain_and_overflow_results_are_nodata_without_hiding_invalid_inputs(operation, values):
    assert evaluate_float64_values(operation, values) is None
    for invalid in (None, True, "1", math.inf, math.nan, 2**53 + 1):
        changed = list(values)
        changed[0] = invalid
        with pytest.raises(ValueError):
            evaluate_float64_values(operation, changed)


def test_signed_zero_survives_native_compatible_scalar_boundaries():
    for operation in ("sqrt", "round", "floor", "ceil", "sin", "tan"):
        assert math.copysign(1, evaluate_float64_values(operation, [-0.0])) == -1
    assert math.copysign(1, evaluate_float64_values("min2", [0.0, -0.0])) == -1
    assert math.copysign(1, evaluate_float64_values("max2", [-0.0, 0.0])) == 1
    assert math.copysign(1, evaluate_float64_values("divide", [-1.0, -0.0])) == 1


def test_unknown_operation_dtype_and_noncanonical_constants_remain_rejections():
    for operation in (None, [], "asin", "where", "callback", "eval"):
        with pytest.raises(ValueError):
            evaluate_float64_values(operation, [1])
    with pytest.raises(ValueError):
        prepare_integer_values_spec("add", [{"band": 0}, {"constant": "7ff0000000000000"}])
