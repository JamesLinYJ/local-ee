"""Bounded List.reduce execution for closed scalar/composed reducer trees."""
from __future__ import annotations

import math

from .composed_reducers import (
    MAX_REDUCER_INPUTS,
    MAX_REDUCER_NODES,
    ReducerSpec,
    ScalarReducerLeaf,
    normalize_reducer_spec,
    validate_reducer_spec,
)
from .composed_reducer_output import _owned_value
from .composed_reducer_expansion import evaluate_for_each, evaluate_repeat
from .ir import Reducer, fail


MAX_LIST_ROWS = 1_000
_EXACT_INTEGER = 2**53


def _charge(translator, work):
    if work < 0 or translator.steps + work > 50_000:
        fail("Composed List reduction exceeds the shared 50000-step compilation work budget")
    translator.steps += work


def _number(value, label):
    if type(value) not in (int, float):
        fail(f"{label} inputs must be finite numbers or null")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or (type(value) is int and abs(value) > _EXACT_INTEGER):
        fail(f"{label} inputs exceed the finite exact Float64 domain")
    return value


def _records(translator, values, input_count):
    if type(values) is not list or len(values) > MAX_LIST_ROWS:
        fail("List.reduce requires at most 1000 inline values")
    if not 0 <= input_count <= MAX_REDUCER_INPUTS:
        fail("List.reduce supports reducers with 0 to 32 inputs")
    _charge(translator, len(values) + 1)
    if input_count == 0:
        from .finite_reducer_scan import scan_inputs

        scan_inputs(translator, values)
        _charge(translator, len(values))
        return [[] for _ in values]
    if input_count == 1:
        # A one-input List reducer consumes each List value directly, including
        # lists and dictionaries for count/first/last.
        _charge(translator, len(values))
        return [[value] for value in values]
    copy_work = len(values) * (input_count + 1)
    _charge(translator, copy_work)
    rows = []
    for row in values:
        if row is None:
            rows.append([None] * input_count)
        elif type(row) is list and len(row) == input_count:
            rows.append(list(row))
        else:
            fail(f"List.reduce requires rows of {input_count} inputs")
    return rows


def _scalar(translator, records, reducer):
    from .list_reductions import invoke_list_reduce

    if type(reducer) is not ScalarReducerLeaf:
        fail("Composed scalar reducer leaf is invalid")
    _charge(translator, 1 + len(records))
    values = [row[0] for row in records]
    result = invoke_list_reduce(
        translator, "List.reduce", {"list": values, "reducer": Reducer(reducer.name)},
    )
    if reducer.name in {"first", "last"} and result is not None:
        result = _owned_value(translator, result)
    name = "stdDev" if reducer.name == "sd" else reducer.name
    return [(name, result)]


def _regression(translator, records, reducer):
    from .list_reductions import invoke_list_reduce

    result = invoke_list_reduce(
        translator, "List.reduce", {"list": records, "reducer": reducer},
    )
    if reducer.name == "linearFit":
        names = ("scale", "offset")
    else:
        names = ("coefficients", "residuals")
    return list(zip(names, (result[name] for name in names)))


def _entries_as_dict(translator, entries, group_name=None):
    # Reserve all key scans/hashes before allocating or filling the result.
    _charge(translator, len(entries) + (group_name is not None))
    key_work = sum(len(name) for name, _ in entries)
    if group_name is not None:
        key_work += len(group_name)
    _charge(translator, key_work)
    result = {}
    if group_name is not None:
        result[group_name] = None
    for name, value in entries:
        if name in result:
            fail("Composed reducer output names collide in a dictionary result")
        result[name] = value
    if group_name is not None:
        # The reserved key was installed only to check for a collision.
        del result[group_name]
    return result


def _group_identity(translator, value):
    if type(value) is bool:
        _charge(translator, 1)
        return ("bool", value)
    if type(value) is str:
        _charge(translator, 1 + len(value))
        return ("str", value)
    if type(value) in (int, float):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite or (type(value) is int and abs(value) > _EXACT_INTEGER):
            fail("Reducer.group keys must be finite exact numbers, strings, or null")
        _charge(translator, 1)
        return ("number", float(value))
    fail("Reducer.group keys must be finite numbers, strings, booleans, or null")


