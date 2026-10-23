"""Exact finite numeric kernels and output assembly for static Array.reduce."""
from __future__ import annotations

import math

import numpy as np

from .aggregate_statistics_numeric import numeric_dispersion
from .array_core import charge_array, finite_float_sum, wrap_array
from .ir import fail


_WORK_PER_OPERATION = {
    "sum": 1,
    "mean": 1,
    "min": 1,
    "max": 1,
    "count": 1,
    "first": 1,
    "last": 1,
    "median": None,
    "sd": 2,
    "stdDev": 2,
    "variance": 2,
    "sampleVariance": 2,
    # Zero pre-scan plus bounded factor scan, including arithmetic checks.
    "product": 4,
}
_INTEGER_OPERATIONS = frozenset({
    "sum", "min", "max", "count", "first", "last", "product",
})


def _valid_array(array):
    if array.dtype.kind not in {"i", "u", "f"}:
        fail("Static Array reductions require finite numeric values")
    if array.dtype.kind == "f":
        if not np.isfinite(array).all():
            fail("Static Array reductions require finite numeric values")
    else:
        for value in array.flat:
            if abs(int(value)) > 2**53:
                fail("Static Array integer input exceeds the exact Float64 domain")


def _mean(values):
    if len(values) == 0:
        fail("Static Array reductions require at least one value")
    return finite_float_sum(values, len(values))


def _product(values, integer_input):
    if integer_input:
        # A later zero makes the exact product zero even when the preceding
        # factors would overflow. Scan for it before multiplying so this case
        # never constructs a large arbitrary-precision intermediate.
        if any(int(value) == 0 for value in values):
            return 0
        result = 1
        for value in values:
            factor = int(value)
            if abs(result) > (2**53) // abs(factor):
                fail("Static Array integer result exceeds the exact Float64 domain")
            result *= factor
        return result
    negative = False
    has_zero = False
    for value in values:
        value = float(value)
        negative ^= math.copysign(1.0, value) < 0
        has_zero |= value == 0.0
    if has_zero:
        return math.copysign(0.0, -1.0 if negative else 1.0)

    significand, exponent = 1.0, 0
    for value in values:
        factor, factor_exponent = math.frexp(abs(float(value)))
        significand *= factor
        significand, adjustment = math.frexp(significand)
        exponent += factor_exponent + adjustment
    try:
        result = math.ldexp(significand, exponent)
    except OverflowError:
        fail("Static Array product exceeds the finite Float64 range")
    if not math.isfinite(result):
        fail("Static Array product exceeds the finite Float64 range")
    return -result if negative else result


def _statistic(values, operation, integer_input):
    if operation == "count":
        return len(values)
    if operation == "sum":
        if integer_input:
            result = sum(int(value) for value in values)
            if abs(result) > 2**53:
                fail("Static Array integer result exceeds the exact Float64 domain")
            return result
        return finite_float_sum(values)
    if operation == "mean":
        return _mean(values)
    if operation == "min":
        return min(value.item() if hasattr(value, "item") else value for value in values)
    if operation == "max":
        return max(value.item() if hasattr(value, "item") else value for value in values)
    if operation == "first":
        return values[0].item() if hasattr(values[0], "item") else values[0]
    if operation == "last":
        value = values[-1]
        return value.item() if hasattr(value, "item") else value
    if operation == "median":
        ordered = sorted(
            value.item() if hasattr(value, "item") else value for value in values
        )
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return _mean(ordered[middle - 1:middle + 1])
    if operation == "product":
        return _product(values, integer_input)
    if operation in {"sd", "stdDev", "variance", "sampleVariance"}:
        sample = operation in {"sd", "sampleVariance"}
        want_sd = operation in {"sd", "stdDev"}
        result = numeric_dispersion(
            values.tolist(), sample=sample, standard_deviation=want_sd,
        )
        if result is None:
            label = "Sample variance" if operation == "sampleVariance" else "Sample standard deviation"
            fail(f"{label} requires at least two Array values")
        if not math.isfinite(result):
            fail("Static Array statistic exceeds the finite Float64 domain")
        return result
    fail(f"Unsupported static Array numeric reducer: {operation}")


def _work(array_size, output_cells, reduction_count, retained, operations):
    """Reserve scans, grouping, reducer passes and owned outputs before allocation."""
    work = 2 * array_size + 2 * output_cells + len(retained) + 1
    median_work = max(1, math.ceil(math.log2(reduction_count)))
    for _, operation in operations:
        per_value = _WORK_PER_OPERATION.get(operation)
        if per_value is None:
            per_value = median_work
        work += array_size * per_value
    return work


def _gather_groups(array, axes, field_axis, reduced_count, retained, group_count, input_count):
    field_axes = () if field_axis is None else (field_axis,)
    order = (*retained, *field_axes, *axes)
    grouped = np.transpose(array, order)
    return grouped.reshape(group_count, input_count, reduced_count)


def _assemble(results, shape, axes, field_axis, retained, output_count):
    present_axes = (*retained, *((field_axis,) if field_axis is not None else ()))
    present_shape = tuple(shape[axis] for axis in retained)
    if field_axis is not None:
        present_shape += (output_count,)
    ordered_axes = (*present_axes, *axes)
    ordered_shape = (*present_shape, *((1,) * len(axes)))
    values = results.reshape(ordered_shape)
    permutation = tuple(ordered_axes.index(axis) for axis in range(len(shape)))
    if permutation != tuple(range(len(shape))):
        values = np.transpose(values, permutation)
    return values


def reduce_array(translator, array, axes, field_axis, reduced_count,
                 output_shape, output_cells, retained, group_count, operations):
    """Reduce each retained cell independently, preserving the array rank."""
    output_count = len(operations)
    integer_input = array.dtype.kind in {"i", "u"}
    if reduced_count == 1 and any(
            operation in {"sd", "sampleVariance"} for _, operation in operations):
        fail("Sample statistics require at least two Array values")
    work = _work(
        int(array.size), output_cells, reduced_count, retained, operations,
    )
    charge_array(translator, work)
    _valid_array(array)

    groups = _gather_groups(
        array, axes, field_axis, reduced_count, retained, group_count,
        1 if field_axis is None else array.shape[field_axis],
    )
    all_integer = integer_input and all(
        operation in _INTEGER_OPERATIONS for _, operation in operations
    )
    count_only = all(operation == "count" for _, operation in operations)
    result_dtype = np.int64 if all_integer or count_only else np.float64
    results = np.empty((group_count, output_count), dtype=result_dtype)
    for group in range(group_count):
        values = groups[group, 0, :]
        for output_index, (_, operation) in enumerate(operations):
            result = _statistic(values, operation, integer_input)
            if result_dtype is np.int64 and abs(int(result)) > 2**53:
                fail("Static Array integer result exceeds the exact Float64 domain")
            results[group, output_index] = result

    arranged = _assemble(
        results, array.shape, axes, field_axis, retained, output_count,
    )
    if tuple(arranged.shape) != tuple(output_shape):
        fail("Array.reduce produced an unexpected output shape")
    return wrap_array(arranged)
