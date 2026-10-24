"""Construct validated Earth Engine collection filters."""
from __future__ import annotations

from .filter_metadata import (
    _MAX_NOT_NULL_PROPERTIES, field_name as _field,
    finite_number as _finite_number, matches_filter,
    max_difference_arguments as _max_difference_arguments,
)
from .filter_normalization import lower_filter_node, validate_range_arguments
from .ir import Filter, fail, integer


SUPPORTED_FILTERS = frozenset({
    "and", "or", "not", "dateRangeContains", "intersects", "equals",
    "lessThan", "greaterThan", "stringContains", "inList", "listContains",
    "calendarRange", "notNull", "maxDifference", "expression",
    "eq", "gt", "gte", "lt", "lte", "neq", "notEquals",
    "greaterThanOrEquals", "lessThanOrEquals", "stringStartsWith",
    "stringEndsWith", "rangeContains", "dayOfYear", "always", "never",
    "hasGeometry",
})
_FILTERS = SUPPORTED_FILTERS  # Backward-compatible local registry name.
_BINARY_FILTERS = {
    "equals", "lessThan", "greaterThan", "stringContains", "inList",
    "listContains", "eq", "gt", "gte", "lt", "lte", "neq",
    "notEquals", "greaterThanOrEquals", "lessThanOrEquals",
    "stringStartsWith", "stringEndsWith",
}
_STRING_FILTERS = {"stringContains", "stringStartsWith", "stringEndsWith"}
_ORDERED_FILTERS = {
    "lessThan", "greaterThan", "gt", "gte", "lt", "lte",
    "greaterThanOrEquals", "lessThanOrEquals",
}
_FOUR_OPTIONAL_OPERANDS = frozenset({
    "leftField", "leftValue", "rightField", "rightValue",
})

# Pinned official algorithm argument signatures for the Wave56 filter family.
# Each entry is (required names, optional names); local semantic validation
# further requires exactly one field/value form for each binary operand.
FILTER_PREPARATION_ARGUMENTS = {
    **{
        "Filter." + name: (frozenset(), _FOUR_OPTIONAL_OPERANDS)
        for name in (
            "eq", "gt", "gte", "lt", "lte", "neq", "notEquals",
            "greaterThanOrEquals", "lessThanOrEquals", "stringStartsWith",
            "stringEndsWith",
        )
    },
    "Filter.rangeContains": (
        frozenset({"field", "minValue", "maxValue"}), frozenset(),
    ),
    "Filter.dayOfYear": (frozenset({"start", "end"}), frozenset()),
    "Filter.always": (frozenset(), frozenset()),
    "Filter.never": (frozenset(), frozenset()),
    "Filter.hasGeometry": (frozenset(), frozenset()),
}
FILTER_DEFERRED_ARGUMENTS = {
    "Filter.hasType": (frozenset(), _FOUR_OPTIONAL_OPERANDS),
}


def invoke_filter(translator, name, arguments):
    operation = name.split(".", 1)[1]
    if operation == "hasType":
        fail(
            "Filter.hasType is unsupported because Python JSON values do not "
            "retain a documented closed Earth Engine type identity"
        )
    if operation not in _FILTERS:
        fail(f"Unsupported filter: {name}")
    if operation == "expression":
        translator.allowed(arguments, {"expression"})
        from .filter_expression import parse_filter_expression

        if "expression" not in arguments:
            fail("Filter.expression requires an expression string")
        return parse_filter_expression(translator, arguments["expression"])
    if operation in {"and", "or"}:
        translator.allowed(arguments, {"filters"})
    elif operation == "not":
        translator.allowed(arguments, {"filter"})
    elif operation == "calendarRange":
        translator.allowed(arguments, {"start", "end", "field"})
    elif operation == "notNull":
        translator.allowed(arguments, {"properties"})
        properties = arguments.get("properties")
        if not isinstance(properties, list):
            fail("Filter.notNull properties must be a list of strings")
        if len(properties) > _MAX_NOT_NULL_PROPERTIES:
            fail("Filter.notNull supports at most 1000 properties")
        if any(
            not isinstance(property_name, str) for property_name in properties
        ):
            fail("Filter.notNull properties must be a list of strings")
    elif operation == "maxDifference":
        translator.allowed(arguments, {"difference", "leftField", "leftValue", "rightField", "rightValue"})
        if "difference" not in arguments:
            fail("Filter.maxDifference requires difference")
        _max_difference_arguments(arguments)
    elif operation == "rangeContains":
        translator.allowed(arguments, {"field", "minValue", "maxValue"})
        try:
            validate_range_arguments(arguments)
        except (TypeError, ValueError, KeyError, OverflowError) as exc:
            fail(str(exc))
    elif operation == "dayOfYear":
        translator.allowed(arguments, {"start", "end"})
        if set(arguments) != {"start", "end"}:
            fail("Filter.dayOfYear requires start and end")
        if any(type(arguments[key]) is not int or abs(arguments[key]) > 2**53
               for key in ("start", "end")):
            fail("Filter.dayOfYear start and end must be exact integers")
        integer(arguments["start"], "Filter.dayOfYear start")
        integer(arguments["end"], "Filter.dayOfYear end")
    elif operation in {"always", "never", "hasGeometry"}:
        translator.allowed(arguments, set())
    else:
        fields = {"leftField", "leftValue", "rightField", "rightValue"}
        if operation == "intersects":
            fields.add("maxError")
        translator.allowed(arguments, fields)
    if operation in _BINARY_FILTERS:
        for side in ("left", "right"):
            field_key, value_key = side + "Field", side + "Value"
            if (field_key in arguments) == (value_key in arguments):
                if operation == "equals" and field_key not in arguments:
                    # The pinned SDK omits a literal null operand. Keep the
                    # established explicit null-equality diagnostic instead
                    # of treating that serialized form as a generic arity bug.
                    fail("Filter.equals equality involving missing/null operands is unsupported")
                fail(f"Filter.{operation} requires exactly one field or value per operand")
            if field_key in arguments:
                _field(arguments[field_key], f"Filter.{operation}")
            elif operation in _STRING_FILTERS and type(arguments[value_key]) is not str:
                fail(f"Filter.{operation} literal operands must be strings")
    if operation in _ORDERED_FILTERS:
        literal_kinds = []
        for side in ("left", "right"):
            field_key, value_key = side + "Field", side + "Value"
            if field_key in arguments:
                continue
            value = arguments[value_key]
            if type(value) is str:
                literal_kinds.append("string")
            elif type(value) in (int, float):
                _finite_number(value, f"Filter.{operation} literal operand")
                literal_kinds.append("number")
            else:
                fail(f"Filter.{operation} operands must be numbers or strings")
        if len(literal_kinds) == 2 and literal_kinds[0] != literal_kinds[1]:
            fail(f"Filter.{operation} literal operands must have matching types")
    try:
        lowered = lower_filter_node(operation, arguments)
    except (TypeError, ValueError, KeyError, OverflowError) as exc:
        fail(str(exc))
    if lowered.name != operation or lowered.args is not arguments:
        return lowered
    for side in ("left", "right"):
        if side + "Field" in arguments and side + "Value" in arguments:
            fail("Filter operands cannot specify both field and value")
    if operation == "dateRangeContains" and "leftValue" in arguments:
        from .date_ranges import UnboundedDateRange, is_date_range

        value = arguments["leftValue"]
        if isinstance(value, UnboundedDateRange) or not is_date_range(value):
            fail("Filter.dateRangeContains requires a finite DateRange")
    return Filter(operation, arguments)


class FilteringOperations:
    def matches(self, filt, item):
        return matches_filter(self, filt, item)
