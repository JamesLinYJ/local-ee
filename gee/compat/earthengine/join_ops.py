"""Bounded metadata joins over local image frames, retaining their pixel IR."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from .filtering import _finite_number, _max_difference_arguments
from .ir import Filter, ImageSequence, fail


JOIN_FUNCTIONS = frozenset({
    "Join.simple", "Join.inverted", "Join.saveFirst", "Join.saveAll",
    "Join.saveBest", "Join.apply",
})
_COMPARISONS = {"equals", "lessThan", "greaterThan"}


@dataclass(frozen=True)
class Join:
    operation: str
    key: str | None = None
    ordering: str | None = None
    ascending: bool = True
    outer: bool = False
    measure_key: str | None = None


def _charge(translator, count=1):
    translator.steps += count
    if translator.steps > 50000:
        fail("Earth Engine graph exceeds compilation limits")


def _field(value, label):
    if not isinstance(value, str) or not value or "." in value:
        fail(f"{label} requires a nonempty flat metadata property name")
    return value


def _validate_condition(translator, condition, depth=0):
    _charge(translator)
    if depth > 32 or not isinstance(condition, Filter):
        fail("Join condition must be a bounded ee.Filter")
    args, op = condition.args, condition.name
    if op in {"and", "or"}:
        translator.allowed(args, {"filters"})
        if not isinstance(args.get("filters"), list) or len(args["filters"]) > 1000:
            fail("Join compound filters require at most 1000 child filters")
        for child in args["filters"]:
            _validate_condition(translator, child, depth + 1)
    elif op == "not":
        translator.allowed(args, {"filter"})
        _validate_condition(translator, args.get("filter"), depth + 1)
    elif op in _COMPARISONS:
        translator.allowed(args, {"leftField", "leftValue", "rightField", "rightValue"})
        for side in ("left", "right"):
            fields = [key for key in (side + "Field", side + "Value") if key in args]
            if len(fields) != 1:
                fail("Join filter requires exactly one field or value on each side")
            if side + "Field" in args:
                _field(args[side + "Field"], "Join filter")
    elif op == "maxDifference":
        translator.allowed(args, {"difference", "leftField", "leftValue", "rightField", "rightValue"})
        if "difference" not in args:
            fail("Filter.maxDifference requires difference")
        _max_difference_arguments(args)
    else:
        fail(f"Unsupported local join condition: Filter.{op}")


def _scalar(value):
    if isinstance(value, bool) or isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and math.isfinite(value):
        return value
    fail("Join comparisons require finite scalar metadata values")


def _matches(translator, condition, primary, secondary):
    _charge(translator)
    args, op = condition.args, condition.name
    if op == "and":
        return all(_matches(translator, child, primary, secondary) for child in args["filters"])
    if op == "or":
        return any(_matches(translator, child, primary, secondary) for child in args["filters"])
    if op == "not":
        return not _matches(translator, args["filter"], primary, secondary)
    if op == "maxDifference":
        return _max_difference(translator, condition, primary, secondary) is not None
    values = []
    for side, image in (("left", primary), ("right", secondary)):
        if side + "Field" in args:
            _charge(translator)
            value = image.props.get(args[side + "Field"])
        else:
            value = args[side + "Value"]
        # An absent/null field is not an equality key. Preserve the original
        # metadata on outer rows instead of fabricating a match or an image.
        if value is None:
            return False
        values.append(_scalar(value))
    left, right = values
    same_kind = type(left) is type(right) or (
        type(left) in {int, float} and type(right) in {int, float}
    )
    if op == "equals":
        return same_kind and left == right
    if not same_kind:
        fail("Join ordered comparisons need compatible metadata types")
    return left < right if op == "lessThan" else left > right


def _max_difference(translator, condition, primary, secondary):
    """Return the inclusive absolute numeric measure, or None when it fails."""
    _charge(translator)
    args = condition.args
    difference = _max_difference_arguments(args)
    values = []
    for side, image in (("left", primary), ("right", secondary)):
        field_name = side + "Field"
        if field_name in args:
            _charge(translator)
            value = image.props.get(args[field_name])
            # Missing and explicit null values are not numeric join operands.
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


def _has_direct_measure(condition):
    # A single maxDifference filter has one unambiguous numeric measure. A
    # logical composition can contain multiple measures or change their meaning.
    return isinstance(condition, Filter) and condition.name == "maxDifference"


def _construct(translator, name, args):
    op = name.split(".")[1]
    if op in {"simple", "inverted"}:
        translator.allowed(args, set())
        return Join(op)
    if op == "saveBest":
        translator.allowed(args, {"matchKey", "measureKey", "outer"})
        key = _field(args.get("matchKey"), "matchKey")
        measure_key = _field(args.get("measureKey"), "measureKey")
        if "outer" in args and type(args["outer"]) is not bool:
            fail("Join outer must be a boolean")
        return Join(op, key=key, outer=args.get("outer", False), measure_key=measure_key)

    key_name = "matchKey" if op == "saveFirst" else "matchesKey"
    translator.allowed(args, {key_name, "ordering", "ascending", "measureKey", "outer"})
    key = _field(args.get(key_name), key_name)
    ordering = args.get("ordering")
    if ordering is not None:
        ordering = _field(ordering, "Join ordering")
    measure_key = args.get("measureKey")
    if measure_key is not None:
        measure_key = _field(measure_key, "measureKey")
    for option in ("ascending", "outer"):
        if option in args and type(args[option]) is not bool:
            fail(f"Join {option} must be a boolean")
    return Join(
        op, key=key, ordering=ordering, ascending=args.get("ascending", True),
        outer=args.get("outer", False), measure_key=measure_key,
    )


def invoke_join(translator, name, args):
    if name not in JOIN_FUNCTIONS:
        fail(f"Unsupported Earth Engine algorithm: {name}")
    if name != "Join.apply":
        return _construct(translator, name, args)
    translator.allowed(args, {"join", "primary", "secondary", "condition"})
    join = args.get("join")
    if not isinstance(join, Join):
        fail("Join.apply requires a supported ee.Join")
    condition = args.get("condition")
    _validate_condition(translator, condition)
    has_measure = _has_direct_measure(condition)
    if join.operation == "saveBest" and not has_measure:
        fail("Join.saveBest requires a single Filter.maxDifference condition")
    if join.measure_key is not None and not has_measure:
        fail("Join measures with measureKey require a single Filter.maxDifference condition; compound measures are unsupported")
    from ...ee_collections import frames

    primary = frames(translator, args.get("primary"))
    secondary = frames(translator, args.get("secondary"))
    if len(primary) > 1000 or len(secondary) > 1000:
        fail("Local joins support at most 1000 images per collection")
    output = []
    for image in primary:
        matches = []
        for candidate in secondary:
            if condition.name == "maxDifference":
                measure = _max_difference(translator, condition, image, candidate)
                matched = measure is not None
            else:
                measure = None
                matched = _matches(translator, condition, image, candidate)
            if matched:
                matches.append((candidate, measure))
                if join.operation in {"simple", "inverted"} or (
                    join.operation == "saveFirst" and join.ordering is None
                ):
                    break
        if join.operation in {"simple", "inverted"}:
            if bool(matches) == (join.operation == "simple"):
                output.append(image)
            continue
        if not matches:
            if join.outer:
                output.append(image)
            continue
        if join.ordering is not None:
            keys = []
            for candidate, _ in matches:
                _charge(translator)
                if candidate.props.get(join.ordering) is None:
                    fail("Join ordering property is missing or null")
                keys.append(_scalar(candidate.props[join.ordering]))
            if len({"number" if type(key) in {int, float} else type(key).__name__ for key in keys}) > 1:
                fail("Join ordering values must have compatible scalar types")
            matches = [item for _, item in sorted(zip(keys, matches), key=lambda pair: pair[0], reverse=not join.ascending)]
        if join.operation == "saveBest":
            # min() keeps the first secondary source row when measures tie,
            # matching the stable local collection-order policy.
            _charge(translator, len(matches))
            selected = min(matches, key=lambda pair: pair[1])
            saved = selected[0]
            measure = selected[1]
        elif join.operation == "saveFirst":
            saved, measure = matches[0]
        else:
            saved = [item[0] for item in matches]
            measure = None
        if join.measure_key is not None:
            if join.operation == "saveAll":
                saved = [
                    replace(candidate, props={**candidate.props, join.measure_key: distance})
                    for candidate, distance in matches
                ]
            else:
                saved = replace(saved, props={**saved.props, join.measure_key: measure})
        output.append(replace(image, props={**image.props, join.key: saved}))
    return ImageSequence(output)
