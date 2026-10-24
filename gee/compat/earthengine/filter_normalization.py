"""Exact lowering for bounded Earth Engine filter aliases and range helpers."""
from __future__ import annotations

import math

from .ir import Filter


_ALIAS_TARGETS = {
    "eq": "equals",
    "gt": "greaterThan",
    "lt": "lessThan",
}
_NEGATED_ALIASES = {
    "neq": "equals",
    "notEquals": "equals",
    "gte": "lessThan",
    "greaterThanOrEquals": "lessThan",
    "lte": "greaterThan",
    "lessThanOrEquals": "greaterThan",
}
def validate_range_arguments(arguments: dict) -> None:
    """Validate the finite scalar subset used by exact range lowering."""
    if set(arguments) != {"field", "minValue", "maxValue"}:
        raise ValueError("Filter.rangeContains requires field, minValue, and maxValue")
    field = arguments["field"]
    if type(field) is not str or not field or "." in field:
        raise ValueError("Filter.rangeContains requires a nonempty flat field name")
    kinds = []
    for key in ("minValue", "maxValue"):
        value = arguments[key]
        if isinstance(value, str):
            kinds.append("string")
        elif type(value) in (int, float):
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite or type(value) is int and abs(value) > 2**53:
                raise ValueError("Filter.rangeContains bounds must be finite supported scalars")
            kinds.append("number")
        else:
            raise ValueError("Filter.rangeContains bounds must be numbers or strings")
    if kinds[0] != kinds[1]:
        raise ValueError("Filter.rangeContains bounds must have matching types")


def lower_filter_node(name: str, arguments: dict) -> Filter:
    """Lower one filter node without mutating its caller-owned arguments."""
    if type(name) is not str or type(arguments) is not dict:
        raise ValueError("Filter names and arguments must be strings and objects")
    if name in _ALIAS_TARGETS:
        return Filter(_ALIAS_TARGETS[name], dict(arguments))
    if name in _NEGATED_ALIASES:
        child = Filter(_NEGATED_ALIASES[name], dict(arguments))
        return Filter("not", {"filter": child})
    if name == "rangeContains":
        validate_range_arguments(arguments)
        field = arguments["field"]
        lower = Filter("not", {"filter": Filter("lessThan", {
            "leftField": field, "rightValue": arguments["minValue"],
        })})
        upper = Filter("not", {"filter": Filter("greaterThan", {
            "leftField": field, "rightValue": arguments["maxValue"],
        })})
        return Filter("and", {"filters": [lower, upper]})
    if name == "dayOfYear":
        if set(arguments) != {"start", "end"}:
            raise ValueError("Filter.dayOfYear requires start and end")
        if any(type(arguments[key]) is not int or abs(arguments[key]) > 2**53
               for key in ("start", "end")):
            raise ValueError("Filter.dayOfYear start and end must be exact integers")
        return Filter("calendarRange", {
            "start": arguments["start"],
            "end": arguments["end"],
            "field": "day_of_year",
        })
    if name in {"always", "never"}:
        if arguments:
            raise ValueError(f"Filter.{name} does not accept arguments")
        return Filter("and" if name == "always" else "or", {"filters": []})
    if name == "hasType":
        raise ValueError(
            "Filter.hasType is unsupported because Python JSON values do not "
            "retain a documented closed Earth Engine type identity"
        )
    return Filter(name, arguments)


def lower_filter_tree(value: Filter, *, max_nodes: int = 64, max_depth: int = 16) -> Filter:
    """Return canonical filter data, accounting for aliases before allocation."""
    budget = [0]

    def visit(node: Filter, depth: int) -> Filter:
        budget[0] += 1
        if budget[0] > max_nodes or depth > max_depth:
            raise ValueError("Sample predicates exceed64 nodes or depth16")
        if not isinstance(node, Filter) or type(node.args) is not dict:
            raise ValueError("Filter requires serialized ee.Filter values")
        lowered = lower_filter_node(node.name, node.args)
        if lowered.name != node.name or lowered.args is not node.args:
            if lowered.name in {"and", "or"}:
                children = lowered.args.get("filters")
                if type(children) is not list:
                    raise ValueError("Filter boolean children must be a list")
                return Filter(lowered.name, {
                    "filters": [visit(child, depth + 1) for child in children],
                })
            if lowered.name == "not":
                return Filter("not", {
                    "filter": visit(lowered.args["filter"], depth + 1),
                })
            return lowered
        name, arguments = node.name, node.args
        if name in {"and", "or"}:
            children = arguments.get("filters")
            if type(children) is not list:
                raise ValueError(f"Filter.{name} children must be a list")
            return Filter(name, {"filters": [
                visit(child, depth + 1) for child in children
            ]})
        if name == "not":
            return Filter("not", {
                "filter": visit(arguments.get("filter"), depth + 1),
            })
        return Filter(name, dict(arguments))

    return visit(value, 0)
