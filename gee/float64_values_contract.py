"""Closed scalar Float64 raster policies, independently implemented in Scala.

Each operation rounds at the binary64 boundary. Invalid or nonfinite results
become NoData; finite input validation is separate from result masking.
"""
from __future__ import annotations

import math


FLOAT64_ARITIES = {
    "add": 2, "subtract": 2, "multiply": 2, "divide": 2,
    "power": 2, "mod": 2, "min2": 2, "max2": 2, "and": 2, "or": 2,
    "absolute": 1, "sqrt": 1, "log": 1, "log10": 1, "exp": 1,
    "round": 1, "floor": 1, "ceil": 1, "sin": 1, "cos": 1, "tan": 1, "not": 1,
}
FLOAT64_BOOLEAN = frozenset({"and", "or", "not"})


def _finite(value):
    try:
        valid = (type(value) in (int, float) and math.isfinite(value)
                 and (type(value) is not int or abs(value) <= 2**53))
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("Float64 Image values must be finite; raw integers must be within +/-2^53")
    return float(value)


def _round(value):
    # Adding0.5 can increment an already integral value near2^52. For smaller
    # values the floor and fraction test express the local ties-to-+infinity
    # policy without perturbing that integral range.
    if abs(value) >= 2**52 or value == 0.0:
        return value
    lower = math.floor(value)
    return float(lower + (1 if value - lower >= 0.5 else 0))


def evaluate_float64_values(operation, values):
    """Fold fixed scalar inputs; None is a masked result, never a wire constant."""
    if type(operation) is not str or operation not in FLOAT64_ARITIES:
        raise ValueError("Unsupported Float64 Image operation")
    if type(values) not in (list, tuple) or len(values) != FLOAT64_ARITIES[operation]:
        raise ValueError("Float64 Image operation requires its exact scalar arity")
    numbers = tuple(_finite(value) for value in values)
    left = numbers[0]
    right = numbers[1] if len(numbers) == 2 else None
    if operation in FLOAT64_BOOLEAN:
        if operation == "not":
            return int(left == 0.0)
        return int((left != 0.0 and right != 0.0) if operation == "and"
                   else (left != 0.0 or right != 0.0))
    try:
        if operation == "add":
            result = left + right
        elif operation == "subtract":
            result = left - right
        elif operation == "multiply":
            result = left * right
        elif operation == "divide":
            # Pinned Image.divide explicitly returns0 for division by zero.
            result = 0.0 if right == 0.0 else left / right
        elif operation == "power":
            result = math.pow(left, right)
        elif operation == "mod":
            result = math.fmod(left, right)
        elif operation == "min2":
            result = min(left, right)
            if left == right == 0.0:
                result = -0.0 if math.copysign(1.0, left) < 0 or math.copysign(1.0, right) < 0 else 0.0
        elif operation == "max2":
            result = max(left, right)
            if left == right == 0.0:
                result = 0.0 if math.copysign(1.0, left) > 0 or math.copysign(1.0, right) > 0 else -0.0
        elif operation == "absolute":
            result = abs(left)
        elif operation == "round":
            result = _round(left)
        elif operation == "floor":
            result = left if left == 0.0 else float(math.floor(left))
        elif operation == "ceil":
            result = left if left == 0.0 else float(math.ceil(left))
        else:
            function = {"sqrt": math.sqrt, "log": math.log, "log10": math.log10,
                        "exp": math.exp, "sin": math.sin, "cos": math.cos, "tan": math.tan}[operation]
            result = function(left)
    except (OverflowError, ValueError, ZeroDivisionError):
        return None
    return result if math.isfinite(result) else None
