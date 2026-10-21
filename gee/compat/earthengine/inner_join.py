"""Bounded inner joins that materialize matching image pairs as Features."""
from __future__ import annotations

from dataclasses import dataclass

from .ir import Image, fail
from .join_conditions import (
    evaluate_condition,
    matches_condition,
    measure_condition,
    validate_condition,
)


MAX_INPUT_IMAGES = 1000
MAX_OUTPUT_PAIRS = 1000


@dataclass(frozen=True)
class InnerJoin:
    """The property keys used by a pinned ``Join.inner`` invocation."""

    primary_key: str
    secondary_key: str
    measure_key: str | None = None


def _charge(translator, amount=1):
    translator.steps += amount
    if translator.steps > 50000:
        fail("Earth Engine graph exceeds compilation limits")


def _property_key(value, label):
    if not isinstance(value, str) or not value or "." in value:
        fail(f"{label} requires a nonempty flat property key")
    return value


def construct_inner(translator, args) -> InnerJoin:
    """Validate pinned Join.inner arguments and retain only its typed keys."""
    translator.allowed(args, {"primaryKey", "secondaryKey", "measureKey"})
    primary_key = _property_key(args.get("primaryKey", "primary"), "primaryKey")
    secondary_key = _property_key(args.get("secondaryKey", "secondary"), "secondaryKey")
    measure_key = args.get("measureKey")
    if measure_key is not None:
        measure_key = _property_key(measure_key, "measureKey")
    if primary_key == secondary_key or measure_key in {primary_key, secondary_key}:
        fail("Join.inner primaryKey, secondaryKey, and measureKey must be distinct")

    # Account for configured property names before retaining them in the IR.
    key_chars = len(primary_key) + len(secondary_key)
    if measure_key is not None:
        key_chars += len(measure_key)
    _charge(translator, 1 + key_chars)
    return InnerJoin(primary_key, secondary_key, measure_key)


def _charge_feature(translator, join):
    key_count = 5
    key_chars = (
        len("type") + len("geometry") + len("properties")
        + len(join.primary_key) + len(join.secondary_key)
    )
    if join.measure_key is not None:
        key_count += 1
        key_chars += len(join.measure_key)
    # Charge object fields and every repeated property-key character before
    # allocating the two dictionaries for this result Feature.
    _charge(translator, 2 + key_count + key_chars)


def apply_inner(translator, args) -> dict:
    """Return a bounded FeatureCollection whose properties retain real Images."""
    translator.allowed(args, {"join", "primary", "secondary", "condition"})
    join = args.get("join")
    if not isinstance(join, InnerJoin):
        fail("Join.apply requires a Join.inner instance")

    condition = args.get("condition")
    validate_condition(translator, condition)
    measured_filter = measure_condition(condition) if join.measure_key is not None else None
    if join.measure_key is not None and measured_filter is None:
        fail("Join.inner measureKey requires a unique Filter.maxDifference measure")

    from ...ee_collections import frames

    primary = frames(translator, args.get("primary"))
    secondary = frames(translator, args.get("secondary"))
    if len(primary) > MAX_INPUT_IMAGES or len(secondary) > MAX_INPUT_IMAGES:
        fail("Join.inner supports at most 1000 Images in each collection")
    for collection in (primary, secondary):
        for image in collection:
            _charge(translator)
            if not isinstance(image, Image):
                fail("Join.inner requires ImageCollections containing concrete Images")

    # Charge the outer result envelope before allocating its feature list.
    _charge(translator, 4 + len("FeatureCollection") + len("features") + len("type"))
    features = []
    for primary_image in primary:
        for secondary_image in secondary:
            # Pair checks are the dominant work for sparse joins, so charge
            # before evaluating the condition.
            _charge(translator)
            if join.measure_key is not None:
                matched, measure = evaluate_condition(
                    translator, condition, primary_image, secondary_image)
            else:
                matched = matches_condition(translator, condition, primary_image, secondary_image)
                measure = None
            if not matched:
                continue

            if len(features) >= MAX_OUTPUT_PAIRS:
                fail("Join.inner supports at most 1000 matched output pairs")

            if join.measure_key is not None and measure is None:
                fail("Join condition matched without its required maxDifference measure")

            _charge_feature(translator, join)

            properties = {
                join.primary_key: primary_image,
                join.secondary_key: secondary_image,
            }
            if join.measure_key is not None:
                properties[join.measure_key] = measure
            features.append({
                "type": "Feature",
                "geometry": None,
                "properties": properties,
            })

    return {"type": "FeatureCollection", "features": features}
