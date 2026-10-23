"""Finite scalar policies shared with the integer-image compiler and wire gate.

These are explicit local policies, not an assertion of Google dtype parity.
The native implementation is independent and tested against integer references.
"""
from __future__ import annotations

import math

from .float64_values_contract import FLOAT64_ARITIES, FLOAT64_BOOLEAN, evaluate_float64_values


MAX_INTEGER = 2**53
CAST_BOUNDS = {
    "int8": (-128, 127), "uint8": (0, 255),
    "int16": (-32768, 32767), "uint16": (0, 65535),
    "int32": (-(2**31), 2**31 - 1), "uint32": (0, 2**32 - 1),
    "int64": (-MAX_INTEGER, MAX_INTEGER),
}
COMPARISONS = frozenset({"eq", "neq", "lt", "lte", "gt", "gte"})
BOOLEAN_OPERATIONS = COMPARISONS | FLOAT64_BOOLEAN
UNARY = frozenset({"cast", "bit_not", "bit_count"}) | frozenset(
    name for name, arity in FLOAT64_ARITIES.items() if arity == 1
)
OPERATIONS = COMPARISONS | UNARY | frozenset(FLOAT64_ARITIES) | frozenset({
    "bit_and", "bit_or", "bit_xor", "left_shift", "right_shift",
})


def finite_number(value):
    """Reject booleans and integers that would lose bits during wire conversion."""
    try:
        valid = (type(value) in (int, float) and math.isfinite(value)
                 and (type(value) is not int or abs(value) <= MAX_INTEGER))
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("Integer image operands require finite numbers; integers must be within +/-2^53")
    return value


def exact_integer(value):
    finite_number(value)
    if abs(value) > MAX_INTEGER or int(value) != value:
        raise ValueError("Bit operations require integral inputs and results within +/-2^53")
    return int(value)


def check_constant(operation, index, value):
    """Validate fixed operands even when every raster cell is masked or absent."""
    finite_number(value)
    if operation in COMPARISONS or operation in FLOAT64_ARITIES or operation == "cast":
        return
    integer = exact_integer(value)
    if operation in {"left_shift", "right_shift"} and index == 1 and not 0 <= integer <= 63:
        raise ValueError("Image shift count must be an integer in 0..63")


def validate_operation(operation, dtype):
    if type(operation) is not str or operation not in OPERATIONS:
        raise ValueError("Unsupported integer image operation")
    if operation == "cast":
        if type(dtype) is not str or dtype not in CAST_BOUNDS:
            raise ValueError("Integer image cast requires an explicit supported dtype")
    elif dtype is not None:
        raise ValueError("Integer image dtype must be null except for cast")
    return 1 if operation in UNARY else 2


def evaluate_integer_values(operation, values, dtype=None):
    """Fold finite constants without introducing a raster or implicit Float32 step."""
    arity = validate_operation(operation, dtype)
    if type(values) not in (list, tuple) or len(values) != arity:
        raise ValueError(f"Integer image {operation} requires exactly {arity} operands")
    for index, value in enumerate(values):
        check_constant(operation, index, value)
    if operation in FLOAT64_ARITIES:
        return evaluate_float64_values(operation, values)
    left = values[0]
    if operation in COMPARISONS:
        right = values[1]
        predicates = {"eq": left == right, "neq": left != right, "lt": left < right,
                      "lte": left <= right, "gt": left > right, "gte": left >= right}
        return int(predicates[operation])
    if operation == "cast":
        minimum, maximum = CAST_BOUNDS[dtype]
        if dtype == "int64" and abs(math.trunc(left)) > MAX_INTEGER:
            raise ValueError("Image int64 result exceeds the exact Float64 integer range")
        return math.trunc(max(minimum, min(maximum, left)))
    left = exact_integer(left)
    if operation == "bit_not":
        result = ~left
    elif operation == "bit_count":
        result = (left & ((1 << 64) - 1)).bit_count()
    else:
        right = exact_integer(values[1])
        if operation == "bit_and":
            result = left & right
        elif operation == "bit_or":
            result = left | right
        elif operation == "bit_xor":
            result = left ^ right
        elif operation == "left_shift":
            result = left << right
        else:
            result = left >> right
    return exact_integer(result)
