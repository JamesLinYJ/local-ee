"""Bounded kernels for finite fixed-bin histogram Reducer leaves."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math

from .array_core import MAX_ARRAY_CELLS, MAX_ARRAY_WORK
from .ir import fail


MAX_HISTOGRAM_ROWS = 1_000
MAX_PUBLIC_JSON_BYTES = 1_000_000
MAX_EXACT_INTEGER = 2**53
HISTOGRAM_REDUCER_NAMES = (
    "Reducer.fixedHistogram",
    "Reducer.fixed2DHistogram",
)

# Earth Engine's fixed2DHistogram reference describes the count array and the
# xAxis/yAxis edge arrays, but the algorithm descriptor does not enumerate
# output keys. These canonical labels mirror those names in the official text.
_OUTPUTS = {
    "Reducer.fixedHistogram": ("histogram",),
    "Reducer.fixed2DHistogram": ("histogram", "xAxis", "yAxis"),
}
_FIELDS = {"name", "minimums", "maximums", "steps", "cumulative"}


@dataclass(frozen=True)
class HistogramReducerLeaf:
    """Closed immutable parameters for one finite histogram leaf."""

    name: str
    minimums: tuple[float, ...]
    maximums: tuple[float, ...]
    steps: tuple[int, ...]
    cumulative: bool


def _charge(translator, amount: int, purpose: str) -> None:
    if (type(amount) is not int or amount < 0 or amount > MAX_ARRAY_WORK
            or translator.steps + amount > MAX_ARRAY_WORK):
        fail(f"{purpose} exceeds the shared 50000-step compilation work budget")
    translator.steps += amount


def _number(value, label: str) -> float:
    if type(value) is int:
        if not -MAX_EXACT_INTEGER <= value <= MAX_EXACT_INTEGER:
            fail(f"{label} must be a finite number within the exact ±2^53 range")
        return float(value)
    if type(value) is not float or not math.isfinite(value):
        fail(f"{label} must be a finite number")
    return value


def _integer_step(value, label: str) -> int:
    """Canonicalize an EE Integer argument carried as JSON int or float."""
    if isinstance(value, bool):
        fail(f"{label} must be a positive exact integer")
    if type(value) is int:
        if abs(value) > MAX_EXACT_INTEGER:
            fail(f"{label} exceeds the exact ±2^53 integer range")
        result = value
    elif type(value) is float:
        if not math.isfinite(value) or not value.is_integer():
            fail(f"{label} must be a positive exact integer")
        if abs(value) > MAX_EXACT_INTEGER:
            fail(f"{label} exceeds the exact ±2^53 integer range")
        result = int(value)
    else:
        fail(f"{label} must be a positive exact integer")
    if result <= 0:
        fail(f"{label} must be a positive exact integer")
    return result


def _shape(leaf: HistogramReducerLeaf) -> tuple[int, int, int]:
    dimensions = len(leaf.steps)
    if dimensions == 1:
        bins = leaf.steps[0]
        cells = bins * 2
        matrix_cells = bins
    else:
        x_bins, y_bins = leaf.steps
        bins = x_bins + y_bins
        matrix_cells = x_bins * y_bins
        cells = matrix_cells + bins
    if cells > MAX_ARRAY_CELLS:
        fail("Fixed histogram outputs exceed the shared 10000-array-cell limit")
    return bins, matrix_cells, cells


def _grid_is_representable(minimum: float, maximum: float, steps: int) -> None:
    low = Fraction.from_float(minimum)
    high = Fraction.from_float(maximum)
    if low >= high:
        fail("Fixed histogram bounds must satisfy min < max")
    width = (high - low) / steps
    previous = None
    for index in range(steps):
        edge = minimum if index == 0 else float(low + width * index)
        if (not math.isfinite(edge) or (previous is not None and edge <= previous)
                or Fraction.from_float(edge) >= high):
            fail("Fixed histogram grid is not representable as distinct Float64 edges")
        previous = edge


def _validate_leaf(translator, leaf: HistogramReducerLeaf) -> tuple[int, tuple[str, ...]]:
    if type(leaf) is not HistogramReducerLeaf or set(vars(leaf)) != _FIELDS:
        fail("Histogram reducer leaf has invalid fields")
    if (type(leaf.name) is not str or leaf.name not in _OUTPUTS
            or type(leaf.minimums) is not tuple or type(leaf.maximums) is not tuple
            or type(leaf.steps) is not tuple or type(leaf.cumulative) is not bool):
        fail("Histogram reducer leaf has invalid fields")
    dimensions = 1 if leaf.name == "Reducer.fixedHistogram" else 2
    if (len(leaf.minimums) != dimensions or len(leaf.maximums) != dimensions
            or len(leaf.steps) != dimensions
            or (dimensions == 2 and leaf.cumulative)
            or any(type(value) is not float or not math.isfinite(value)
                   for value in (*leaf.minimums, *leaf.maximums))
            or any(type(value) is not int or value <= 0 for value in leaf.steps)):
        fail("Histogram reducer leaf parameters have invalid types or arity")
    bins, _, cells = _shape(leaf)
    _charge(translator, 1 + len(leaf.name) + bins,
            "Fixed histogram descriptor validation")
    for minimum, maximum, steps in zip(leaf.minimums, leaf.maximums, leaf.steps):
        _grid_is_representable(minimum, maximum, steps)
    outputs = _OUTPUTS[leaf.name]
    if dimensions == 1:
        return 1, outputs
    return 2, outputs


def make_histogram_reducer(translator, name, args) -> HistogramReducerLeaf:
    """Parse exact pinned constructor arguments into a canonical leaf."""
    if type(name) is not str or name not in HISTOGRAM_REDUCER_NAMES:
        fail(f"Unsupported fixed histogram reducer: {name}")
    if type(args) is not dict:
        fail("Fixed histogram reducer arguments must be an object")
    if name == "Reducer.fixedHistogram":
        allowed = {"min", "max", "steps", "cumulative"}
        required = {"min", "max", "steps"}
        dimensions = 1
    else:
        allowed = {"xMin", "xMax", "xSteps", "yMin", "yMax", "ySteps"}
        required = allowed
        dimensions = 2
    translator.allowed(args, allowed)
    if required - args.keys():
        fail("Fixed histogram reducer is missing required arguments")
    if dimensions == 1:
        bounds = ((args["min"], args["max"]),)
        raw_steps = (args["steps"],)
        cumulative = args.get("cumulative", False)
        if type(cumulative) is not bool:
            fail("Reducer.fixedHistogram cumulative must be a boolean")
    else:
        bounds = ((args["xMin"], args["xMax"]), (args["yMin"], args["yMax"]))
        raw_steps = (args["xSteps"], args["ySteps"])
        cumulative = False
    minima, maxima = [], []
    for minimum, maximum in bounds:
        minima.append(_number(minimum, "Fixed histogram min"))
        maxima.append(_number(maximum, "Fixed histogram max"))
    steps = tuple(
        _integer_step(step, "Fixed histogram steps") for step in raw_steps
    )
    leaf = HistogramReducerLeaf(
        name, tuple(minima), tuple(maxima), steps, cumulative,
    )
    _validate_leaf(translator, leaf)
    return leaf


def describe_histogram_reducer(translator, leaf) -> tuple[int, tuple[str, ...]]:
    """Return arity and canonical output names after full leaf validation."""
    return _validate_leaf(translator, leaf)
