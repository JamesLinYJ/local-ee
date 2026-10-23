"""Finite static scalar math with explicit argument and work contracts."""
from __future__ import annotations

from fractions import Fraction
import math

from .array_core import charge_array
from .ir import Collection, Image, UnsupportedEEError, fail


_UNARY = {
    "sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh",
    "tanh", "log", "log10", "exp", "cbrt", "signum", "erf", "erfc",
    "gamma", "not",
}
_BINARY = {
    "hypot", "atan2", "min", "max", "first", "firstNonZero",
    "first_nonzero", "and", "or",
}
_TERNARY = {"clamp", "unitScale"}
NUMBER_MATH_FUNCTIONS = frozenset(
    "Number." + name for name in _UNARY | _BINARY | _TERNARY
)


def _number(value, operation):
    if isinstance(value, (Image, Collection)):
        fail("Expected a static Number")
    if (type(value) not in (int, float)
            or type(value) is int and abs(value) > 2 ** 53
            or type(value) is float and not math.isfinite(value)):
        fail(f"{operation} requires a finite static numeric input; integers must be exact Float64")
    return float(value)


def _parameters(operation):
    if operation in _UNARY:
        return ("input",)
    if operation in _BINARY:
        return ("left", "right")
    if operation in _TERNARY:
        return ("number", "min", "max")
    return ()


def _unit_scale(number, lower, upper):
    if lower == upper:
        return 0.0
    # Exact binary-rational subtraction avoids overflowing an intermediate
    # when the finite scaled result is representable (for example [-1e308, 1e308]).
    ratio = ((Fraction.from_float(number) - Fraction.from_float(lower)) /
             (Fraction.from_float(upper) - Fraction.from_float(lower)))
    try:
        return float(ratio)
    except OverflowError:
        fail("Number.unitScale exceeds the finite Float64 domain")


def _compute(operation, values, name):
    if operation == "atan2":
        # The pinned SDK describes [left, right] as [x, y], while libm takes (y, x).
        result = math.atan2(values[1], values[0])
    elif operation == "signum":
        result = (values[0] > 0) - (values[0] < 0)
    elif operation == "not":
        result = 0.0 if values[0] != 0 else 1.0
    elif operation in {"first", "firstNonZero", "first_nonzero"}:
        result = values[0] if operation == "first" or values[0] != 0 else values[1]
    elif operation == "and":
        result = float(values[0] != 0 and values[1] != 0)
    elif operation == "or":
        result = float(values[0] != 0 or values[1] != 0)
    elif operation in {"min", "max"}:
        result = min(values) if operation == "min" else max(values)
    elif operation == "clamp":
        number, lower, upper = values
        if lower > upper:
            fail("Number.clamp requires min <= max")
        result = min(max(number, lower), upper)
    elif operation == "unitScale":
        result = _unit_scale(*values)
    else:
        try:
            result = getattr(math, operation)(*values)
        except (ArithmeticError, ValueError):
            fail(f"{name} must produce a finite real number")
    if type(result) not in (int, float) or not math.isfinite(result):
        fail(f"{name} must produce a finite real number")
    return result


def invoke_number_math(translator, name, arguments):
    """Compute supported finite scalar operators with bounded static work.

    Float64 libm rounding and argument reduction are local policies; this
    handler does not claim numerical equivalence to Google's service.
    """
    if name not in NUMBER_MATH_FUNCTIONS:
        fail(f"Unsupported static Number math: {name}")
    operation = name.split(".", 1)[1]
    parameters = _parameters(operation)
    translator.allowed(arguments, set(parameters))
    missing = [parameter for parameter in parameters if parameter not in arguments]
    if missing:
        fail(f"{name} requires {', '.join(missing)}")
    # Validate every operand, including operands ignored by first/firstNonZero,
    # before charging and before selecting a result.
    values = tuple(_number(arguments[parameter], name) for parameter in parameters)
    charge_array(translator, len(parameters))
    try:
        return _compute(operation, values, name)
    except UnsupportedEEError:
        raise
    except (ArithmeticError, ValueError):
        fail(f"{name} must produce a finite real number")
