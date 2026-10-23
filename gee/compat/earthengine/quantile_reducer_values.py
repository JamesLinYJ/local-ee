"""Exact bounded kernels for finite percentile, interval-mean and mode leaves."""
from __future__ import annotations

from fractions import Fraction
import math

from .ir import fail
from .quantile_reducer_spec import (
    MAX_EXACT_INTEGER,
    MAX_QUANTILE_OUTPUT_BYTES,
    MAX_QUANTILE_ROWS,
    MAX_QUANTILE_SCALAR_BITS,
    QuantileReducerLeaf,
    _charge,
    describe_quantile_reducer,
)


def _exact_scalar(value, label: str) -> Fraction | None:
    if value is None:
        return None
    if type(value) is int:
        if value.bit_length() > 54:
            fail(f"{label} integers must be within the exact ±2^53 range")
        if not -MAX_EXACT_INTEGER <= value <= MAX_EXACT_INTEGER:
            fail(f"{label} integers must be within the exact ±2^53 range")
        exact = Fraction(value)
    elif type(value) is float and math.isfinite(value):
        exact = Fraction.from_float(value)
    else:
        fail(f"{label} values must be finite numbers or null")
    if exact.numerator.bit_length() + exact.denominator.bit_length() > MAX_QUANTILE_SCALAR_BITS:
        fail(f"{label} rational value exceeds the bounded scalar size")
    return exact


def _sort_work(count: int) -> int:
    return 0 if count < 2 else count * (count - 1).bit_length()


_SCALAR_RATIONAL_LIMBS = (MAX_QUANTILE_SCALAR_BITS + 63) // 64


def _as_finite_float(value: Fraction, label: str) -> float:
    try:
        result = float(value)
    except (OverflowError, ValueError):
        fail(f"{label} result is outside the finite Float64 range")
    if not math.isfinite(result):
        fail(f"{label} result is outside the finite Float64 range")
    return result


def _quantile(sorted_values: list[Fraction], percentile: Fraction) -> Fraction:
    """Linear interpolation at p*(n-1)/100, entirely in rational arithmetic."""
    position = percentile * (len(sorted_values) - 1) / 100
    lower = position.numerator // position.denominator
    remainder = position - lower
    if remainder == 0:
        return sorted_values[lower]
    return (sorted_values[lower] * (1 - remainder)
            + sorted_values[lower + 1] * remainder)


def _mean(values: list[Fraction]) -> Fraction:
    return sum(values, Fraction()) / len(values)


def _reserve_output(translator, outputs: tuple[str, ...]) -> None:
    # A finite binary64's repr is at most 24 characters; reserve that plus
    # separators and the complete output-name copy before running the kernel.
    # JSON string escaping can expand each character to six ASCII bytes.
    byte_reserve = 2 + sum(6 * len(name) + 32 for name in outputs)
    if byte_reserve > MAX_QUANTILE_OUTPUT_BYTES:
        fail("Quantile reducer output exceeds the 1 MB JSON size limit")
    _charge(translator, 1 + sum(len(name) + 3 for name in outputs),
            "Quantile reducer output names and copies")


def reduce_quantile_reducer(translator, leaf, records) -> list[tuple[str, float | None]]:
    """Reduce at most 1000 one-scalar rows under the shared 50000-step cap."""
    input_count, outputs = describe_quantile_reducer(translator, leaf)
    if type(leaf) is not QuantileReducerLeaf or input_count != 1:
        fail("Quantile reducer requires a canonical one-input leaf")
    if type(records) is not list or len(records) > MAX_QUANTILE_ROWS:
        fail("Quantile reducers require at most 1000 input rows")
    _reserve_output(translator, outputs)
    # Reserve the full row/shape walk before looking at any row or value.
    _charge(
        translator,
        1 + len(records) * (3 + 1 + _SCALAR_RATIONAL_LIMBS),
        "Quantile reducer row scan and rational conversion",
    )
    values: list[Fraction] = []
    for row in records:
        if type(row) is not list or len(row) != 1:
            fail(f"{leaf.name} rows must contain exactly one scalar input")
        value = _exact_scalar(row[0], leaf.name)
        if value is not None:
            values.append(value)
    if leaf.max_raw is not None and len(values) > leaf.max_raw:
        fail(f"{leaf.name} raw input count exceeds maxRaw")

    count = len(values)
    if leaf.name == "Reducer.mode":
        _charge(translator, 4 * count, "Mode value counting")
        counts: dict[Fraction, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        if counts:
            highest = max(counts.values())
            result_values = (_as_finite_float(
                min(value for value, size in counts.items() if size == highest),
                leaf.name,
            ),)
        else:
            result_values = (None,)
    else:
        sort_cost = _sort_work(count)
        if leaf.name == "Reducer.intervalMean":
            scan_cost = 4 * count + 8
        else:
            scan_cost = 4 * len(outputs) + 4
        _charge(translator, sort_cost + scan_cost,
                "Quantile sorting and interpolation")
        ordered = sorted(values)
        if not ordered:
            result_values = tuple(None for _ in outputs)
        elif leaf.name == "Reducer.percentile":
            result_values = tuple(
                _as_finite_float(_quantile(ordered, percentile), leaf.name)
                for percentile in leaf.percentiles
            )
        else:
            lower = _quantile(ordered, leaf.percentiles[0])
            upper = _quantile(ordered, leaf.percentiles[1])
            selected = [value for value in ordered if lower <= value <= upper]
            result_values = (
                None if not selected else
                _as_finite_float(_mean(selected), leaf.name),
            )

    if len(result_values) != len(outputs):
        fail("Quantile reducer produced an invalid output shape")
    # Return new outer tuples so callers never receive the leaf's output tuple.
    return [(str(name), value) for name, value in zip(outputs, result_values)]
