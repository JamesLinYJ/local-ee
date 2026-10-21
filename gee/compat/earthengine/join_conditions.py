"""Bounded validation and evaluation for local image-join conditions."""
from __future__ import annotations

import math

from .filtering import _finite_number, _max_difference_arguments
from .ir import Filter, fail


_COMPARISONS = {"equals", "lessThan", "greaterThan"}
_LOGICAL = {"and", "or"}
_MAX_DEPTH = 32
_MAX_CHILDREN = 1000
_MAX_NODES = 50000


def _charge(translator, count=1):
    translator.steps += count
    if translator.steps > _MAX_NODES:
        fail("Earth Engine graph exceeds compilation limits")


def _field(value, label):
    if not isinstance(value, str) or not value or "." in value:
        fail(f"{label} requires a nonempty flat metadata property name")
    return value


def scalar_value(value):
    if isinstance(value, bool) or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if finite:
            return value
    fail("Join comparisons require finite scalar metadata values")


_scalar = scalar_value


def _logical_children(translator, condition, op):
    args = condition.args
    if op in _LOGICAL:
        translator.allowed(args, {"filters"})
        children = args.get("filters")
        if not isinstance(children, list) or len(children) > _MAX_CHILDREN:
            fail("Join compound filters require at most 1000 child filters")
        return children
    translator.allowed(args, {"filter"})
    return [args.get("filter")]


def _validate(translator, condition, depth=0):
    _charge(translator)
    if depth > _MAX_DEPTH or not isinstance(condition, Filter) or not isinstance(condition.args, dict):
        fail("Join condition must be a bounded ee.Filter")
    args, op = condition.args, condition.name
    if op in _LOGICAL or op == "not":
        children = _logical_children(translator, condition, op)
        for child in children:
            _validate(translator, child, depth + 1)
        return
    if op in _COMPARISONS:
        translator.allowed(args, {"leftField", "leftValue", "rightField", "rightValue"})
        for side in ("left", "right"):
            fields = [key for key in (side + "Field", side + "Value") if key in args]
            if len(fields) != 1:
                fail("Join filter requires exactly one field or value on each side")
            if side + "Field" in args:
                _field(args[side + "Field"], "Join filter")
            else:
                _scalar(args[side + "Value"])
        return
    if op == "maxDifference":
        translator.allowed(args, {"difference", "leftField", "leftValue", "rightField", "rightValue"})
        if "difference" not in args:
            fail("Filter.maxDifference requires difference")
        _max_difference_arguments(args)
        return
    fail(f"Unsupported local join condition: Filter.{op}")


def validate_condition(translator, condition):
    """Validate a join predicate's supported structure, arguments, and bounds."""
    _validate(translator, condition)


def _measure_scan(condition, depth=0, nodes=None):
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if nodes[0] > _MAX_NODES or depth > _MAX_DEPTH:
        fail("Join condition exceeds compilation limits")
    if not isinstance(condition, Filter) or not isinstance(condition.args, dict):
        fail("Join condition must be a bounded ee.Filter")
    op, args = condition.name, condition.args
    if op == "maxDifference":
        return condition
    if op in _LOGICAL:
        children = args.get("filters")
        if not isinstance(children, list) or len(children) > _MAX_CHILDREN:
            fail("Join compound filters require at most 1000 child filters")
        measures = [_measure_scan(child, depth + 1, nodes) for child in children]
        present = [item for item in measures if item is not None]
        if op == "and":
            if len(present) > 1:
                fail("Join conditions have multiple maxDifference measures; compound measures are unsupported")
            return present[0] if present else None
        if present:
            fail("Join Filter.or cannot contain a measured Filter.maxDifference; compound measures are unsupported")
        return None
    if op == "not":
        if _measure_scan(args.get("filter"), depth + 1, nodes) is not None:
            fail("Join Filter.not cannot contain a measured Filter.maxDifference; compound measures are unsupported")
        return None
    if op in _COMPARISONS:
        return None
    fail(f"Unsupported local join condition: Filter.{op}")


def measure_condition(condition):
    """Return the unique maxDifference filter, rejecting ambiguous placement."""
    return _measure_scan(condition)


