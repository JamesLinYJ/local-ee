"""Finite DateRange algebra against independent interval expectations."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gee.compat.earthengine.date_ranges import (
    DATE_RANGE_METHODS,
    UNBOUNDED_DATE_RANGE,
    UnboundedDateRange,
    invoke_date_range,
    is_date_range,
)
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.filtering import matches_filter
from gee.compat.earthengine.ir import Filter, UnsupportedEEError, static_truth
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    with OfflineGuard() as guard:
        client = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        assert client.__version__ == "1.7.49"
        yield client
    assert guard.evidence()["attempt_count"] == 0


def _invoke(name, **arguments):
    return invoke_date_range(Translator([], {}, None), name, arguments)


def _compile(ee, expression):
    encoded = ee.serializer.encode(expression, for_cloud_api=False)
    return compile_expression(encoded, [], {})["value"]


def test_declares_all_pinned_date_range_entry_points():
    assert DATE_RANGE_METHODS == frozenset({
        "DateRange.contains", "DateRange.end", "DateRange.intersection",
        "DateRange.intersects", "DateRange.isEmpty", "DateRange.isUnbounded",
        "DateRange.start", "DateRange.union", "DateRange.unbounded",
    })


def test_constructor_keeps_finite_tuple_and_one_millisecond_default():
    assert _invoke("DateRange", start=1_234) == (1_234.0, 1_235.0)
    assert _invoke("DateRange", start=1_234.25, end=1_235.75) == (1_234.25, 1_235.75)
    assert _invoke("DateRange", start="2020-01-01", end="2020-01-02") == (
        1_577_836_800_000.0, 1_577_923_200_000.0,
    )
    assert is_date_range((0, 1))
    assert not is_date_range((0, float("inf")))
    assert not is_date_range((True, 1))
    assert not is_date_range([0, 1])


def test_finite_millisecond_endpoints_stay_inside_exact_domain():
    maximum = float(2**53)
    assert _invoke("DateRange", start=maximum - 1) == (maximum - 1, maximum)
    assert _invoke("DateRange", start=maximum, end=maximum) == (maximum, maximum)
    assert _invoke("DateRange", start=1.25, end=1.75) == (1.25, 1.75)
    with pytest.raises(UnsupportedEEError, match="advance by one representable"):
        _invoke("DateRange", start=maximum)
    for start, end in ((2**53 + 1, 2**53 + 2), (-2**53 - 1, 0), (0, float("inf"))):
        with pytest.raises(UnsupportedEEError, match="finite and within"):
            _invoke("DateRange", start=start, end=end)


def test_date_wrappers_cannot_hide_integer_precision_loss(ee):
    for value in (2**53 + 1, -(2**53 + 1)):
        for expression in (ee.Date(value), ee.DateRange(ee.Date(value)),
                           ee.DateRange(0, 1).contains(ee.Date(value))):
            with pytest.raises(UnsupportedEEError, match="milliseconds"):
                _compile(ee, expression)
    assert _compile(ee, ee.Date(2**53).millis()) == 2**53


def test_start_end_membership_and_half_open_boundaries():
    bounds = (10.0, 20.0)
    assert _invoke("DateRange.start", dateRange=bounds) == 10.0
    assert _invoke("DateRange.end", dateRange=bounds) == 20.0
    assert _invoke("DateRange.contains", dateRange=bounds, other=10) is True
    assert _invoke("DateRange.contains", dateRange=bounds, other=19.999) is True
    assert _invoke("DateRange.contains", dateRange=bounds, other=20) is False
    assert _invoke("DateRange.contains", dateRange=bounds, other=(10, 20)) is True
    assert _invoke("DateRange.contains", dateRange=bounds, other=(9, 20)) is False


def test_touching_disjoint_and_reversed_ranges_use_empty_set_algebra():
    bounds = (10.0, 20.0)
    touching = (20.0, 30.0)
    disjoint = (25.0, 35.0)
    reversed_range = (18.0, 12.0)
    empty_range = (12.0, 12.0)

    assert _invoke("DateRange.isEmpty", dateRange=empty_range) is True
    assert _invoke("DateRange.isEmpty", dateRange=reversed_range) is True
    assert _invoke("DateRange.intersects", dateRange=bounds, other=touching) is False
    assert _invoke("DateRange.intersects", dateRange=bounds, other=disjoint) is False
    assert _invoke("DateRange.intersects", dateRange=bounds, other=reversed_range) is False
    assert _invoke("DateRange.intersection", dateRange=bounds, other=touching) == (20.0, 20.0)
    assert _invoke("DateRange.intersection", dateRange=bounds, other=disjoint) == (25.0, 25.0)
    assert _invoke("DateRange.intersection", dateRange=bounds, other=reversed_range) == (18.0, 18.0)
    assert _invoke("DateRange.contains", dateRange=bounds, other=empty_range) is True
    assert _invoke("DateRange.union", dateRange=bounds, other=empty_range) == bounds
    assert _invoke("DateRange.union", dateRange=bounds, other=disjoint) == (10.0, 35.0)


def test_intersection_and_union_retain_only_real_finite_endpoints():
    left, right = (0.0, 10.0), (4.0, 14.0)
    assert _invoke("DateRange.intersects", dateRange=left, other=right) is True
    assert _invoke("DateRange.intersection", dateRange=left, other=right) == (4.0, 10.0)
    assert _invoke("DateRange.union", dateRange=left, other=right) == (0.0, 14.0)

    # Existing tuple consumers see the same input unchanged; no endpoint is
    # replaced by a sentinel or a guessed extreme timestamp.
    assert left == (0.0, 10.0)
    assert right == (4.0, 14.0)


def test_date_operands_are_points_for_membership_only():
    bounds = (10.0, 20.0)
    assert _invoke("DateRange.contains", dateRange=bounds, other=19) is True
    assert _invoke("DateRange.contains", dateRange=bounds, other=20) is False
    for operation in (
        "DateRange.intersection", "DateRange.intersects", "DateRange.union",
    ):
        with pytest.raises(UnsupportedEEError, match="other must be a finite DateRange"):
            _invoke(operation, dateRange=bounds, other=19)
    with pytest.raises(UnsupportedEEError, match="contains other must be"):
        _invoke("DateRange.contains", dateRange=bounds, other=2**53 + 1)
    with pytest.raises(UnsupportedEEError, match="other must be a finite DateRange"):
        _invoke("DateRange.union", dateRange=bounds, other=2**53)


def test_unbounded_is_a_typed_universal_range_and_endpoints_fail_closed():
    whole = _invoke("DateRange.unbounded")
    assert whole is UNBOUNDED_DATE_RANGE
    assert isinstance(whole, UnboundedDateRange)
    assert is_date_range(whole)
    assert _invoke("DateRange.isUnbounded", dateRange=whole) is True
    assert _invoke("DateRange.isEmpty", dateRange=whole) is False
    finite = (100.0, 200.0)
    assert _invoke("DateRange.contains", dateRange=whole, other=finite) is True
    assert _invoke("DateRange.contains", dateRange=whole, other=100_000) is True
    assert _invoke("DateRange.intersects", dateRange=whole, other=finite) is True
    assert _invoke("DateRange.intersection", dateRange=whole, other=finite) is finite
    assert _invoke("DateRange.union", dateRange=finite, other=whole) is whole
    assert _invoke("DateRange.contains", dateRange=finite, other=whole) is False

    for operation in ("DateRange.start", "DateRange.end"):
        with pytest.raises(UnsupportedEEError, match="unbounded range is unsupported"):
            _invoke(operation, dateRange=whole)


def test_range_values_are_not_boolean_conditions_and_unbounded_filters_reject():
    for value in ((0.0, 1.0), UNBOUNDED_DATE_RANGE):
        with pytest.raises(UnsupportedEEError, match="static scalar/list/dictionary"):
            static_truth(value)
    filt = Filter("dateRangeContains", {
        "leftValue": UNBOUNDED_DATE_RANGE,
        "rightField": "system:time_start",
    })
    with pytest.raises(UnsupportedEEError, match="finite DateRange"):
        matches_filter(
            Translator([], {}, None), filt,
            {"properties": {"system:time_start": 10}},
        )


def test_rejects_wrong_options_missing_values_and_invalid_types():
    for args in ({}, {"start": 1, "timeZone": "America/Los_Angeles"},
                 {"start": True}, {"start": "0" * 201}):
        with pytest.raises(UnsupportedEEError):
            _invoke("DateRange", **args)
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        _invoke("DateRange", start=1, extra=2)
    with pytest.raises(UnsupportedEEError, match="requires dateRange"):
        _invoke("DateRange.isEmpty")
    with pytest.raises(UnsupportedEEError, match="requires dateRange and other"):
        _invoke("DateRange.union", dateRange=(0, 1))
    with pytest.raises(UnsupportedEEError, match="finite DateRange"):
        _invoke("DateRange.isEmpty", dateRange=[0, 1])
    for invalid in (True, float("nan"), float("inf"), "2020-01-01", {"start": 0}):
        with pytest.raises(UnsupportedEEError, match="other must be"):
            _invoke("DateRange.contains", dateRange=(0, 1), other=invalid)


def test_shared_budget_is_precharged_and_does_not_overrun():
    translator = Translator([], {}, None)
    translator.steps = 49_999
    assert invoke_date_range(translator, "DateRange.isEmpty", {
        "dateRange": (0.0, 1.0),
    }) is False
    assert translator.steps == 50_000

    translator.steps = 50_000
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        invoke_date_range(translator, "DateRange.isEmpty", {
            "dateRange": (0.0, 1.0),
        })
    assert translator.steps == 50_000


def test_pinned_sdk_serializes_methods_into_public_compiler(ee):
    start = ee.DateRange(10, 20)
    touching = ee.DateRange(20, 30)
    whole = ee.DateRange.unbounded()
    expressions = {
        "start": start.start(),
        "end": start.end(),
        "contains_start": start.contains(10),
        "contains_end": start.contains(20),
        "contains_date": start.contains(ee.Date(10)),
        "intersection_start": start.intersection(ee.DateRange(15, 25)).start(),
        "numeric_intersection_start": start.intersection(15).start(),
        "date_intersection_start": start.intersection(ee.Date(15)).start(),
        "numeric_union_end": start.union(20).end(),
        "date_union_end": start.union(ee.Date(20)).end(),
        "numeric_intersects_touching": start.intersects(20),
        "date_intersects_touching": start.intersects(ee.Date(20)),
        "touching_intersection_empty": start.intersection(touching).isEmpty(),
        "touching_intersects": start.intersects(touching),
        "empty": ee.DateRange(7, 7).isEmpty(),
        "unbounded": whole.isUnbounded(),
        "union_end": start.union(ee.DateRange(15, 25)).end(),
        "unbounded_union": start.union(whole).isUnbounded(),
    }
    encoded = {
        key: ee.serializer.encode(value, for_cloud_api=False)
        for key, value in expressions.items()
    }
    result = {key: compile_expression(value, [], {})["value"]
              for key, value in encoded.items()}
    assert result == {
        "start": 10.0,
        "end": 20.0,
        "contains_start": True,
        "contains_end": False,
        "contains_date": True,
        "intersection_start": 15.0,
        "numeric_intersection_start": 15.0,
        "date_intersection_start": 15.0,
        "numeric_union_end": 21.0,
        "date_union_end": 21.0,
        "numeric_intersects_touching": False,
        "date_intersects_touching": False,
        "touching_intersection_empty": True,
        "touching_intersects": False,
        "empty": True,
        "unbounded": True,
        "union_end": 25.0,
        "unbounded_union": True,
    }

    with pytest.raises(UnsupportedEEError, match="unbounded range is unsupported"):
        compile_expression(
            ee.serializer.encode(whole.start(), for_cloud_api=False), [], {},
        )
    with pytest.raises(UnsupportedEEError, match="Unbounded DateRange output"):
        compile_expression(ee.serializer.encode(whole, for_cloud_api=False), [], {})


def test_pinned_algorithm_signatures_match_sdk_methods(ee):
    definitions = json.loads((ROOT / "vendor/earthengine-js/algorithms.json").read_text())["algorithms"]
    expected = {"DateRange", *DATE_RANGE_METHODS}
    pinned = {entry["name"]: entry for entry in definitions}
    assert {"algorithms/" + name for name in expected} <= pinned.keys()
    for name in expected:
        signature = ee.ApiFunction.lookup(name).getSignature()
        assert signature["name"] in {name, "algorithms/" + name}
        definition = pinned["algorithms/" + name]
        assert signature["returns"] == definition["returnType"]
        assert [arg["name"] for arg in signature["args"]] == [
            arg["argumentName"] for arg in definition.get("arguments", [])
        ]
        assert [arg["type"] for arg in signature["args"]] == [
            arg["type"] for arg in definition.get("arguments", [])
        ]
