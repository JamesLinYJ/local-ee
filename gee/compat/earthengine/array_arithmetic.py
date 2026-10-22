"""Finite, shape-exact elementwise Array arithmetic without broadcasting."""
from __future__ import annotations

import numpy as np

from .array_core import charge_array, require_array, wrap_array
from .ir import fail


ARRAY_ARITHMETIC_FUNCTIONS = frozenset({
    "Array.add", "Array.subtract", "Array.multiply", "Array.divide",
    "Array.abs", "Array.sqrt", "Array.hypot", "Array.atan2",
})
_EXACT_BINARY = {"Array.add": np.add, "Array.subtract": np.subtract,
                 "Array.multiply": np.multiply}


def exact_integer_result(result):
    """Check Python-integer intermediates before narrowing back to int64."""
    result = np.asarray(result, dtype=object)
    if any(abs(value) > 2**53 for value in result.flat):
        fail("Static Array integer result exceeds the exact Float64 domain")
    return np.asarray(result, dtype=np.int64)


def invoke_arithmetic(translator, name, arguments):
    if name not in ARRAY_ARITHMETIC_FUNCTIONS:
        fail(f"Unsupported static Array arithmetic: {name}")
    if name in {"Array.abs", "Array.sqrt"}:
        translator.allowed(arguments, {"input"})
        array = require_array(arguments["input"])
        charge_array(translator, int(array.size) * 2 + 1)
        if name == "Array.sqrt":
            if np.any(array < 0):
                fail("Static Array.sqrt requires nonnegative real values")
            result = np.sqrt(array.astype(np.float64))
        elif array.dtype.kind in {"i", "u"}:
            result = exact_integer_result(np.abs(array.astype(object)))
        else:
            result = np.abs(array)
        return wrap_array(result)

    translator.allowed(arguments, {"left", "right"})
    if name in {"Array.hypot", "Array.atan2"}:
        missing = {"left", "right"} - arguments.keys()
        if missing:
            fail(f"{name} requires {', '.join(sorted(missing))}")
    left, right = (require_array(arguments[key]) for key in ("left", "right"))
    if left.shape != right.shape:
        fail("Static Array arithmetic currently requires the same shape; broadcasting is unsupported")
    if name in {"Array.hypot", "Array.atan2"}:
        charge_array(translator, int(left.size) * 5 + 1)
        with np.errstate(over="ignore", invalid="ignore"):
            x, y = left.astype(np.float64), right.astype(np.float64)
            # The pinned Array.atan2 documentation calls right the y values.
            result = np.hypot(x, y) if name == "Array.hypot" else np.arctan2(y, x)
        return wrap_array(result)
    charge_array(translator, int(left.size) * 3 + 1)
    if name != "Array.divide" and left.dtype.kind in {"i", "u"} and right.dtype.kind in {"i", "u"}:
        # Object arithmetic uses bounded Python integers, preventing int64 wrap
        # before the explicit exact-domain check. Input scalars are <=2^53.
        result = _EXACT_BINARY[name](left.astype(object), right.astype(object))
        return wrap_array(exact_integer_result(result))
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        if name == "Array.divide":
            # The pinned signature explicitly specifies zero for division by
            # zero. Keep that rule without producing temporary infinities.
            result = np.divide(left.astype(np.float64), right.astype(np.float64),
                               out=np.zeros(left.shape, dtype=np.float64), where=right != 0)
        else:
            result = _EXACT_BINARY[name](left.astype(np.float64), right.astype(np.float64))
    return wrap_array(result)
