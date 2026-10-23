"""Bounded finite evaluation for discrete scalar reducer leaves."""
from __future__ import annotations

import math

from .aggregate_statistics_histogram import aggregate_histogram
from .aggregate_statistics_values import (
    MAX_EXACT_INTEGER,
    MAX_PUBLIC_BYTES,
    _scalar,
    charge,
    result_scalar,
)
from .composed_reducer_output import _owned_value
from .finite_reducer_scan import scan_inputs
from .ir import fail


DISCRETE_REDUCER_OUTPUTS = {
    "countEvery": ("count",),
    "countDistinct": ("count",),
    "countDistinctNonNull": ("count",),
    "firstNonNull": ("first",),
    "lastNonNull": ("last",),
    "countRuns": ("count",),
    "frequencyHistogram": ("histogram",),
    "allNonZero": ("all",),
    "anyNonZero": ("any",),
    "and": ("all",),
    "or": ("any",),
    "bitwiseAnd": ("bitwiseAnd",),
    "bitwiseOr": ("bitwiseOr",),
}


def _typed_identity(translator, value, reducer_name):
    if value is None:
        return ("null",)
    value = _scalar(value, f"Reducer.{reducer_name}")
    if type(value) is str:
        charge(translator, len(value), f"Reducer.{reducer_name} string hash")
        return ("string", value)
    if type(value) is bool:
        return ("boolean", value)
    # The exact integer check in _scalar makes this conversion lossless. Python
    # equality then intentionally identifies numeric 1 and 1.0 as one value.
    return ("number", float(value))


def _identity_reducer(translator, name, values):
    include_null = name == "countDistinct"
    # Reserve bounded set growth before constructing it. Every row has already
    # been validated, so this path never hides an invalid later row.
    charge(translator, 1 + len(values) * 2, f"Reducer.{name} distinct work")
    distinct = set()
    for value in values:
        if value is None and not include_null:
            continue
        distinct.add(_typed_identity(translator, value, name))
    return len(distinct)


def _count_runs(translator, values):
    charge(translator, 1 + len(values), "Reducer.countRuns run scan")
    runs = 0
    previous = None
    have_previous = False
    for value in values:
        if value is None:
            continue
        identity = _typed_identity(translator, value, "countRuns")
        if not have_previous or identity != previous:
            runs += 1
        previous = identity
        have_previous = True
    return runs


def _numeric_values(translator, name, values, *, integers=False):
    charge(translator, 1 + len(values) * 2, f"Reducer.{name} numeric scan and copy")
    output = []
    for value in values:
        if value is None:
            continue
        if type(value) not in (int, float):
            expected = "exact integer-valued numbers" if integers else "numbers"
            fail(f"Reducer.{name} requires finite {expected} or null")
        if type(value) is int:
            if value < -MAX_EXACT_INTEGER or value > MAX_EXACT_INTEGER:
                fail(f"Reducer.{name} integers must be within the exact ±2^53 range")
            number = value
        else:
            if not math.isfinite(value):
                fail(f"Reducer.{name} requires finite numbers or null")
            number = value
        if integers:
            if type(number) is float:
                if not number.is_integer():
                    fail(f"Reducer.{name} requires exact integer-valued numbers")
                if abs(number) > MAX_EXACT_INTEGER:
                    fail(f"Reducer.{name} integers must be within the exact ±2^53 range")
                number = int(number)
        output.append(number)
    return output


def _entry(translator, name, value, *, scalar=True):
    if scalar:
        value = result_scalar(translator, value, f"Reducer.{name}")
    return [(DISCRETE_REDUCER_OUTPUTS[name][0], value)]


def reduce_discrete_leaf(translator, name, values):
    """Apply one named single-input discrete reducer to at most 1000 values."""
    if type(name) is not str:
        fail("Discrete reducer name must be a string")
    if name.startswith("Reducer."):
        name = name.removeprefix("Reducer.")
    if name not in DISCRETE_REDUCER_OUTPUTS:
        fail(f"Unsupported discrete reducer leaf: {name}")
    scan_inputs(translator, values)
    # Charge the fixed output key before reduction or dictionary construction.
    charge(translator, 1 + len(DISCRETE_REDUCER_OUTPUTS[name][0]),
           f"Reducer.{name} output name")

    if name == "countEvery":
        return _entry(translator, name, len(values))
    if name in {"countDistinct", "countDistinctNonNull"}:
        return _entry(translator, name, _identity_reducer(translator, name, values))
    if name == "countRuns":
        return _entry(translator, name, _count_runs(translator, values))
    if name in {"firstNonNull", "lastNonNull"}:
        charge(translator, 1 + 2 * len(values), f"Reducer.{name} selection and copy")
        selected = None
        found = False
        for value in values:
            if value is not None:
                selected = value
                found = True
                if name == "firstNonNull":
                    break
        if not found:
            selected = None
        owned = _owned_value(translator, selected) if selected is not None else None
        return _entry(translator, name, owned, scalar=owned is None)
    if name == "frequencyHistogram":
        result = aggregate_histogram(translator, values)
        return _entry(translator, name, result, scalar=False)
    if name in {"allNonZero", "anyNonZero", "and", "or"}:
        numbers = _numeric_values(translator, name, values)
        all_inputs = name in {"allNonZero", "and"}
        result = int(all(value != 0 for value in numbers)) if all_inputs else int(
            any(value != 0 for value in numbers)
        )
        return _entry(translator, name, result)
    if name in {"bitwiseAnd", "bitwiseOr"}:
        numbers = _numeric_values(translator, name, values, integers=True)
        charge(translator, 1 + len(numbers), f"Reducer.{name} bitwise fold")
        if name == "bitwiseAnd":
            result = -1
            for number in numbers:
                result &= number
        else:
            result = 0
            for number in numbers:
                result |= number
        if result < -MAX_EXACT_INTEGER or result > MAX_EXACT_INTEGER:
            fail(f"Reducer.{name} result exceeds the exact ±2^53 integer range")
        return _entry(translator, name, result)
    fail(f"Unsupported discrete reducer leaf: {name}")
