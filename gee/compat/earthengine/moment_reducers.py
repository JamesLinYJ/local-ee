"""Closed metadata and bounded finite evaluation for moment reducers."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .ir import fail
from .moment_reducer_values import standardized_moment


MAX_MOMENT_ROWS = 1_000
MAX_MOMENT_NAME_CHARS = 64
MAX_MOMENT_WORK = 50_000
MAX_MOMENT_OUTPUT_BYTES = 1_000_000
MAX_EXACT_INTEGER = 2**53

MOMENT_REDUCER_NAMES = frozenset({
    "Reducer.skew",
    "Reducer.kurtosis",
})
_OUTPUTS = {
    "Reducer.skew": ("skew",),
    "Reducer.kurtosis": ("kurtosis",),
}


@dataclass(frozen=True, slots=True)
class MomentReducerLeaf:
    """Immutable identity for a single-input, single-output moment leaf."""

    name: str


def _charge(translator, work: int, label: str) -> None:
    if type(work) is not int or work < 0 or work > MAX_MOMENT_WORK:
        fail(f"{label} has invalid work accounting")
    if translator is None:
        return
    steps = getattr(translator, "steps", None)
    if type(steps) is not int or steps < 0:
        fail("Moment reducer requires a nonnegative translator work counter")
    if steps + work > MAX_MOMENT_WORK:
        fail("Moment reducer exceeds the shared 50000-step work budget")
    translator.steps = steps + work


def _bounded_text(translator, value, label: str) -> str:
    if type(value) is not str or len(value) > MAX_MOMENT_NAME_CHARS:
        fail(f"{label} must be a bounded string")
    _charge(translator, 1 + len(value), label)
    return value


def make_moment_reducer(translator, name, arguments) -> MomentReducerLeaf:
    """Validate a pinned no-argument reducer call and detach its identity."""
    name = _bounded_text(translator, name, "Moment reducer name")
    if name not in MOMENT_REDUCER_NAMES:
        fail(f"Unsupported moment reducer: {name}")
    if type(arguments) is not dict:
        fail(f"{name} arguments must be a dictionary")
    _charge(translator, 1 + len(arguments), "Moment reducer arguments")
    for key in arguments:
        _bounded_text(translator, key, "Moment reducer argument name")
    translator.allowed(arguments, set())
    return MomentReducerLeaf(name)


def describe_moment_reducer(
    translator, leaf: MomentReducerLeaf,
) -> tuple[int, tuple[str, ...]]:
    """Revalidate a closed descriptor, including deserialized mutations."""
    if type(leaf) is not MomentReducerLeaf:
        fail("Moment reducer leaf has an invalid type")
    name = _bounded_text(translator, leaf.name, "Moment reducer leaf name")
    if name not in MOMENT_REDUCER_NAMES:
        fail("Moment reducer leaf has an invalid canonical name")
    outputs = _OUTPUTS[name]
    _charge(translator, sum(1 + len(output) for output in outputs),
            "Moment reducer outputs")
    return 1, outputs


def _number(value, label: str) -> float | None:
    if value is None:
        return None
    if type(value) is int:
        if value < -MAX_EXACT_INTEGER or value > MAX_EXACT_INTEGER:
            fail(f"{label} integers exceed the exact ±2^53 range")
        return float(value)
    if type(value) is not float or not math.isfinite(value):
        fail(f"{label} values must be finite exact numbers or null")
    return value


def _reserve_work(translator, output: str, row_count: int, input_count: int) -> None:
    # Finite Float64 reprs are bounded to 32 characters. Reserve the complete
    # row walk, worst-case numerical kernel and output work before inspecting
    # rows or allocating the complete-case vector.
    maximum_bytes = 2 + 2 + len(output) + 1 + 32
    if maximum_bytes > MAX_MOMENT_OUTPUT_BYTES:
        fail("Moment reducer output exceeds the 1 MB JSON size limit")
    row_work = 1 + row_count * (input_count + 3)
    kernel_work = 32 * row_count + 48
    output_work = 1 + len(output) + 32
    _charge(
        translator, row_work + kernel_work + output_work,
        "Moment reducer row, kernel and output reservation",
    )


def reduce_moment_reducer(
    translator, leaf: MomentReducerLeaf, records,
) -> list[tuple[str, float | None]]:
    """Reduce one finite column, skipping nulls and validating every row."""
    inputs, outputs = describe_moment_reducer(translator, leaf)
    if type(records) is not list or len(records) > MAX_MOMENT_ROWS:
        fail("Moment reducers support at most 1000 inline rows")

    output = outputs[0]
    _reserve_work(translator, output, len(records), inputs)
    values = []
    for row in records:
        if type(row) is not list or len(row) != inputs:
            fail(f"{leaf.name} rows must have exactly one input")
        value = _number(row[0], leaf.name)
        if value is not None:
            values.append(value)

    if not values:
        result = None
    else:
        order = 3 if leaf.name == "Reducer.skew" else 4
        result = standardized_moment(values, order)
    if result is not None and (type(result) is not float or not math.isfinite(result)):
        fail("Moment reducer produced a non-finite output")
    return [(output, result)]
