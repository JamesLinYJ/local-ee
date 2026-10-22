"""Finite static scalar math with explicit argument and work contracts."""
from __future__ import annotations

import math

from .array_core import charge_array
from .ir import Collection, Image, fail


_UNARY = {"sin", "cos"}
_BINARY = {"hypot", "atan2"}
NUMBER_MATH_FUNCTIONS = frozenset("Number." + name for name in _UNARY | _BINARY)


def _number(value, operation):
    if isinstance(value, (Image, Collection)):
        fail("Expected a static Number")
    if (type(value) not in (int, float)
            or type(value) is int and abs(value) > 2 ** 53
            or type(value) is float and not math.isfinite(value)):
        fail(f"{operation} requires a finite static numeric input; integers must be exact Float64")
    return float(value)


def invoke_number_math(translator, name, arguments):
    """Compute supported radian functions and stable vector magnitudes.

    Float64 libm rounding and argument reduction are local policies; no
    numerical equivalence to Google's service is inferred from these kernels.
    """
    if name not in NUMBER_MATH_FUNCTIONS:
        fail(f"Unsupported static Number math: {name}")
    operation = name.split(".", 1)[1]
    parameters = ("input",) if operation in _UNARY else ("left", "right")
    translator.allowed(arguments, set(parameters))
    missing = [parameter for parameter in parameters if parameter not in arguments]
    if missing:
        fail(f"{name} requires {', '.join(missing)}")
    values = tuple(_number(arguments[parameter], name) for parameter in parameters)
    charge_array(translator, len(parameters))
    try:
        # The pinned SDK describes [left, right] as [x, y], and Array.atan2
        # explicitly names right as y. libm instead accepts (y, x).
        if operation == "atan2":
            values = (values[1], values[0])
        result = getattr(math, operation)(*values)
    except (ArithmeticError, ValueError):
        fail(f"{name} must produce a finite real number")
    if not math.isfinite(result):
        fail(f"{name} must produce a finite real number")
    return result
