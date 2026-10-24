"""Bounded Feature predicate evaluation for inline synthetic metadata.

Ordered comparisons over absent/null properties produce UNKNOWN. Not preserves
UNKNOWN, while And/Or use three-valued truth tables before the collection
boundary rejects a final UNKNOWN.
This preserves the pinned SDK's gte/lte aliases, which serialize as Not(lt/gt).
Google execution parity for the null policy has not been tested. Equality with
missing or null operands is rejected because its engine semantics are unclear.
"""
from __future__ import annotations

from .array_values import StaticArray
from .feature_values import charge, property_name
from .filter_structure import FILTER_ARGUMENTS as _ARGUMENTS, validate_filter_structure
from .filter_normalization import lower_filter_node
from .ir import Filter, fail


_UNKNOWN = object()


def _operands(translator, arguments, properties):
    values = []
    for side in ("left", "right"):
        field_key, value_key = side + "Field", side + "Value"
        has_field, has_value = field_key in arguments, value_key in arguments
        if has_field == has_value:
            fail("Feature filters require exactly one field or value per operand")
        if has_field:
            key = property_name(arguments[field_key])
            if not key or "." in key:
                fail("Feature filters require nonempty flat property names")
            charge(translator)
            if key not in properties or properties[key] is None:
                values.append(_UNKNOWN)
            else:
                values.append(properties[key])
        else:
            values.append(arguments[value_key])
    return values


def _scalar_kind(value, label):
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


def _contains_scalar(translator, candidates, sequence, label):
    if not isinstance(sequence, list):
        fail(f"{label} requires a list operand")
    candidate_kind = _scalar_kind(candidates, label)
    found = False
    for item in sequence:
        charge(translator)
        item_kind = _scalar_kind(item, label)
        if item_kind == candidate_kind == "string":
            charge(translator, min(len(item), len(candidates)))
        if item_kind == candidate_kind and item == candidates:
            found = True
    return found


def _charge_string_comparison(translator, left, right):
    if isinstance(left, str) and isinstance(right, str):
        charge(translator, min(len(left), len(right)))


def matches_feature_filter(translator, filt, feature, depth=0):
    """Return True/False or an internal UNKNOWN sentinel for a feature."""
    charge(translator)
    if depth > 32:
        fail("Feature filter nesting exceeds the depth limit")
    if not isinstance(filt, Filter) or not isinstance(filt.args, dict):
        fail("Inline FeatureCollection.filter requires a serialized ee.Filter")
    name, arguments = filt.name, filt.args
    try:
        lowered = lower_filter_node(name, arguments)
    except (TypeError, ValueError, KeyError, OverflowError) as exc:
        fail(str(exc))
    if lowered.name != name or lowered.args is not arguments:
        return matches_feature_filter(translator, lowered, feature, depth)
    allowed = _ARGUMENTS.get(name)
    if allowed is None:
        fail(f"Unsupported inline Feature filter: Filter.{name}")
    translator.allowed(arguments, allowed)

    if name in {"and", "or"}:
        children = arguments.get("filters")
        if not isinstance(children, list) or len(children) > 1000:
            fail(f"Filter.{name} requires at most 1000 child filters")
        # Visit every branch so malformed or unsupported children cannot hide
        # behind ordinary boolean short-circuiting. Each visit charges budget.
        values = [matches_feature_filter(translator, child, feature, depth + 1)
                  for child in children]
        if name == "and":
            if any(value is False for value in values):
                return False
            return True if all(value is True for value in values) else _UNKNOWN
        if any(value is True for value in values):
            return True
        return False if all(value is False for value in values) else _UNKNOWN
    if name == "not":
        value = matches_feature_filter(translator, arguments.get("filter"), feature, depth + 1)
        return _UNKNOWN if value is _UNKNOWN else not value

    properties = feature["properties"]
    if name == "hasGeometry":
        return feature.get("geometry") is not None
    if name == "notNull":
        keys = arguments.get("properties")
        if not isinstance(keys, list) or len(keys) > 1000:
            fail("Filter.notNull supports at most 1000 property names")
        if any(not isinstance(key, str) for key in keys):
            fail("Filter.notNull properties must be a list of strings")
        return translator.matches(filt, feature)
    if name == "calendarRange":
        if "start" not in arguments:
            fail("Filter.calendarRange requires start")
        return translator.matches(filt, feature)
    if name == "dateRangeContains":
        if set(arguments) != {"leftValue", "rightField"}:
            fail("Only system:time_start date filtering is supported")
        return translator.matches(filt, feature)
    if name == "intersects":
        if "maxError" in arguments and arguments["maxError"] is not None:
            fail("Feature geometry filter maxError is unsupported")
        if set(arguments) - {"maxError", "leftField", "rightValue"}:
            fail("Only collection footprint intersection filtering is supported")
        return translator.matches(filt, feature)
    if name == "maxDifference":
        if "difference" not in arguments:
            fail("Filter.maxDifference requires difference")
        _operands(translator, arguments, properties)
        return translator.matches(filt, feature)

    if name == "equals" and any(
        side + "Field" not in arguments and side + "Value" not in arguments
        for side in ("left", "right")
    ):
        # The SDK omits a constantValue for a Python None argument, so an
        # absent operand and an omitted null cannot be distinguished here.
        fail("Feature filter equality involving missing/null values is unsupported")
    left, right = _operands(translator, arguments, properties)
    if name in {"lessThan", "greaterThan"}:
        if left is _UNKNOWN or right is _UNKNOWN or left is None or right is None:
            return _UNKNOWN
        left_kind, right_kind = _scalar_kind(left, "Ordered Feature filters"), _scalar_kind(right, "Ordered Feature filters")
        if left_kind != right_kind or left_kind not in {"number", "string"}:
            fail("Metadata filter operands have incompatible types")
        _charge_string_comparison(translator, left, right)
        try:
            return left < right if name == "lessThan" else left > right
        except TypeError:
            fail("Metadata filter operands have incompatible types")
    if name == "equals":
        if left is _UNKNOWN or right is _UNKNOWN or left is None or right is None:
            fail("Feature filter equality involving missing/null values is unsupported")
        left_kind, right_kind = _scalar_kind(left, "Feature filter equality"), _scalar_kind(right, "Feature filter equality")
        _charge_string_comparison(translator, left, right)
        return left_kind == right_kind and left == right
    if name == "stringContains":
        if not isinstance(left, str) or not isinstance(right, str):
            fail("Filter.stringContains requires string operands")
        charge(translator, len(left) + len(right))
        return right in left
    if name in {"stringStartsWith", "stringEndsWith"}:
        if left is _UNKNOWN or right is _UNKNOWN or left is None or right is None:
            return _UNKNOWN
        if not isinstance(left, str) or not isinstance(right, str):
            fail(f"Filter.{name} requires string operands")
        charge(translator, min(len(left), len(right)))
        return left.startswith(right) if name == "stringStartsWith" else left.endswith(right)
    if name == "inList":
        if left is _UNKNOWN or right is _UNKNOWN or left is None or right is None:
            fail("Filter.inList requires present, non-null operands")
        return _contains_scalar(translator, left, right, "Filter.inList")
    if name == "listContains":
        if left is _UNKNOWN or right is _UNKNOWN or left is None or right is None:
            fail("Filter.listContains requires present, non-null operands")
        return _contains_scalar(translator, right, left, "Filter.listContains")
    return translator.matches(filt, feature)
