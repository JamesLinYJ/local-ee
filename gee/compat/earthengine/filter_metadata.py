"""Evaluate bounded filters against finite collection metadata and footprints."""
from __future__ import annotations

import math

from .date_values import millis, utc_date
from .filter_normalization import lower_filter_node
from .ir import Filter, fail, integer


_MAX_NOT_NULL_PROPERTIES = 1000


def finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"{label} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or isinstance(value, int) and abs(value) > 2**53:
        fail(f"{label} must be a finite, exactly representable number")
    return value


def field_name(value, label):
    if not isinstance(value, str) or not value or "." in value:
        fail(f"{label} requires a nonempty flat metadata property name")
    return value


def max_difference_arguments(arguments):
    difference = finite_number(
        arguments.get("difference"), "Filter.maxDifference difference",
    )
    for side in ("left", "right"):
        fields = [key for key in (side + "Field", side + "Value") if key in arguments]
        if len(fields) != 1:
            fail("Filter.maxDifference requires exactly one field or value on each side")
        if side + "Field" in arguments:
            field_name(arguments[side + "Field"], "Filter.maxDifference")
        else:
            finite_number(arguments[side + "Value"], "Filter.maxDifference operand")
    return difference


def _charge(translator, count=1):
    translator.steps += count
    if translator.steps > 50000:
        fail("Earth Engine graph exceeds compilation limits")


def matches_filter(translator, filt, item):
    arguments, name = filt.args, filt.name
    try:
        lowered = lower_filter_node(name, arguments)
    except (TypeError, ValueError, KeyError, OverflowError) as exc:
        fail(str(exc))
    if lowered.name != name or lowered.args is not arguments:
        return matches_filter(translator, lowered, item)
    if name in {"and", "or"}:
        values = [matches_filter(translator, child, item) for child in arguments["filters"]]
        return all(values) if name == "and" else any(values)
    if name == "not":
        return not matches_filter(translator, arguments["filter"], item)
    properties = item.get("properties", {})
    if name == "notNull":
        # A filter passes only when each named property is present and non-null;
        # other falsey JSON values remain present. An empty list passes every item.
        # Charge every item even for an empty list so a large catalogue cannot bypass
        # the decoder's existing total compilation budget.
        for key in (None, *arguments["properties"]):
            _charge(translator)
            if key is not None and (key not in properties or properties[key] is None):
                return False
        return True
    if name == "hasGeometry":
        return item.get("geometry") is not None
    if name == "maxDifference":
        difference = max_difference_arguments(arguments)
        values = []
        for side in ("left", "right"):
            field_key, value_key = side + "Field", side + "Value"
            if field_key in arguments:
                _charge(translator)
                value = properties.get(arguments[field_key])
                # Missing and null metadata do not satisfy numeric filters.
                if value is None:
                    return False
            else:
                value = arguments[value_key]
            values.append(finite_number(value, "Filter.maxDifference operand"))
        _charge(translator)
        distance = abs(values[0] - values[1])
        if not math.isfinite(distance):
            fail("Filter.maxDifference operands must produce a finite difference")
        return distance <= difference
    if name == "dateRangeContains":
        if arguments.get("rightField") != "system:time_start" or "leftValue" not in arguments:
            fail("Only system:time_start date filtering is supported")
        from .date_ranges import UnboundedDateRange, is_date_range

        value = arguments["leftValue"]
        if isinstance(value, UnboundedDateRange) or not is_date_range(value):
            fail("Filter.dateRangeContains requires a finite DateRange")
        start, end = value
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
        if (set(arguments) - {"leftField", "rightValue", "maxError"}
                or arguments.get("leftField") != ".all"
                or "rightValue" not in arguments):
            fail("Only collection footprint intersection filtering is supported")
        if "maxError" in arguments and arguments["maxError"] is not None:
            fail("Filter.intersects maxError is unsupported")
        geometry = arguments["rightValue"]
        from shapely.geometry import shape

        try:
            if not isinstance(geometry, dict):
                raise ValueError("intersection value must be GeoJSON")
            if geometry.get("type") == "Feature":
                geometry = geometry.get("geometry")
            filter_geometry = shape(geometry)
            # Null or absent source geometry is a valid non-match, after validating
            # the supplied filter geometry and the full intersects signature.
            if item.get("geometry") is None:
                return False
            return shape(item["geometry"]).intersects(filter_geometry)
        except (ValueError, KeyError, TypeError) as exc:
            fail(f"Invalid footprint filter geometry: {exc}")

    def operand(side):
        field_key, value_key = side + "Field", side + "Value"
        if field_key in arguments:
            key = arguments[field_key]
            if key not in properties:
                fail(f"Item metadata property is unavailable: {key}")
            return properties[key]
        if value_key in arguments:
            return arguments[value_key]
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
            if not isinstance(left, str) or not isinstance(right, str):
                fail("Filter.stringContains requires string operands")
            return right in left
        if name in {"stringStartsWith", "stringEndsWith"}:
            if not isinstance(left, str) or not isinstance(right, str):
                fail(f"Filter.{name} requires string operands")
            _charge(translator, min(len(left), len(right)))
            if name == "stringStartsWith":
                return left.startswith(right)
            return left.endswith(right)
        if name in {"inList", "listContains"}:
            if name == "inList":
                left, right = right, left
            if not isinstance(left, list):
                fail("Filter.inList requires a list operand")
            return right in left
    except TypeError:
        fail("Metadata filter operands have incompatible types")
    fail(f"Unsupported metadata filter: Filter.{name}")
