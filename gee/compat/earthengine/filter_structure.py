"""Validate inline Feature filter trees before row-dependent evaluation."""
from __future__ import annotations

from .array_values import StaticArray
from .feature_values import charge, property_name
from .filter_normalization import lower_filter_node
from .ir import Filter, fail, integer


FILTER_ARGUMENTS = {
    "and": {"filters"},
    "or": {"filters"},
    "not": {"filter"},
    "dateRangeContains": {"leftField", "leftValue", "rightField", "rightValue"},
    "intersects": {"leftField", "leftValue", "rightField", "rightValue", "maxError"},
    "equals": {"leftField", "leftValue", "rightField", "rightValue"},
    "lessThan": {"leftField", "leftValue", "rightField", "rightValue"},
    "greaterThan": {"leftField", "leftValue", "rightField", "rightValue"},
    "stringContains": {"leftField", "leftValue", "rightField", "rightValue"},
    "stringStartsWith": {"leftField", "leftValue", "rightField", "rightValue"},
    "stringEndsWith": {"leftField", "leftValue", "rightField", "rightValue"},
    "inList": {"leftField", "leftValue", "rightField", "rightValue"},
    "listContains": {"leftField", "leftValue", "rightField", "rightValue"},
    "calendarRange": {"start", "end", "field"},
    "notNull": {"properties"},
    "maxDifference": {"difference", "leftField", "leftValue", "rightField", "rightValue"},
    "hasGeometry": set(),
}

_CALENDAR_FIELDS = {
    "year", "month", "day_of_year", "day_of_month", "day_of_week", "hour", "minute",
}
_BINARY = {
    "equals", "lessThan", "greaterThan", "stringContains", "stringStartsWith",
    "stringEndsWith", "inList", "listContains",
}


def _kind(value, label):
    if isinstance(value, (StaticArray, list, dict)):
        fail(f"{label} supports scalar metadata operands only")
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if type(value) in (int, float):
        return "number"
    if isinstance(value, str):
        return "string"
    fail(f"{label} supports scalar metadata operands only")


def _operands(translator, arguments):
    result = []
    for side in ("left", "right"):
        field, literal = side + "Field", side + "Value"
        if (field in arguments) == (literal in arguments):
            fail("Feature filters require exactly one field or value per operand")
        if field in arguments:
            key = property_name(arguments[field])
            if not key or "." in key:
                fail("Feature filters require nonempty flat property names")
            charge(translator, max(1, len(key)))
            result.append((True, None))
        else:
            value = arguments[literal]
            charge(translator, max(1, len(value)) if isinstance(value, str) else 1)
            result.append((False, value))
    return result


def validate_filter_structure(translator, filt):
    """Validate filter structure before row evaluation, charging the graph budget."""
    active = set()

    def visit(node, depth):
        charge(translator)
        if depth > 32:
            fail("Feature filter nesting exceeds the depth limit")
        if not isinstance(node, Filter) or type(node.args) is not dict:
            fail("Inline FeatureCollection.filter requires a serialized ee.Filter")
        identity = id(node)
        if identity in active:
            fail("Feature filter tree contains a cycle")
        active.add(identity)
        try:
            name, arguments = node.name, node.args
            if type(name) is not str:
                fail("Feature filter names must be strings")
            try:
                lowered = lower_filter_node(name, arguments)
            except (TypeError, ValueError, KeyError, OverflowError) as exc:
                fail(str(exc))
            if lowered.name != name or lowered.args is not arguments:
                visit(lowered, depth)
                return
            allowed = FILTER_ARGUMENTS.get(name)
            if allowed is None:
                fail(f"Unsupported inline Feature filter: Filter.{name}")
            if any(type(key) is not str for key in arguments):
                fail("Feature filter argument names must be strings")
            translator.allowed(arguments, allowed)
            charge(translator, len(arguments))

            if name in {"and", "or"}:
                children = arguments.get("filters")
                if not isinstance(children, list) or len(children) > 1000:
                    fail(f"Filter.{name} requires at most 1000 child filters")
                charge(translator, len(children))
                for child in children:
                    visit(child, depth + 1)
                return
            if name == "not":
                if "filter" not in arguments:
                    fail("Filter.not requires a filter")
                visit(arguments["filter"], depth + 1)
                return
            if name == "hasGeometry":
                return
            if name == "notNull":
                fields = arguments.get("properties")
                if not isinstance(fields, list) or len(fields) > 1000:
                    fail("Filter.notNull supports at most 1000 property names")
                charge(translator, len(fields))
                if any(not isinstance(field, str) for field in fields):
                    fail("Filter.notNull properties must be a list of strings")
                for field in fields:
                    charge(translator, max(1, len(field)))
                return
            if name == "calendarRange":
                if "start" not in arguments:
                    fail("Filter.calendarRange requires start")
                integer(arguments["start"], "Calendar start")
                if "end" in arguments:
                    integer(arguments["end"], "Calendar end")
                field = arguments.get("field", "day_of_year")
                if type(field) is not str or field not in _CALENDAR_FIELDS:
                    fail(f"Unsupported calendar field: {field}")
                return
            if name == "dateRangeContains":
                if set(arguments) != {"leftValue", "rightField"}:
                    fail("Only system:time_start date filtering is supported")
                from .date_ranges import UnboundedDateRange, is_date_range

                value = arguments["leftValue"]
                if (isinstance(value, UnboundedDateRange) or not is_date_range(value)
                        or arguments["rightField"] != "system:time_start"):
                    fail("Filter.dateRangeContains requires a finite DateRange on system:time_start")
                return
            if name == "intersects":
                from .spatial_filters import prepare_intersects_filter

                prepare_intersects_filter(translator, arguments)
                return
            if name == "maxDifference":
                if "difference" not in arguments:
                    fail("Filter.maxDifference requires difference")
                from .filter_metadata import max_difference_arguments

                max_difference_arguments(arguments)
                return
            if name not in _BINARY:
                fail(f"Unsupported inline Feature filter: Filter.{name}")

            operands = _operands(translator, arguments)
            if name in {"stringContains", "stringStartsWith", "stringEndsWith"}:
                for is_field, value in operands:
                    if not is_field and type(value) is not str:
                        fail(f"Filter.{name} literal operands must be strings")
            elif name in {"lessThan", "greaterThan"}:
                kinds = [None if is_field else _kind(value, "Ordered Feature filters")
                         for is_field, value in operands]
                for kind in kinds:
                    if kind is not None and kind not in {"number", "string"}:
                        fail("Ordered Feature filters require numbers or strings")
                known = [kind for kind in kinds if kind is not None]
                if len(known) == 2 and known[0] != known[1]:
                    fail("Metadata filter operands have incompatible types")
            elif name == "equals":
                for is_field, value in operands:
                    if not is_field:
                        kind = _kind(value, "Feature filter equality")
                        if kind == "null":
                            fail("Feature filter equality involving missing/null values is unsupported")
            elif name in {"inList", "listContains"}:
                sequence_side = 1 if name == "inList" else 0
                candidate_side = 1 - sequence_side
                is_field, sequence = operands[sequence_side]
                if not is_field:
                    if not isinstance(sequence, list):
                        fail(f"Filter.{name} requires a list operand")
                    charge(translator, len(sequence))
                    for item in sequence:
                        _kind(item, f"Filter.{name}")
                        if isinstance(item, str):
                            charge(translator, max(1, len(item)))
                is_field, candidate = operands[candidate_side]
                if not is_field and _kind(candidate, f"Filter.{name}") == "null":
                    fail(f"Filter.{name} requires present, non-null operands")
        finally:
            active.remove(identity)

    visit(filt, 0)
