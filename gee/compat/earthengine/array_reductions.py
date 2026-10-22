"""Bounded single-output finite Array reductions and prefix accumulations."""
from __future__ import annotations

import math

import numpy as np

from .array_arithmetic import exact_integer_result
from .array_core import charge_array, finite_float_sum, require_array, wrap_array
from .ir import Reducer, fail, integer


ARRAY_REDUCTION_FUNCTIONS = frozenset({"Array.reduce", "Array.accum"})
_REDUCERS = frozenset({"sum", "mean", "min", "max", "count", "median", "sd"})


def _reducer(value):
    if not isinstance(value, Reducer) or value.name not in _REDUCERS or value.unweighted:
        fail("Static Array reductions require a supported single-output scalar Reducer")
    return value.name


def _axis(value, array):
    axis = integer(value, "Array reduction axis", 0)
    if axis >= array.ndim:
        fail("Array reduction axis is outside the array rank")
    return axis


def _axes(value, array):
    if not isinstance(value, list) or not value or len(value) > array.ndim:
        fail("Array.reduce requires a nonempty list of axes")
    axes = tuple(_axis(axis, array) for axis in value)
    if len(set(axes)) != len(axes):
        fail("Array.reduce axes must be unique")
    return axes


def _group_statistic(array, axes, reducer):
    remaining = [axis for axis in range(array.ndim) if axis not in axes]
    count = math.prod(array.shape[axis] for axis in axes)
    groups = np.transpose(array.astype(np.float64), [*remaining, *axes]).reshape(-1, count)
    shape = tuple(1 if axis in axes else length for axis, length in enumerate(array.shape))
    results = []
    for row in groups:
        if reducer == "sum":
            results.append(finite_float_sum(row))
        elif reducer == "median":
            ordered = np.sort(row)
            middle = len(row) // 2
            results.append(float(ordered[middle]) if len(row) % 2 else
                           finite_float_sum(ordered[middle - 1:middle + 1], 2))
        else:
            results.append(_row_statistic(row, reducer == "sd"))
    return np.array(results).reshape(shape)


def _row_statistic(row, sample_sd):
    if not sample_sd:
        return finite_float_sum(row, len(row))
    # Subtract an observed anchor first: unlike subtracting a rounded large
    # mean, this preserves small differences on a large common offset. Fall
    # back to scaling only when opposite extreme values overflow differences.
    for scale in (1.0, float(np.max(np.abs(row))) or 1.0):
        with np.errstate(over="ignore", invalid="ignore"):
            values = row if scale == 1.0 else row / scale
            anchor = float(values[0])
            differences = values - anchor
        if not np.isfinite(differences).all():
            continue
        delta = finite_float_sum(differences, len(row))
        with np.errstate(over="ignore", invalid="ignore"):
            deviations = differences - delta
        if not np.isfinite(deviations).all():
            continue
        spread = float(np.max(np.abs(deviations)))
        if spread == 0:
            return 0.0
        norm = math.hypot(*(float(value) / spread for value in deviations)) / math.sqrt(len(row) - 1)
        return (norm * spread) * scale
    fail("Static Array statistic exceeds the finite Float64 domain")


def _reduce(translator, arguments):
    translator.allowed(arguments, {"array", "reducer", "axes", "fieldAxis"})
    if arguments.get("fieldAxis") is not None:
        fail("Static Array.reduce fieldAxis is unsupported")
    array = require_array(arguments["array"])
    if not array.size:
        fail("Empty Array reductions are currently unsupported")
    axes = _axes(arguments.get("axes"), array)
    reducer = _reducer(arguments.get("reducer"))
    count = math.prod(array.shape[axis] for axis in axes)
    output_shape = tuple(1 if axis in axes else length for axis, length in enumerate(array.shape))
    work = int(array.size) * (max(1, math.ceil(math.log2(count))) if reducer == "median" else 4)
    charge_array(translator, work + math.prod(output_shape))
    if reducer == "sd" and count < 2:
        fail("Sample standard deviation requires at least two Array values")
    with np.errstate(over="ignore", invalid="ignore"):
        if reducer == "count":
            result = np.full(output_shape, count, dtype=np.int64)
        elif reducer == "sum":
            if array.dtype.kind in {"i", "u"}:
                result = exact_integer_result(np.sum(array.astype(object), axis=axes, keepdims=True))
            else:
                result = _group_statistic(array, axes, "sum")
        elif reducer in {"mean", "sd", "median"}:
            result = _group_statistic(array, axes, reducer)
        else:
            function = {"min": np.min, "max": np.max}[reducer]
            result = function(array, axis=axes, keepdims=True)
    return wrap_array(result)


def _accum(translator, arguments):
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
