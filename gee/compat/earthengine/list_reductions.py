"""Finite List reducer adapters; single outputs stay values, regressions maps."""
from __future__ import annotations

import math

from .array_core import charge_array, wrap_array
from .array_reductions import _reduce
from .ir import Reducer, fail
from .table_reducers import TableReducer, reduce_regression_rows


MAX_LIST_ROWS = 1000
_SCALAR_REDUCERS = frozenset({"sum", "mean", "min", "max", "count", "first", "last", "median", "sd"})


def _number(value):
    if type(value) not in (int, float):
        fail("List.reduce numeric inputs must be finite numbers or null")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or (type(value) is int and abs(value) > 2**53):
        fail("List.reduce numeric inputs exceed the finite exact Float64 domain")
    return value


def _regression_rows(translator, values, reducer):
    rows = []
    charge_array(translator, len(values) * (reducer.input_count + 1))
    for row in values:
        if row is None:
            continue
        if not isinstance(row, list) or len(row) != reducer.input_count:
            fail(f"List.reduce {reducer.name} requires rows of {reducer.input_count} inputs")
        # Validate non-null fields even in incomplete rows. A missing response
        # must not conceal invalid text/boolean data in a design column.
        checked = [None if item is None else _number(item) for item in row]
        if all(item is not None for item in checked):
            rows.append(checked)
    return rows


def invoke_list_reduce(translator, name, arguments):
    """Run only the declared bounded scalar and unweighted regression subset."""
    if name != "List.reduce":
        fail(f"Unsupported List reduction: {name}")
    translator.allowed(arguments, {"list", "reducer"})
    values = arguments.get("list")
    if not isinstance(values, list) or len(values) > MAX_LIST_ROWS:
        fail("List.reduce requires at most 1000 inline values")
    reducer = arguments.get("reducer")
    if isinstance(reducer, TableReducer):
        rows = _regression_rows(translator, values, reducer)
        return reduce_regression_rows(translator, rows, reducer)
    if (not isinstance(reducer, Reducer) or reducer.unweighted
            or reducer.name not in _SCALAR_REDUCERS):
        fail("List.reduce requires a supported scalar or regression Reducer")
    charge_array(translator, len(values))
    present = [value for value in values if value is not None]
    if reducer.name == "count":
        # The pinned count contract counts non-null inputs of any type.
        return len(present)
    if reducer.name in {"first", "last"}:
        return present[0 if reducer.name == "first" else -1] if present else None
    checked = [_number(value) for value in present]
    if not checked:
        return 0 if reducer.name == "sum" else None
    if reducer.name == "sd" and len(checked) < 2:
        return None
    # Reuse the same finite statistics and shared work accounting as Array
    # reduce, including stable sums/means and ddof=1 sample standard deviation.
    result = _reduce(translator, {
        "array": wrap_array(checked), "reducer": reducer, "axes": [0],
    })
    return result.data.item()
