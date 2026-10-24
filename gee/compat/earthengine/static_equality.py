"""Bounded structural equality for finite static values, never IR dataclasses.

Numeric scalars preserve exact int/float value equality, with booleans distinct.
Arrays retain dtype and shape and are never broadcast or coerced to Lists. This
local typed-array policy has not been compared with Google server equality.
"""
from __future__ import annotations

import math

import numpy as np

from .array_values import MAX_ARRAY_CELLS, MAX_ARRAY_RANK, StaticArray
from .ir import fail


MAX_COMPARISON_DEPTH = 96
MAX_STATIC_VALUES = 10000
MAX_COMPARISON_WORK = 50000


def _charge(translator, work=1):
    if translator.steps + work > MAX_COMPARISON_WORK:
        fail("Static equality exceeds the compilation work budget")
    translator.steps += work


def _validate(translator, value, depth=0, *, exact_integers=False):
    _charge(translator)
    if depth > MAX_COMPARISON_DEPTH:
        fail("Static equality exceeds the nesting limit")
    from .geometry_values import GeometryValue

    kind = dict if type(value) is GeometryValue else type(value)
    if type(value) is int:
        if exact_integers and abs(value) > 2**53:
            fail("Static equality requires integers in the exact Float64 domain")
        return
    if type(value) in (type(None), bool, str):
        return
    if type(value) is float:
        if not math.isfinite(value):
            fail("Static equality requires finite numbers")
        return
    if type(value) is StaticArray:
        data = value.data
        if (not isinstance(data, np.ndarray) or data.size > MAX_ARRAY_CELLS
                or data.ndim > MAX_ARRAY_RANK or data.dtype.kind not in "iuf"):
            fail("Static equality requires a bounded numeric Array")
        _charge(translator, data.size)
        if exact_integers and data.dtype.kind in "iu":
            if data.dtype.kind == "u":
                unsafe_integer = np.any(data > 2**53)
            else:
                unsafe_integer = np.any((data < -(2**53)) | (data > 2**53))
            if bool(unsafe_integer.item()):
                fail("Static equality requires integers in the exact Float64 domain")
        if not np.isfinite(data).all():
            fail("Static equality requires finite Array cells")
        return
    if kind in (list, dict):
        if len(value) > MAX_STATIC_VALUES:
            fail("Static equality supports at most 10000 container values")
        if kind is dict:
            _charge(translator, len(value))
            if any(type(key) is not str for key in value):
                fail("Static equality requires Dictionary string keys")
        for child in value.values() if kind is dict else value:
            _validate(translator, child, depth + 1, exact_integers=exact_integers)
        return
    fail(f"Static equality does not support {type(value).__name__} values")


def _equal(translator, left, right):
    _charge(translator)
    if type(left) in (int, float) and type(right) in (int, float):
        # Both Python encodings represent EE Numbers. Python compares int/float
        # values without first rounding a large integer to the float's precision.
        return left == right
    from .geometry_values import GeometryValue

    left_kind = dict if type(left) is GeometryValue else type(left)
    right_kind = dict if type(right) is GeometryValue else type(right)
    if left_kind is not right_kind:
        return False
    if left_kind is StaticArray:
        a, b = left.data, right.data
        if a.shape != b.shape or a.dtype != b.dtype:
            return False
        _charge(translator, a.size)
        return bool(np.array_equal(a, b))
    if left_kind is list:
        return len(left) == len(right) and all(
            _equal(translator, a, b) for a, b in zip(left, right)
        )
    if left_kind is dict:
        _charge(translator, len(left) + len(right))
        return left.keys() == right.keys() and all(
            _equal(translator, left[key], right[key]) for key in left
        )
    return left == right


def static_equal(translator, left, right, *, exact_integers=False):
    """Compare fully validated static values against the shared work budget."""
    _validate(translator, left, exact_integers=exact_integers)
    _validate(translator, right, exact_integers=exact_integers)
    return _equal(translator, left, right)


def contains_value(translator, values, element):
    if type(values) is not list:
        fail("List.contains requires a static List")
    _validate(translator, values)
    _validate(translator, element)
    return any(_equal(translator, candidate, element) for candidate in values)


def distinct_values(translator, values):
    if type(values) is not list:
        fail("List.distinct requires a static List")
    _validate(translator, values)
    result = []
    for value in values:
        if not any(_equal(translator, value, previous) for previous in result):
            result.append(value)
    return result