def _evaluate(translator, records, spec):
    if spec.kind == "leaf":
        from .table_reducers import TableReducer
        from .finite_reducer_leaves import FiniteReducerLeaf, reduce_finite_leaf

        if type(spec.leaf) is TableReducer:
            return _regression(translator, records, spec.leaf)
        if type(spec.leaf) is FiniteReducerLeaf:
            return reduce_finite_leaf(translator, spec.leaf, records)
        return _scalar(translator, records, spec.leaf)
    if spec.kind == "setOutputs":
        values = _evaluate(translator, records, spec.child)
        if len(values) != len(spec.output_selection):
            fail("Composed reducer output selection did not match its child")
        _charge(translator, len(values))
        return [
            (name, value)
            for (old_name, value), name in zip(values, spec.output_selection)
            if name not in (None, "")
        ]
    if spec.kind == "repeat":
        return evaluate_repeat(translator, records, spec, _evaluate)
    if spec.kind == "forEach":
        return evaluate_for_each(translator, records, spec, _evaluate)
    if spec.kind == "combine":
        left_rows = records
        right_rows = records
        if not spec.shared_inputs:
            _charge(translator, len(records) * (spec.input_count + 1))
            left_width = spec.left.input_count
            left_rows = [row[:left_width] for row in records]
            right_rows = [row[left_width:] for row in records]
        left = _evaluate(translator, left_rows, spec.left)
        right = _evaluate(translator, right_rows, spec.right)
        _charge(translator, len(right))
        for name, _ in right:
            _charge(translator, len(spec.output_prefix) + len(name))
        right = [(spec.output_prefix + name, value) for name, value in right]
        return [*left, *right]
    if spec.kind == "group":
        _charge(translator, len(records) * (spec.input_count + 1))
        groups = {}
        for row in records:
            key = row[spec.group_field]
            if key is None:
                continue
            identity = _group_identity(translator, key)
            if identity not in groups:
                if len(groups) >= MAX_LIST_ROWS:
                    fail("Reducer.group supports at most 1000 groups")
                groups[identity] = [key, []]
            groups[identity][1].append(
                row[:spec.group_field] + row[spec.group_field + 1:]
            )
        _charge(translator, len(groups) * (len(spec.child.outputs) + 3))
        grouped = []
        for key, child_rows in groups.values():
            entries = _evaluate(translator, child_rows, spec.child)
            record = _entries_as_dict(translator, entries, spec.group_name)
            record[spec.group_name] = key
            grouped.append(record)
        return [("groups", grouped)]
    fail("Composed List reduction encountered an unsupported descriptor")


def _public_shape(translator, entries, outputs):
    if len(outputs) == 1:
        return entries[0][1]
    return _entries_as_dict(translator, entries)


def _charge_names(translator, names):
    _charge(translator, sum(1 + len(name) for name in names))


def _ensure_no_duplicate_outputs(translator, names, message):
    _charge_names(translator, names)
    if len(set(names)) != len(names):
        fail(message)


def _check_nested_groups(translator, spec):
    _charge(translator, 1)
    if spec.kind == "group":
        _charge_names(translator, (spec.group_name,))
        if spec.group_name in spec.child.outputs:
            fail("Reducer.group groupName collides with a reducer output name")
        _ensure_no_duplicate_outputs(
            translator, spec.child.outputs,
            "Grouped reducer output names collide in a group record",
        )
        _check_nested_groups(translator, spec.child)
    elif spec.kind == "combine":
        _check_nested_groups(translator, spec.left)
        _check_nested_groups(translator, spec.right)
    elif spec.kind == "setOutputs":
        _check_nested_groups(translator, spec.child)
    elif spec.kind in {"repeat", "forEach"}:
        _check_nested_groups(translator, spec.child)


def reduce_records(
    translator, records, reducer, *, list_result=False, normalized=False,
    prevalidated=False,
):
    """Reduce preflighted ordered rows; collection callers always get a dict."""
    if normalized:
        spec = reducer
        if (type(prevalidated) is int
                and 1 <= prevalidated <= MAX_REDUCER_NODES):
            nodes = prevalidated
        else:
            nodes = validate_reducer_spec(spec, translator)
    else:
        spec, nodes = normalize_reducer_spec(translator, reducer)
    if type(records) is not list or len(records) > MAX_LIST_ROWS:
        fail("Inline table reduction supports at most 1000 rows")
    if any(type(row) is not list or len(row) != spec.input_count for row in records):
        fail("Inline table rows do not match the reducer input arity")
    _check_nested_groups(translator, spec)
    if not list_result or len(spec.outputs) != 1:
        _ensure_no_duplicate_outputs(
            translator, spec.outputs,
            "Composed reducer output names collide in a dictionary result",
        )
    _charge(translator, len(records) * (nodes + len(spec.outputs) + 1))
    entries = _evaluate(translator, records, spec)
    if len(entries) != len(spec.outputs):
        fail("Composed reduction produced an unexpected output count")
    if list_result:
        return _public_shape(translator, entries, spec.outputs)
    return _entries_as_dict(translator, entries)


def reduce_list(translator, values, reducer):
    """Evaluate List.reduce and return only detached static values."""
    spec, nodes = normalize_reducer_spec(translator, reducer)
    records = _records(translator, values, spec.input_count)
    return reduce_records(
        translator, records, spec, list_result=True, normalized=True,
        prevalidated=nodes,
    )