def _comparison(translator, condition, primary_image, secondary_image):
    args, op = condition.args, condition.name
    values = []
    for side, image in (("left", primary_image), ("right", secondary_image)):
        field = side + "Field"
        if field in args:
            _charge(translator)
            value = image.props.get(args[field])
        else:
            value = args[side + "Value"]
        # Preserve the existing scalar join policy: missing and null operands
        # fail the leaf predicate, including the child of Filter.not.
        if value is None:
            return False
        values.append(_scalar(value))
    left, right = values
    same_kind = type(left) is type(right) or (
        type(left) in {int, float} and type(right) in {int, float}
    )
    if op == "equals":
        if same_kind and isinstance(left, str):
            _charge(translator, min(len(left), len(right)))
        return same_kind and left == right
    if not same_kind:
        fail("Join ordered comparisons need compatible metadata types")
    if isinstance(left, str):
        _charge(translator, min(len(left), len(right)))
    return left < right if op == "lessThan" else left > right


def max_difference(translator, condition, primary_image, secondary_image):
    """Return an inclusive absolute numeric measure, or None when it fails."""
    _charge(translator)
    if not isinstance(condition, Filter) or condition.name != "maxDifference" or not isinstance(condition.args, dict):
        fail("Join measure must be a Filter.maxDifference")
    args = condition.args
    translator.allowed(args, {"difference", "leftField", "leftValue", "rightField", "rightValue"})
    difference = _max_difference_arguments(args)
    values = []
    for side, image in (("left", primary_image), ("right", secondary_image)):
        field_name = side + "Field"
        if field_name in args:
            _charge(translator)
            value = image.props.get(args[field_name])
            if value is None:
                return None
        else:
            value = args[side + "Value"]
        values.append(_finite_number(value, "Filter.maxDifference operand"))
    _charge(translator)
    distance = abs(values[0] - values[1])
    if not math.isfinite(distance):
        fail("Filter.maxDifference operands must produce a finite difference")
    return distance if distance <= difference else None


def _evaluate(translator, condition, primary_image, secondary_image):
    # Direct measured joins previously charged only the numeric predicate.
    # Keep that work accounting unchanged as the compound path is added.
    if condition.name == "maxDifference":
        measure = max_difference(translator, condition, primary_image, secondary_image)
        return measure is not None, measure
    _charge(translator)
    args, op = condition.args, condition.name
    if op == "and":
        measure = None
        for child in args["filters"]:
            matched, child_measure = _evaluate(translator, child, primary_image, secondary_image)
            if not matched:
                return False, None
            if child_measure is not None:
                if measure is not None:
                    fail("Join conditions have multiple maxDifference measures; compound measures are unsupported")
                measure = child_measure
        return True, measure
    if op == "or":
        for child in args["filters"]:
            matched, measure = _evaluate(translator, child, primary_image, secondary_image)
            if measure is not None:
                fail("Join Filter.or cannot contain a measured Filter.maxDifference; compound measures are unsupported")
            if matched:
                return True, None
        return False, None
    if op == "not":
        matched, measure = _evaluate(translator, args["filter"], primary_image, secondary_image)
        if measure is not None:
            fail("Join Filter.not cannot contain a measured Filter.maxDifference; compound measures are unsupported")
        return not matched, None
    return _comparison(translator, condition, primary_image, secondary_image), None


def evaluate_condition(translator, condition, primary_image, secondary_image):
    """Evaluate a validated unique-measure predicate and return its measure."""
    return _evaluate(translator, condition, primary_image, secondary_image)


def _matches(translator, condition, primary_image, secondary_image):
    """Evaluate any validated boolean condition, whether or not it has measures."""
    if condition.name == "maxDifference":
        return max_difference(translator, condition, primary_image, secondary_image) is not None
    _charge(translator)
    args, op = condition.args, condition.name
    if op == "and":
        return all(_matches(translator, child, primary_image, secondary_image) for child in args["filters"])
    if op == "or":
        return any(_matches(translator, child, primary_image, secondary_image) for child in args["filters"])
    if op == "not":
        return not _matches(translator, args["filter"], primary_image, secondary_image)
    return _comparison(translator, condition, primary_image, secondary_image)


def matches_condition(translator, condition, primaryImage, secondaryImage):
    """Evaluate any previously validated join predicate as a boolean."""
    return _matches(translator, condition, primaryImage, secondaryImage)
