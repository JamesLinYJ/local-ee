"""Pinned ErrorMargin constructor and typed-consumer contract."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.error_margin import (
    ERROR_MARGIN_ARGUMENTS,
    ErrorMarginValue,
    construct_error_margin,
    validate_no_reprojection_margin,
)
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.public_values import public_value


ROOT = Path(__file__).resolve().parents[1]


def translator(steps=0):
    result = Translator([], {}, {})
    result.steps = steps
    return result


def construct(args, *, steps=0):
    return construct_error_margin(translator(steps), args)


def test_signature_matches_the_pinned_algorithm_catalog():
    algorithms = json.loads(
        (ROOT / "vendor/earthengine-js/algorithms.json").read_text(encoding="utf-8")
    )["algorithms"]
    signature = next(
        item for item in algorithms if item["name"] == "algorithms/ErrorMargin"
    )
    assert signature["returnType"] == "ErrorMargin"
    assert ERROR_MARGIN_ARGUMENTS == {
        "ErrorMargin": (frozenset(), frozenset({"value", "unit"})),
    }
    assert [
        (arg["argumentName"], arg["type"], arg["optional"], arg["defaultValue"])
        for arg in signature["arguments"]
    ] == [("value", "Float", True, None), ("unit", "String", True, "meters")]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"value": 0}, ErrorMarginValue(0.0, "meters")),
        ({"value": 12}, ErrorMarginValue(12.0, "meters")),
        ({"value": -12.5, "unit": "projected"}, ErrorMarginValue(12.5, "projected")),
        ({"value": -0.0}, ErrorMarginValue(0.0, "meters")),
        ({"value": 0.0009, "unit": "projected"}, ErrorMarginValue(0.0009, "projected")),
        ({"value": 0.001}, ErrorMarginValue(0.001, "meters")),
        ({"value": 19_999_999}, ErrorMarginValue(19_999_999.0, "meters")),
        ({"value": 20_000_000}, ErrorMarginValue(None, "infinite")),
        ({"value": -20_000_000, "unit": "projected"}, ErrorMarginValue(None, "infinite")),
        ({"value": 10**1000}, ErrorMarginValue(None, "infinite")),
        ({"unit": "infinite"}, ErrorMarginValue(None, "infinite")),
        ({"value": 0.0001, "unit": "infinite"}, ErrorMarginValue(None, "infinite")),
    ],
)
def test_constructor_normalizes_finite_and_infinite_margins(args, expected):
    assert construct(args) == expected


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"value": None},
        {"value": None, "unit": "meters"},
        {"value": True},
        {"value": "1"},
        {"value": []},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": -0.0009, "unit": "meters"},
        {"value": 1, "unit": "feet"},
        {"value": 1, "unit": 5},
        {"value": 1, "extra": 2},
        {"value": 1, "unit": "m" * 10},
    ],
)
def test_constructor_rejects_malformed_or_unsupported_inputs(args):
    with pytest.raises(UnsupportedEEError):
        construct(args)


def test_constructor_requires_bounded_arguments_and_honors_shared_work_budget():
    with pytest.raises(UnsupportedEEError, match="bounded dictionary"):
        construct_error_margin(translator(), {"value": 1, "unit": "meters", "x": 3})
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        construct({"value": 1}, steps=49_993)
    for invalid_steps in (True, -1, 50_001):
        with pytest.raises(UnsupportedEEError, match="50000-step"):
            construct_error_margin(translator(invalid_steps), {"value": 1})


def test_value_is_frozen_and_remains_opaque_at_the_public_boundary():
    value = construct({"value": 1, "unit": "projected"})
    with pytest.raises(FrozenInstanceError):
        value.magnitude = 2.0
    with pytest.raises(UnsupportedEEError, match="Unsupported internal value"):
        public_value(value)


def test_same_projection_helper_requires_a_typed_or_sdk_numeric_margin():
    t = translator()
    typed = construct_error_margin(t, {"value": 3, "unit": "projected"})
    assert validate_no_reprojection_margin(t, None, "ROI margin") is None
    assert validate_no_reprojection_margin(t, typed, "ROI margin") is typed
    assert validate_no_reprojection_margin(t, 2, "ROI margin") == ErrorMarginValue(
        2.0, "meters",
    )
    assert validate_no_reprojection_margin(t, 2.5, "ROI margin") == ErrorMarginValue(
        2.5, "meters",
    )
    for value in (True, "2", {"value": 2, "unit": "meters"}):
        with pytest.raises(UnsupportedEEError, match="static ErrorMargin"):
            validate_no_reprojection_margin(t, value, "ROI margin")


def test_helper_rechecks_the_frozen_value_invariant_and_work_budget():
    t = translator()
    value = ErrorMarginValue(1.0, "meters")
    object.__setattr__(value, "magnitude", -1.0)
    with pytest.raises(UnsupportedEEError, match="normalized ErrorMargin"):
        validate_no_reprojection_margin(t, value, "ROI margin")

    with pytest.raises(UnsupportedEEError, match="50000-step"):
        validate_no_reprojection_margin(translator(50_000), ErrorMarginValue(1.0, "meters"), "ROI margin")

