"""Bounded filtering and key selection for finite static EE containers.

This adapter reuses the canonical Filter IR and equality implementation. Key
selectors use the shared bounded RE2 matcher, including literal-looking keys.
"""
from __future__ import annotations

from .date_values import millis
from .feature_filters import _ARGUMENTS as FEATURE_FILTER_ARGUMENTS
from .feature_filters import _scalar_kind, matches_feature_filter
from .filtering import _max_difference_arguments
from .ir import Filter, fail, integer
from .static_dictionary_values import (
    MAX_STATIC_VALUES,
    _measure,
    charge,
    clone_entries,
    clone_value,
    measure_entries,
    require_dictionary,
    require_string_list,
)
from .static_equality import static_equal
from .feature_values import is_feature, validate_feature
from .regex_values import compile_pattern


STATIC_CONTAINER_SELECTION_FUNCTIONS = frozenset({
    "List.filter", "Dictionary.remove", "Dictionary.select",
})
_ARGUMENTS = {
    "List.filter": ({"list", "filter"}, set()),
    "Dictionary.remove": ({"dictionary", "selectors"}, {"ignoreMissing"}),
    "Dictionary.select": ({"dictionary", "selectors"}, {"ignoreMissing"}),
}


def _arguments(translator, name, arguments):
    required, optional = _ARGUMENTS[name]
    translator.allowed(arguments, required | optional)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def _list_filter_match(translator, filt, item):
    feature = item if is_feature(item) else {"type": "Feature", "properties": {"item": item}}
    if filt.name == "equals" and not is_feature(item):
        args = filt.args
        fields = [side for side in ("left", "right") if side + "Field" in args]
        values = [side for side in ("left", "right") if side + "Value" in args]
        if len(fields) == 2 and all(args[side + "Field"] == "item" for side in fields):
            return static_equal(translator, item, item, exact_integers=True)
        if not fields and len(values) == 2:
            return static_equal(translator, args["leftValue"], args["rightValue"], exact_integers=True)
        if len(fields) == len(values) == 1 and args[fields[0] + "Field"] == "item":
            return static_equal(translator, item, args[values[0] + "Value"], exact_integers=True)
    return matches_feature_filter(translator, filt, feature) is True


def _validate_filter(translator, filt, depth=0):
    """Preflight the whole Filter tree, including branches no item visits."""
    charge(translator)
    if depth > 32 or type(filt) is not Filter or type(filt.args) is not dict:
        fail("List.filter requires a bounded, well-formed ee.Filter tree")
    name, args = filt.name, filt.args
    if type(name) is not str or name not in FEATURE_FILTER_ARGUMENTS:
        fail(f"Unsupported inline Feature filter: Filter.{name}")
    translator.allowed(args, FEATURE_FILTER_ARGUMENTS[name])
    if name in {"and", "or"}:
        children = args.get("filters")
        if type(children) is not list or len(children) > 1000:
            fail(f"Filter.{name} requires at most 1000 child filters")
        charge(translator, len(children))
        for child in children:
            _validate_filter(translator, child, depth + 1)
        return
    if name == "not":
        if "filter" not in args:
            fail("Filter.not requires a child filter")
        _validate_filter(translator, args["filter"], depth + 1)
        return
    if name == "notNull":
        keys = args.get("properties")
        if type(keys) is not list or len(keys) > 1000 or any(type(key) is not str for key in keys):
            fail("Filter.notNull requires at most 1000 string property names")
        static_equal(translator, keys, keys, exact_integers=True)
        return
    if name == "calendarRange":
        if "start" not in args:
            fail("Filter.calendarRange requires start")
        integer(args["start"], "Calendar start")
        integer(args.get("end", args["start"]), "Calendar end")
        field = args.get("field", "day_of_year")
        if type(field) is not str or field not in {"year", "month", "day_of_year", "day_of_month", "day_of_week", "hour", "minute"}:
            fail("Unsupported calendar field")
        return
    if name == "dateRangeContains":
        if set(args) != {"leftValue", "rightField"} or args["rightField"] != "system:time_start":
            fail("Only system:time_start date filtering is supported")
        interval = args["leftValue"]
        if type(interval) not in (list, tuple) or len(interval) != 2:
            fail("Filter.dateRangeContains requires a finite date interval")
        for value in interval:
            millis(value)
        return
    if name == "intersects":
        if args.get("leftField") != ".all" or "rightValue" not in args or "leftValue" in args or "rightField" in args:
            fail("Only collection footprint intersection filtering is supported")
        if args.get("maxError") is not None:
            fail("Feature geometry filter maxError is unsupported")
        static_equal(translator, args["rightValue"], args["rightValue"])
        return
    if name == "maxDifference":
        _max_difference_arguments(args)
        for side in ("left", "right"):
            key = side + "Value"
            if key in args:
                static_equal(translator, args[key], args[key], exact_integers=True)
        return
    for side in ("left", "right"):
        field, value = side + "Field", side + "Value"
        if (field in args) == (value in args):
            fail("Feature filters require exactly one field or value per operand")
        if field in args:
            if type(args[field]) is not str or not args[field] or "." in args[field]:
                fail("Feature filters require nonempty flat property names")
        else:
            static_equal(translator, args[value], args[value], exact_integers=True)
    if name == "equals" and any(args.get(s + "Value") is None for s in ("left", "right") if s + "Value" in args):
        fail("Feature filter equality involving missing/null values is unsupported")
    if name in {"lessThan", "greaterThan"}:
        kinds = {_scalar_kind(args[s + "Value"], "Ordered Feature filters") for s in ("left", "right")
                 if s + "Value" in args and args[s + "Value"] is not None}
        if any(kind not in {"number", "string"} for kind in kinds) or len(kinds) > 1:
            fail("Metadata filter operands have incompatible types")
    if name == "stringContains" and any(type(args[s + "Value"]) is not str for s in ("left", "right") if s + "Value" in args):
        fail("Filter.stringContains requires string operands")
    if name in {"inList", "listContains"}:
        key = ("right" if name == "inList" else "left") + "Value"
        if key in args:
            if type(args[key]) is not list:
                fail(f"Filter.{name} requires a list operand")
            for item in args[key]:
                _scalar_kind(item, f"Filter.{name}")


