"""Closed operation and input-arity contract for local EE pixel math."""
from __future__ import annotations


PIXEL_MATH_ARITIES = {
    "asin": 1,
    "acos": 1,
    "atan": 1,
    "atan2": 2,
    "sinh": 1,
    "cosh": 1,
    "tanh": 1,
    "cbrt": 1,
    "signum": 1,
    "gamma": 1,
    "digamma": 1,
    "trigamma": 1,
    "erf": 1,
    "erfc": 1,
    "erfInv": 1,
    "erfcInv": 1,
}
PIXEL_MATH_OPERATIONS = tuple(PIXEL_MATH_ARITIES)


def validate_pixel_math_operation(operation):
    """Return a supported wire operation, rejecting non-string aliases."""
    if type(operation) is not str or operation not in PIXEL_MATH_ARITIES:
        raise ValueError("Pixel math operation must be one of the supported operation names")
    return operation


def pixel_math_arity(operation):
    """Return the fixed input-band count for one validated operation."""
    return PIXEL_MATH_ARITIES[validate_pixel_math_operation(operation)]


def validate_pixel_math_arity(operation, arity):
    """Check a declared arity against the closed operation contract."""
    expected = pixel_math_arity(operation)
    if type(arity) is not int or arity != expected:
        raise ValueError(f"Pixel math operation {operation!r} requires {expected} input band(s)")
    return expected
