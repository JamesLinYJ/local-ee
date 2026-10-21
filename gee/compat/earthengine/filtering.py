"""Collection filter construction and local metadata/footprint predicates."""
from __future__ import annotations

import math

from .date_values import millis, utc_date
from .ir import Filter, fail, integer


_FILTERS = {
    "and", "or", "not", "dateRangeContains", "intersects", "equals",
    "lessThan", "greaterThan", "stringContains", "inList", "listContains",
    "calendarRange", "notNull", "maxDifference",
}
_MAX_NOT_NULL_PROPERTIES = 1000


def _finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"{label} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or isinstance(value, int) and abs(value) > 2**53:
        fail(f"{label} must be a finite, exactly representable number")
    return value


def _field(value, label):
    if not isinstance(value, str) or not value or "." in value:
        fail(f"{label} requires a nonempty flat metadata property name")
    return value


def _max_difference_arguments(arguments):
    difference = _finite_number(arguments.get("difference"), "Filter.maxDifference difference")
    for side in ("left", "right"):
        fields = [key for key in (side + "Field", side + "Value") if key in arguments]
        if len(fields) != 1:
            fail("Filter.maxDifference requires exactly one field or value on each side")
        if side + "Field" in arguments:
            _field(arguments[side + "Field"], "Filter.maxDifference")
        else:
            _finite_number(arguments[side + "Value"], "Filter.maxDifference operand")
    return difference


def _charge(translator, count=1):
    translator.steps += count
    if translator.steps > 50000:
        fail("Earth Engine graph exceeds compilation limits")


def invoke_filter(translator, name, arguments):
    operation = name.split(".", 1)[1]
    if operation not in _FILTERS:
        fail(f"Unsupported filter: {name}")
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
    else:
        fields = {"leftField", "leftValue", "rightField", "rightValue"}
        if operation == "intersects":
            fields.add("maxError")
        translator.allowed(arguments, fields)
    for side in ("left", "right"):
        if side + "Field" in arguments and side + "Value" in arguments:
            fail("Filter operands cannot specify both field and value")
    return Filter(operation, arguments)


def matches_filter(translator, filt, item):
    arguments, name = filt.args, filt.name
    if name in {"and", "or"}:
        values = [matches_filter(translator, child, item) for child in arguments["filters"]]
        return all(values) if name == "and" else any(values)
    if name == "not":
        return not matches_filter(translator, arguments["filter"], item)
    properties = item.get("properties", {})
    if name == "notNull":
        # The pinned official signature describes this as passing when all named
        # properties are non-null. Missing and explicit null values both fail;
        # other falsey JSON values remain present and non-null. An empty list
        # therefore passes every item by the literal all-properties predicate.
        # Catalogue metadata is not part of the serialized DAG. Charge this
        # work explicitly so an item/property cross product cannot bypass the
        # decoder's existing total compilation budget. Count each item even
        # when the property list is empty, and stop as soon as the predicate
        # fails rather than scanning unrelated properties.
        for key in (None, *arguments["properties"]):
            translator.steps += 1
            if translator.steps > 50000:
                fail("Earth Engine graph exceeds compilation limits")
            if key is not None and (key not in properties or properties[key] is None):
                return False
        return True
    if name == "maxDifference":
        difference = _max_difference_arguments(arguments)
        values = []
        for side in ("left", "right"):
            field_name = side + "Field"
            value_name = side + "Value"
            if field_name in arguments:
                _charge(translator)
                value = properties.get(arguments[field_name])
                # A missing or null property does not satisfy a numeric filter.
                if value is None:
                    return False
            else:
                value = arguments[value_name]
            values.append(_finite_number(value, "Filter.maxDifference operand"))
        _charge(translator)
        distance = abs(values[0] - values[1])
        if not math.isfinite(distance):
            fail("Filter.maxDifference operands must produce a finite difference")
        return distance <= difference
    if name == "dateRangeContains":
        if arguments.get("rightField") != "system:time_start" or "leftValue" not in arguments:
            fail("Only system:time_start date filtering is supported")
        start, end = arguments["leftValue"]
        if "system:time_start" not in properties:
            fail("Item metadata property is unavailable: system:time_start")
        return start <= millis(properties["system:time_start"]) < end
    if name == "calendarRange":
        if "system:time_start" not in properties:
            fail("Item metadata property is unavailable: system:time_start")
        date = utc_date(properties["system:time_start"])
        fields = {
            "year": date.year,
            "month": date.month,
            "day_of_year": date.timetuple().tm_yday,
            "day_of_month": date.day,
            "day_of_week": date.isoweekday(),
            "hour": date.hour,
            "minute": date.minute,
        }
        field = arguments.get("field", "day_of_year")
        if field not in fields:
            fail(f"Unsupported calendar field: {field}")
        start = integer(arguments["start"], "Calendar start")
        end = integer(arguments.get("end", start), "Calendar end")
        value = fields[field]
        return start <= value <= end if start <= end else value >= start or value <= end
    if name == "intersects":
        if arguments.get("leftField") != ".all" or "rightValue" not in arguments:
            fail("Only collection footprint intersection filtering is supported")
        geometry = arguments["rightValue"]
        if geometry.get("type") == "Feature":
            geometry = geometry["geometry"]
        from shapely.geometry import shape

        try:
            return shape(item["geometry"]).intersects(shape(geometry))
        except (ValueError, KeyError, TypeError) as exc:
            fail(f"Invalid footprint filter geometry: {exc}")

    def operand(side):
        if side + "Field" in arguments:
            field = arguments[side + "Field"]
            if field not in properties:
                fail(f"Item metadata property is unavailable: {field}")
            return properties[field]
        if side + "Value" in arguments:
            return arguments[side + "Value"]
        fail("Filter operand is missing")

    left, right = operand("left"), operand("right")
    try:
        if name == "equals":
            return left == right
        if name == "lessThan":
            return left < right
        if name == "greaterThan":
            return left > right
        if name == "stringContains":
            return right in left
        if name in {"inList", "listContains"}:
            if name == "inList":
                left, right = right, left
            if not isinstance(left, list):
                fail("Filter.inList requires a list operand")
            return right in left
    except TypeError:
        fail("Metadata filter operands have incompatible types")
    fail(f"Unsupported metadata filter: Filter.{name}")


class FilteringOperations:
    def matches(self, filt, item):
        return matches_filter(self, filt, item)
