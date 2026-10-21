"""Bounded metadata joins over local image frames, retaining their pixel IR."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from .ir import ImageSequence, fail
from .join_conditions import (
    evaluate_condition, matches_condition, measure_condition,
    scalar_value as _scalar, validate_condition,
)


JOIN_FUNCTIONS = frozenset({
    "Join.simple", "Join.inverted", "Join.saveFirst", "Join.saveAll",
    "Join.saveBest", "Join.apply",
})


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
    validate_condition(translator, condition)
    measurement_requested = join.operation == "saveBest" or join.measure_key is not None
    measured_filter = measure_condition(condition) if measurement_requested else None
    if join.operation == "saveBest" and measured_filter is None:
        fail("Join.saveBest requires a single Filter.maxDifference condition")
    if join.measure_key is not None and measured_filter is None:
        fail("Join measures with measureKey require a single Filter.maxDifference condition")
    from ...ee_collections import frames

    primary = frames(translator, args.get("primary"))
    secondary = frames(translator, args.get("secondary"))
    if len(primary) > 1000 or len(secondary) > 1000:
        fail("Local joins support at most 1000 images per collection")
    output = []
    for image in primary:
        matches = []
        for candidate in secondary:
            if measurement_requested:
                matched, measure = evaluate_condition(translator, condition, image, candidate)
            else:
                matched = matches_condition(translator, condition, image, candidate)
                measure = None
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
            categories = {
                "number" if type(key) in {int, float} else type(key).__name__
                for key in keys
            }
            if len(categories) > 1:
                fail("Join ordering values must have compatible scalar types")
            comparisons = max(1, math.ceil(math.log2(max(2, len(keys)))))
            _charge(translator, len(keys) * comparisons)
            if categories == {"str"}:
                # A comparison may scan a shared long prefix. Charge every key
                # once per comparison level, matching FeatureCollection.sort.
                _charge(translator, sum(map(len, keys)) * comparisons)
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
