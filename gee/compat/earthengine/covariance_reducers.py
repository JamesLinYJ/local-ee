"""Bounded covariance reducer leaves for finite typed array rows."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .array_values import MAX_ARRAY_CELLS, MAX_ARRAY_RANK, StaticArray
from .ir import fail


MAX_COVARIANCE_ROWS = 1_000
MAX_COVARIANCE_WIDTH = 32
MAX_COVARIANCE_OUTPUT_BYTES = 1_000_000
_MAX_WORK = 50_000
_MAX_EXACT_INTEGER = 2**53

COVARIANCE_REDUCER_NAMES = frozenset({
    "Reducer.covariance",
    "Reducer.centeredCovariance",
})
_OUTPUTS = ("array",)


@dataclass(frozen=True)
class CovarianceReducerLeaf:
    """A closed covariance leaf; its name is the reducer suffix."""

    name: str


def _charge(translator, work: int) -> None:
    if (type(work) is not int or work < 0 or work > _MAX_WORK
            or translator.steps + work > _MAX_WORK):
        fail("Covariance reducer exceeds the shared 50000-step compilation work budget")
    translator.steps += work


def _validate_leaf(translator, leaf: CovarianceReducerLeaf) -> str:
    if type(leaf) is not CovarianceReducerLeaf or type(leaf.name) is not str:
        fail("Covariance reducer leaf has invalid fields")
    if len(leaf.name) > 32 or f"Reducer.{leaf.name}" not in COVARIANCE_REDUCER_NAMES:
        fail("Covariance reducer leaf has an unsupported name")
    _charge(translator, 1 + len(leaf.name))
    return leaf.name


def make_covariance_reducer(translator, name, arguments) -> CovarianceReducerLeaf:
    """Validate a no-argument covariance constructor and detach its name."""
    if type(name) is not str or name not in COVARIANCE_REDUCER_NAMES:
        fail(f"Unsupported covariance reducer: {name}")
    if type(arguments) is not dict:
        fail(f"{name} arguments must be a dictionary")
    translator.allowed(arguments, set())
    suffix = name[len("Reducer."):]
    _charge(translator, 1 + len(name) + len(suffix))
    return CovarianceReducerLeaf(suffix)


def describe_covariance_reducer(
    translator, leaf: CovarianceReducerLeaf,
) -> tuple[int, tuple[str, ...]]:
    """Return the single array input and the pinned `array` output name."""
    _validate_leaf(translator, leaf)
    return 1, _OUTPUTS


def _vector_data(value) -> np.ndarray:
    if type(value) is not StaticArray:
        fail("Covariance reducers require typed StaticArray inputs; ordinary Lists are unsupported")
    data = value.data
    if not isinstance(data, np.ndarray):
        fail("Covariance reducer StaticArray data must be a NumPy array")
    if data.ndim != 1:
        fail("Covariance reducers require rank-1 StaticArray inputs")
    if not 1 <= data.size <= MAX_COVARIANCE_WIDTH:
        fail("Covariance reducer vectors must have width 1..32")
    if data.dtype.kind not in "iuf" or data.dtype.itemsize > 8:
        fail("Covariance reducer vectors must contain Float64-compatible real values")
    return data


def _validate_vector_values(data: np.ndarray) -> None:
    kind = data.dtype.kind
    for item in data:
        value = item.item()
        if kind in "iu":
            integer = int(value)
            if integer < -_MAX_EXACT_INTEGER or integer > _MAX_EXACT_INTEGER:
                fail("Covariance reducer array integers must be within the exact ±2^53 range")
        elif not math.isfinite(float(value)):
            fail("Covariance reducer arrays must contain finite values")


def _finite(value: float, detail: str) -> float:
    if not math.isfinite(value):
        fail(f"Covariance reducer {detail} exceeds the finite Float64 range")
    return value


def _neumaier_add(total: float, correction: float, value: float) -> tuple[float, float]:
    """Accumulate one finite term with a compensated online sum."""
    updated = _finite(total + value, "accumulator")
    if abs(total) >= abs(value):
        rounding = (total - updated) + value
    else:
        rounding = (value - updated) + total
    correction = _finite(correction + rounding, "compensation")
    return updated, correction


def _final_sum(total: float, correction: float) -> float:
    try:
        return _finite(math.fsum((total, correction)), "result")
    except (OverflowError, ValueError):
        fail("Covariance reducer result exceeds the finite Float64 range")


def _preflight_rows(translator, records):
    if type(records) is not list or len(records) > MAX_COVARIANCE_ROWS:
        fail("Covariance reducer requires at most 1000 rows")
    # Charge the complete outer walk before inspecting any record or allocating.
    _charge(translator, 1 + len(records))

    width = None
    valid_count = 0
    for row in records:
        if type(row) is not list or len(row) != 1:
            fail("Covariance reducer requires one input array per row")
        value = row[0]
        if value is None:
            continue
        data = _vector_data(value)
        if width is None:
            width = int(data.size)
        elif data.size != width:
            fail("Covariance reducer array dimensions must match")
        valid_count += 1

    if width is not None:
        output_cells = width * width
        if (width > MAX_ARRAY_CELLS or output_cells > MAX_ARRAY_CELLS
                or 2 > MAX_ARRAY_RANK):
            fail("Covariance reducer output exceeds the static Array rank/cell limits")
        # Every output value is a finite JSON number whose representation is
        # shorter than 32 bytes; include matrix punctuation in the bound.
        output_wire = 2 + output_cells * 32 + width * (width - 1) + 2 * width
        if output_wire > MAX_COVARIANCE_OUTPUT_BYTES:
            fail("Covariance reducer output exceeds the 1 MB JSON limit")
    return width, valid_count


def _charge_kernel(translator, row_count: int, width: int, *, centered: bool) -> None:
    cells = width * width
    # Covers value validation, per-row conversion/local differences, online
    # matrix updates, final matrix writes and owned output allocation. The
    # quadratic term reserves at least four units per row/cell update; all
    # limits are checked before numerical scans or work-array allocations.
    if centered:
        work = row_count * (4 * cells + 2 * width) + 5 * cells + 2 * width + 16
    else:
        work = row_count * (4 * cells + 4 * width) + 6 * cells + 4 * width + 16
    _charge(translator, work + 1 + len("array"))


def _validated_arrays(records):
    """Validate every non-null vector before any row is dropped or reduced."""
    for row in records:
        value = row[0]
        if value is not None:
            _validate_vector_values(value.data)


def _output_array(matrix: np.ndarray) -> StaticArray:
    matrix.flags.writeable = False
    return StaticArray(matrix)


def _online_covariance(records, width: int, row_count: int) -> np.ndarray | None:
    if row_count < 2:
        return None

    origins = None
    mean_offsets = np.zeros(width, dtype=np.float64)
    totals = np.zeros((width, width), dtype=np.float64)
    corrections = np.zeros((width, width), dtype=np.float64)
    count = 0
    for row in records:
        value = row[0]
        if value is None:
            continue
        vector = [float(item) for item in value.data]
        count += 1
        if count == 1:
            origins = vector
            continue

        # Anchor the online mean at the first observation so a large shared
        # offset cannot erase small changes while updating an absolute mean.
        # Pébay's recurrence then uses the local-offset form of
        # M2 += (x - old_mean) * (x - new_mean).
        offsets = [
            _finite(vector[index] - origins[index], "local difference")
            for index in range(width)
        ]
        deltas = [
            _finite(offsets[index] - float(mean_offsets[index]), "local difference")
            for index in range(width)
        ]
        for index in range(width):
            increment = _finite(deltas[index] / count, "mean increment")
            mean_offsets[index] = _finite(
                math.fsum((float(mean_offsets[index]), increment)), "mean offset",
            )

        for left in range(width):
            delta = deltas[left]
            for right in range(left, width):
                residual = _finite(
                    offsets[right] - float(mean_offsets[right]), "local difference",
                )
                term = _finite(delta * residual, "covariance accumulation")
                total, correction = _neumaier_add(
                    float(totals[left, right]),
                    float(corrections[left, right]),
                    term,
                )
                totals[left, right] = total
                corrections[left, right] = correction

    result = np.empty((width, width), dtype=np.float64)
    divisor = row_count - 1
    for left in range(width):
        for right in range(left, width):
            covariance = _finite(
                _final_sum(
                    float(totals[left, right]),
                    float(corrections[left, right]),
                ) / divisor,
                "sample covariance",
            )
            result[left, right] = covariance
            result[right, left] = covariance
    return result


def _centered_covariance(records, width: int, row_count: int) -> np.ndarray | None:
    if row_count < 2:
        return None

    totals = np.zeros((width, width), dtype=np.float64)
    corrections = np.zeros((width, width), dtype=np.float64)
    for row in records:
        value = row[0]
        if value is None:
            continue
        vector = [float(item) for item in value.data]
        # This reducer intentionally does not subtract the sample mean. Its
        # inputs are required to be centered by the caller.
        for left in range(width):
            for right in range(left, width):
                term = _finite(
                    vector[left] * vector[right],
                    "centered covariance accumulation",
                )
                total, correction = _neumaier_add(
                    float(totals[left, right]),
                    float(corrections[left, right]),
                    term,
                )
                totals[left, right] = total
                corrections[left, right] = correction

    result = np.empty((width, width), dtype=np.float64)
    divisor = row_count - 1
    for left in range(width):
        for right in range(left, width):
            covariance = _finite(
                _final_sum(
                    float(totals[left, right]),
                    float(corrections[left, right]),
                ) / divisor,
                "centered sample covariance",
            )
            result[left, right] = covariance
            result[right, left] = covariance
    return result


def reduce_covariance_reducer(translator, leaf, records) -> list[tuple[str, object]]:
    """Reduce rows of one typed vector input to an owned read-only matrix.

    Null arrays are skipped after all non-null array values have been checked.
    Empty and singleton samples have an undefined sample covariance and return
    a named null result.
    """
    name = _validate_leaf(translator, leaf)
    width, row_count = _preflight_rows(translator, records)
    if width is None:
        _charge(translator, 1 + len("array"))
        return [("array", None)]

    _charge_kernel(
        translator, row_count, width,
        centered=name == "centeredCovariance",
    )
    _validated_arrays(records)
    if row_count < 2:
        return [("array", None)]

    result = (
        _centered_covariance(records, width, row_count)
        if name == "centeredCovariance"
        else _online_covariance(records, width, row_count)
    )
    if result is None:
        return [("array", None)]
    return [("array", _output_array(result))]