def _list_filter(translator, arguments):
    name = "List.filter"
    _arguments(translator, name, arguments)
    values = arguments["list"]
    if type(values) is not list or len(values) > MAX_STATIC_VALUES:
        fail("List.filter requires a static List of at most 10000 values")
    filt = arguments["filter"]
    if type(filt) is not Filter:
        fail("List.filter requires a serialized ee.Filter")
    _validate_filter(translator, filt)
    # Self-comparison is the existing recursive validator for finite values,
    # exact integers, arrays, depth, cycles and the shared work budget.
    static_equal(translator, values, values, exact_integers=True)
    selected = []
    for item in values:
        charge(translator)
        if is_feature(item):
            validate_feature(translator, item)
        if _list_filter_match(translator, filt, item):
            selected.append(item)
    copy_work, _ = _measure(translator, selected)
    charge(translator, copy_work)
    return [clone_value(item) for item in selected]


def _dictionary_selection(translator, name, arguments):
    _arguments(translator, name, arguments)
    dictionary = arguments["dictionary"]
    require_dictionary(translator, dictionary)
    selectors = arguments["selectors"]
    require_string_list(translator, selectors, f"{name} selectors")
    ignore_missing = arguments.get("ignoreMissing", False)
    if ignore_missing is None:
        ignore_missing = False
    if type(ignore_missing) is not bool:
        fail(f"{name} ignoreMissing must be a boolean")

    charge(translator, len(dictionary))
    keys = tuple(dictionary)
    matched = set()
    for selector in selectors:
        # Compile even on empty dictionaries or ignoreMissing: malformed or
        # unsupported patterns never become successful empty selections.
        pattern = compile_pattern(translator, selector, keys)
        selected_keys = [key for key in keys if pattern.fullmatch(key) is not None]
        matched.update(selected_keys)
        if not selected_keys and not ignore_missing:
            fail(f"{name} selector did not match a key: {selector!r}")

    # Iterating the source mapping keeps insertion order. Duplicate selectors
    # cannot duplicate keys, and null-valued entries remain ordinary values.
    if name == "Dictionary.select":
        entries = [(key, value) for key, value in dictionary.items() if key in matched]
    else:
        entries = [(key, value) for key, value in dictionary.items() if key not in matched]
    copy_work, _ = measure_entries(translator, entries)
    charge(translator, copy_work)
    return clone_entries(entries)


def invoke_static_container_selection(translator, name, arguments):
    """Evaluate the supported pinned List.filter and Dictionary selectors."""
    if name == "List.filter":
        return _list_filter(translator, arguments)
    if name in {"Dictionary.remove", "Dictionary.select"}:
        return _dictionary_selection(translator, name, arguments)
    fail(f"Unsupported static container selection operation: {name}")
