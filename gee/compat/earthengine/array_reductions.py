"""Finite Array.reduce and prefix accumulations over static arrays."""
from __future__ import annotations

import numpy as np

from .array_arithmetic import exact_integer_result
from .array_core import (
    MAX_ARRAY_CELLS, MAX_ARRAY_RANK, charge_array, require_array, wrap_array,
)
from .array_numeric_reductions import reduce_array
from .array_reduction_layout import reduction_layout
from .ir import Reducer, fail, integer


ARRAY_REDUCTION_FUNCTIONS = frozenset({"Array.reduce", "Array.accum"})
_ACCUM_REDUCERS = frozenset({"sum", "mean", "min", "max", "count", "median", "sd"})


def _reducer(value):
    if (not isinstance(value, Reducer) or value.name not in _ACCUM_REDUCERS
            or value.unweighted):
        fail("Static Array reductions require a supported single-output scalar Reducer")
    return value.name


def _axis(value, array):
    axis = integer(value, "Array reduction axis", 0)
    if axis >= array.ndim:
        fail("Array reduction axis is outside the array rank")
    return axis


def _reduce(translator, arguments):
    # Reducer descriptors depend on array/table IR types; defer the import until
    # the canonical Array facade is fully initialized to avoid an import cycle.
    from .numeric_reducer_plan import numeric_outputs

    translator.allowed(arguments, {"array", "reducer", "axes", "fieldAxis"})
    array = require_array(arguments["array"])
    if array.ndim > MAX_ARRAY_RANK or array.size > MAX_ARRAY_CELLS:
        fail("Static Array exceeds the 10000-cell / rank-8 input limit")
    if any(length > MAX_ARRAY_CELLS for length in array.shape):
        fail("Static Array exceeds the 10000-cell / rank-8 input limit")
    if not array.size:
        fail("Empty Array reductions are currently unsupported")
    operations = numeric_outputs(translator, arguments.get("reducer"))
    if not operations:
        fail("Array.reduce requires a numeric reducer with at least one output")
    layout = reduction_layout(
        array.shape, arguments.get("axes"), arguments.get("fieldAxis"),
        input_count=1, output_count=len(operations),
    )
    axes, field_axis, reduced_count, output_shape, output_cells, retained, group_count = layout
    return reduce_array(
        translator, array, axes, field_axis, reduced_count, output_shape,
        output_cells, retained, group_count, operations,
    )


def _accum(translator, arguments):
    # Accumulations retain their established single-output sum/min/max subset.
    translator.allowed(arguments, {"array", "axis", "reducer"})
    array = require_array(arguments["array"])
    axis = _axis(arguments.get("axis"), array)
    reducer = "sum" if arguments.get("reducer") is None else _reducer(arguments["reducer"])
    if reducer not in {"sum", "min", "max"}:
        fail("Static Array.accum currently supports sum/min/max only")
    if not array.size:
        fail("Empty Array accumulations are currently unsupported")
    charge_array(translator, int(array.size) * 3 + 1)
    with np.errstate(over="ignore", invalid="ignore"):
        if reducer == "sum" and array.dtype.kind in {"i", "u"}:
            result = exact_integer_result(np.cumsum(array.astype(object), axis=axis))
        elif reducer == "sum":
            result = np.cumsum(array, axis=axis, dtype=np.float64)
        else:
            operation = np.minimum if reducer == "min" else np.maximum
            result = operation.accumulate(array, axis=axis)
    return wrap_array(result)


def invoke_reduction(translator, name, arguments):
    if name == "Array.reduce":
        return _reduce(translator, arguments)
    if name == "Array.accum":
        return _accum(translator, arguments)
    fail(f"Unsupported static Array reduction: {name}")
