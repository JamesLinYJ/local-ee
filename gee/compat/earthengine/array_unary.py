"""Bounded elementwise unary math for static Earth Engine Arrays."""
from __future__ import annotations

import math

import numpy as np

from .array_core import charge_array, require_array, wrap_array
from .ir import fail


ARRAY_UNARY_FUNCTIONS = frozenset({
    "Array.sin", "Array.cos", "Array.tan", "Array.asin", "Array.acos",
    "Array.atan", "Array.sinh", "Array.cosh", "Array.tanh", "Array.log",
    "Array.log10", "Array.exp", "Array.floor", "Array.ceil", "Array.round",
    "Array.cbrt", "Array.signum", "Array.erf", "Array.erfc", "Array.gamma",
    "Array.not",
})

_NUMPY_KERNELS = {
    "Array.sin": np.sin,
    "Array.cos": np.cos,
    "Array.tan": np.tan,
    "Array.asin": np.arcsin,
    "Array.acos": np.arccos,
    "Array.atan": np.arctan,
    "Array.sinh": np.sinh,
    "Array.cosh": np.cosh,
    "Array.tanh": np.tanh,
    "Array.log": np.log,
    "Array.log10": np.log10,
    "Array.exp": np.exp,
    "Array.floor": np.floor,
    "Array.ceil": np.ceil,
    "Array.cbrt": np.cbrt,
}


def _mapped_math(array, function, name):
    values = []
    for value in array.flat:
        try:
            result = function(float(value))
        except (ArithmeticError, ValueError):
            fail(f"{name} requires values in its finite real domain")
        if not math.isfinite(result):
            fail(f"{name} must produce finite real values")
        values.append(result)
    return np.asarray(values, dtype=np.float64).reshape(array.shape)


def invoke_unary(translator, name, arguments):
    """Evaluate one pinned Array unary algorithm after charging its full cost."""
    if name not in ARRAY_UNARY_FUNCTIONS:
        fail(f"Unsupported static Array unary operation: {name}")
    translator.allowed(arguments, {"input"})
    if "input" not in arguments:
        fail(f"{name} requires input")
    array = require_array(arguments["input"])

    multiplier = 24 if name == "Array.gamma" else 16 if name in {
        "Array.erf", "Array.erfc",
    } else 8 if name in {
        "Array.sin", "Array.cos", "Array.tan", "Array.asin", "Array.acos",
        "Array.atan", "Array.sinh", "Array.cosh", "Array.tanh", "Array.log",
        "Array.log10", "Array.exp", "Array.cbrt",
    } else 2
    charge_array(translator, int(array.size) * multiplier + 1)

    if name in {"Array.asin", "Array.acos"} and np.any(
            (array < -1) | (array > 1)):
        fail(f"{name} requires inputs in [-1, 1]")
    if name in {"Array.log", "Array.log10"} and np.any(array <= 0):
        fail(f"{name} requires positive inputs")

    if name == "Array.not":
        return wrap_array((array == 0).astype(np.int64))
    if name == "Array.signum":
        return wrap_array(np.sign(array))
    if name == "Array.round":
        # Number.round and the pinned Array description use nearest integer;
        # the shared scalar policy resolves ties toward positive infinity.
        with np.errstate(over="ignore", invalid="ignore"):
            return wrap_array(np.floor(array.astype(np.float64, copy=False) + 0.5))
    if name in {"Array.gamma", "Array.erf", "Array.erfc"}:
        function = {
            "Array.gamma": math.gamma,
            "Array.erf": math.erf,
            "Array.erfc": math.erfc,
        }[name]
        return wrap_array(_mapped_math(array, function, name))

    kernel = _NUMPY_KERNELS[name]
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        result = kernel(array.astype(np.float64, copy=False))
    return wrap_array(result)
