"""Numerical kernels for fixed-bin histogram reducer leaves."""
from __future__ import annotations

from fractions import Fraction
import math
import numpy as np

from .array_core import wrap_array
from .histogram_reducer_spec import (
    MAX_EXACT_INTEGER,
    MAX_HISTOGRAM_ROWS,
    MAX_PUBLIC_JSON_BYTES,
    HistogramReducerLeaf,
    _charge,
    _shape,
    describe_histogram_reducer,
)
from .ir import fail


def _exact_scalar(value, label: str) -> Fraction | None:
    if value is None:
        return None
    if type(value) is int:
        if not -MAX_EXACT_INTEGER <= value <= MAX_EXACT_INTEGER:
            fail(f"{label} inputs must be within the exact ±2^53 integer range")
        return Fraction(value)
    if type(value) is not float or not math.isfinite(value):
        fail(f"{label} inputs must be finite numbers or null")
    return Fraction.from_float(value)


def _edge_values(minimum: float, maximum: float, steps: int) -> list[float]:
    low, high = Fraction.from_float(minimum), Fraction.from_float(maximum)
    width = (high - low) / steps
    return [minimum if index == 0 else float(low + width * index)
            for index in range(steps)]


def _bin(value: Fraction, minimum: float, maximum: float, steps: int) -> int | None:
    low, high = Fraction.from_float(minimum), Fraction.from_float(maximum)
    if value < low or value >= high:
        return None
    return int((value - low) * steps / (high - low))


def reduce_histogram_reducer(translator, leaf, records) -> list[tuple[str, object]]:
    """Reduce finite 1- or 2-scalar records into detached readonly arrays."""
    input_count, outputs = describe_histogram_reducer(translator, leaf)
    if type(records) is not list or len(records) > MAX_HISTOGRAM_ROWS:
        fail("Fixed histogram reducers require at most 1000 input rows")
    bins, matrix_cells, output_cells = _shape(leaf)
    dimensions = input_count
    json_reserve = 40 * output_cells + 2 * output_cells + sum(map(len, outputs)) + 64
    if json_reserve > MAX_PUBLIC_JSON_BYTES:
        fail("Fixed histogram outputs exceed the 1 MB public JSON limit")
    work = (1 + len(records) * (1 + 3 * dimensions) + 2 * bins
            + 2 * matrix_cells + 2 * output_cells + sum(map(len, outputs)))
    _charge(translator, work, "Fixed histogram evaluation")

    checked: list[tuple[Fraction | None, ...]] = []
    for row in records:
        if type(row) is not list or len(row) != dimensions:
            fail(f"Fixed histogram records require exactly {dimensions} scalar inputs")
        checked.append(tuple(
            _exact_scalar(value, leaf.name) for value in row
        ))

    axes = [
        _edge_values(minimum, maximum, steps)
        for minimum, maximum, steps in zip(leaf.minimums, leaf.maximums, leaf.steps)
    ]
    if dimensions == 1:
        counts = np.zeros(leaf.steps[0], dtype=np.int64)
        minimum, maximum, steps = leaf.minimums[0], leaf.maximums[0], leaf.steps[0]
        for (value,) in checked:
            if value is not None:
                index = _bin(value, minimum, maximum, steps)
                if index is not None:
                    counts[index] += 1
        if leaf.cumulative:
            counts = np.cumsum(counts, dtype=np.int64)
        result = np.empty((steps, 2), dtype=np.float64)
        result[:, 0] = axes[0]
        result[:, 1] = counts
        return [(outputs[0], wrap_array(result))]

    counts = np.zeros(leaf.steps, dtype=np.int64)
    for x_value, y_value in checked:
        if x_value is None or y_value is None:
            continue
        x_index = _bin(x_value, leaf.minimums[0], leaf.maximums[0], leaf.steps[0])
        y_index = _bin(y_value, leaf.minimums[1], leaf.maximums[1], leaf.steps[1])
        if x_index is not None and y_index is not None:
            counts[x_index, y_index] += 1
    return [
        (outputs[0], wrap_array(counts)),
        (outputs[1], wrap_array(np.asarray(axes[0], dtype=np.float64))),
        (outputs[2], wrap_array(np.asarray(axes[1], dtype=np.float64))),
    ]
