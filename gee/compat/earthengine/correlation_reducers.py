"""Closed metadata and bounded finite evaluation for correlation reducers."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .correlation_statistics import (
    MAX_BETA_ITERATIONS,
    kendall_tau_b,
    pearson_correlation,
    pearson_two_sided_p_value,
    spearman_correlation,
)
from .ir import fail
from .trend_statistics import sens_slope


MAX_CORRELATION_ROWS = 1_000
MAX_CORRELATION_INPUTS = 32
MAX_CORRELATION_NAME_CHARS = 64
MAX_CORRELATION_WORK = 50_000
MAX_CORRELATION_OUTPUT_BYTES = 1_000_000
MAX_EXACT_INTEGER = 2**53

CORRELATION_REDUCER_NAMES = frozenset({
    "Reducer.pearsonsCorrelation",
    "Reducer.spearmansCorrelation",
    "Reducer.kendallsCorrelation",
    "Reducer.sensSlope",
})

_OUTPUTS = {
    "Reducer.pearsonsCorrelation": ("correlation", "p-value"),
    "Reducer.spearmansCorrelation": ("correlation",),
    "Reducer.kendallsCorrelation": ("tau",),
    "Reducer.sensSlope": ("slope", "offset"),
}


@dataclass(frozen=True, slots=True)
class CorrelationReducerLeaf:
    """Immutable reducer identity; mutable serialized fields never enter trees."""

    name: str
    num_inputs: int


def _charge(translator, work: int, label: str) -> None:
    if work < 0:
        fail(f"{label} has invalid work accounting")
    if translator is None:
        return
    if type(getattr(translator, "steps", None)) is not int:
        fail("Correlation reducer requires a translator work counter")
    if translator.steps + work > MAX_CORRELATION_WORK:
        fail("Correlation reducer exceeds the shared 50000-step work budget")
    translator.steps += work


def make_correlation_reducer(translator, name, arguments) -> CorrelationReducerLeaf:
    """Build a canonical correlation reducer leaf from the pinned EE call."""
    if type(name) is not str:
        fail("Correlation reducer name must be a string")
    if len(name) > MAX_CORRELATION_NAME_CHARS:
        fail("Correlation reducer name exceeds the bounded length")
    _charge(translator, 1 + len(name), "Correlation reducer name")
    if name not in CORRELATION_REDUCER_NAMES:
        fail(f"Unsupported correlation reducer: {name}")
    if type(arguments) is not dict:
        fail("Correlation reducer arguments must be a dictionary")
    _charge(translator, 1 + len(arguments), "Correlation reducer arguments")
    for key in arguments:
        if type(key) is not str:
            fail("Correlation reducer argument names must be bounded strings")
        if len(key) > MAX_CORRELATION_NAME_CHARS:
            fail("Correlation reducer argument names must be bounded strings")
        _charge(translator, 1 + len(key), "Correlation reducer argument name")
    allowed = {"numInputs"} if name == "Reducer.kendallsCorrelation" else set()
    translator.allowed(arguments, allowed)
    if name == "Reducer.kendallsCorrelation":
        raw_count = arguments.get("numInputs", 1)
        if raw_count is None:
            num_inputs = 1
        elif type(raw_count) is int:
            num_inputs = raw_count
        elif (type(raw_count) is float and math.isfinite(raw_count)
              and raw_count.is_integer()):
            num_inputs = int(raw_count)
        else:
            fail("Reducer.kendallsCorrelation numInputs must be an integer")
        if num_inputs not in (1, 2):
            fail("Reducer.kendallsCorrelation numInputs must be 1 or 2")
    else:
        num_inputs = 2
    return CorrelationReducerLeaf(name, num_inputs)


def describe_correlation_reducer(
    translator, leaf: CorrelationReducerLeaf,
) -> tuple[int, tuple[str, ...]]:
    """Validate every canonical leaf field and return input/output metadata."""
    if type(leaf) is not CorrelationReducerLeaf:
        fail("Correlation reducer leaf has an invalid type")
    name, num_inputs = leaf.name, leaf.num_inputs
    if type(name) is not str:
        fail("Correlation reducer leaf has an invalid canonical name")
    if len(name) > MAX_CORRELATION_NAME_CHARS:
        fail("Correlation reducer leaf has invalid canonical fields")
    _charge(translator, 1 + len(name), "Correlation reducer name validation")
    if name not in CORRELATION_REDUCER_NAMES:
        fail("Correlation reducer leaf has an invalid canonical name")
    if type(num_inputs) is not int:
        fail("Correlation reducer leaf has invalid canonical fields")
    if name == "Reducer.kendallsCorrelation":
        if num_inputs not in (1, 2):
            fail("Correlation reducer Kendall arity must be 1 or 2")
    elif num_inputs != 2:
        fail("Correlation reducer leaf arity does not match its canonical name")
    outputs = _OUTPUTS[name]
    if not 1 <= num_inputs <= MAX_CORRELATION_INPUTS:
        fail("Correlation reducer input arity exceeds the 32-column limit")
    _charge(translator, sum(1 + len(item) for item in outputs),
            "Correlation reducer outputs")
    return num_inputs, outputs


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


def _log_sort_work(count: int) -> int:
    if count < 2:
        return 0
    return count * (count - 1).bit_length()


def _reserve_kernel_work(translator, name, count):
    if name == "Reducer.pearsonsCorrelation":
        p_iterations = 12 * MAX_BETA_ITERATIONS if count >= 3 else 0
        _charge(translator, 20 * count + p_iterations, "Pearson kernel")
    elif name == "Reducer.spearmansCorrelation":
        _charge(translator, 16 * count + 2 * _log_sort_work(count), "Spearman ranking")
    elif name == "Reducer.kendallsCorrelation":
        pair_count = count * (count - 1) // 2
        _charge(translator, 8 * count + 4 * pair_count, "Kendall pair comparisons")
    else:
        pair_count = count * (count - 1) // 2
        slope_sort = _log_sort_work(pair_count)
        _charge(translator, 12 * count + 6 * pair_count + slope_sort
                + _log_sort_work(count), "Sen slope pairs and sorts")


def _output(translator, outputs, values):
    entries = list(zip(outputs, values))
    byte_count = 2
    work = 1
    for name, value in entries:
        if value is not None and (type(value) is not float or not math.isfinite(value)):
            fail("Correlation reducer produced a non-finite output")
        wire_value = "null" if value is None else repr(value)
        byte_count += len(name) + len(wire_value) + 3
        work += 1 + len(name) + len(wire_value)
    if byte_count > MAX_CORRELATION_OUTPUT_BYTES:
        fail("Correlation reducer output exceeds the 1 MB JSON size limit")
    _charge(translator, work, "Correlation reducer output")
    return entries


def reduce_correlation_reducer(translator, leaf, records) -> list[tuple[str, float | None]]:
    """Reduce at most 1000 preflighted rows, validating every non-null field."""
    input_count, outputs = describe_correlation_reducer(translator, leaf)
    if type(records) is not list or len(records) > MAX_CORRELATION_ROWS:
        fail("Correlation reducer supports at most 1000 inline rows")
    # Reserve the entire shape/value walk before inspecting rows or allocating
    # complete-case vectors. The full walk still validates fields in skipped rows.
    _charge(translator, 1 + len(records) * (input_count + 2),
            "Correlation reducer row validation")
    complete = []
    for row in records:
        if type(row) is not list or len(row) != input_count:
            fail(f"{leaf.name} rows must have exactly {input_count} inputs")
        checked = [_number(value, leaf.name) for value in row]
        if all(value is not None for value in checked):
            complete.append(checked)

    count = len(complete)
    _reserve_kernel_work(translator, leaf.name, count)
    if leaf.name == "Reducer.pearsonsCorrelation":
        if count < 2:
            values = (None, None)
        else:
            try:
                coefficient = pearson_correlation(
                    [row[0] for row in complete], [row[1] for row in complete],
                )
                p_value = (
                    pearson_two_sided_p_value(coefficient, count)
                    if coefficient is not None and count >= 3 else None
                )
            except ArithmeticError:
                fail("Reducer.pearsonsCorrelation failed its bounded numeric calculation")
            values = (coefficient, p_value)
    elif leaf.name == "Reducer.spearmansCorrelation":
        values = (spearman_correlation(
            [row[0] for row in complete], [row[1] for row in complete],
        ),)
    elif leaf.name == "Reducer.kendallsCorrelation":
        if input_count == 1:
            x = [float(index) for index in range(count)]
            y = [row[0] for row in complete]
        else:
            x = [row[0] for row in complete]
            y = [row[1] for row in complete]
        values = (kendall_tau_b(x, y),)
    else:
        trend = sens_slope(
            [row[0] for row in complete], [row[1] for row in complete],
        )
        values = (None, None) if trend is None else trend
    return _output(translator, outputs, values)
