"""Wave56 filter aliases, finite metadata predicates and table execution."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import ee_process_adapters as adapters
from engine.ee_json_result import RuntimeFeatureTable, attach_classification_origin
from engine.ee_sampling_result import SampledFeatureTable
from gee.compat.earthengine.feature_filters import (
    _UNKNOWN,
    matches_feature_filter,
    validate_filter_structure,
)
from gee.compat.earthengine.feature_ops import invoke_feature
from gee.compat.earthengine.filtering import (
    FILTER_DEFERRED_ARGUMENTS,
    FILTER_PREPARATION_ARGUMENTS,
    FilteringOperations,
    invoke_filter,
    matches_filter,
)
from gee.compat.earthengine.ir import Filter
from gee.compat.earthengine.geometry_values import decode_geometry_bounded
from gee.sample_table_spec import (
    decode_sample_operation,
    prepare_sample_filter,
)
from gee.sampling_spec import decode_sampling_spec, sampling_columns
from gee.rf_validation_spec import prepare_classify_spec
from ee_sampling_bridge_helpers import _spec


class _Translator(FilteringOperations):
    def __init__(self):
        self.steps = 0

    @staticmethod
    def allowed(arguments, names):
        unknown = set(arguments) - names
        if unknown:
            raise ValueError(f"Unsupported filter arguments: {sorted(unknown)}")


def _filter(translator, name, arguments=None):
    return invoke_filter(translator, "Filter." + name, arguments or {})


@pytest.mark.parametrize(("name", "expected"), [
    ("eq", Filter("equals", {"leftField": "v", "rightValue": 3})),
    ("gt", Filter("greaterThan", {"leftField": "v", "rightValue": 3})),
    ("lt", Filter("lessThan", {"leftField": "v", "rightValue": 3})),
    ("gte", Filter("not", {"filter": Filter(
        "lessThan", {"leftField": "v", "rightValue": 3})})),
    ("greaterThanOrEquals", Filter("not", {"filter": Filter(
        "lessThan", {"leftField": "v", "rightValue": 3})})),
    ("lte", Filter("not", {"filter": Filter(
        "greaterThan", {"leftField": "v", "rightValue": 3})})),
    ("lessThanOrEquals", Filter("not", {"filter": Filter(
        "greaterThan", {"leftField": "v", "rightValue": 3})})),
    ("neq", Filter("not", {"filter": Filter(
        "equals", {"leftField": "v", "rightValue": 3})})),
    ("notEquals", Filter("not", {"filter": Filter(
        "equals", {"leftField": "v", "rightValue": 3})})),
])
def test_exact_aliases_lower_to_existing_filter_ir(name, expected):
    arguments = {"leftField": "v", "rightValue": 3}
    assert _filter(_Translator(), name, arguments) == expected


def test_range_day_and_constant_filters_lower_exactly():
    translator = _Translator()
    ranged = _filter(translator, "rangeContains", {
        "field": "cloud_cover", "minValue": 10, "maxValue": 20,
    })
    assert ranged.name == "and"
    assert matches_filter(translator, ranged, {"properties": {"cloud_cover": 10}})
    assert matches_filter(translator, ranged, {"properties": {"cloud_cover": 20}})
    assert not matches_filter(translator, ranged, {"properties": {"cloud_cover": 21}})
    assert _filter(translator, "dayOfYear", {"start": 60, "end": 60}) == Filter(
        "calendarRange", {"start": 60, "end": 60, "field": "day_of_year"},
    )
    assert matches_filter(translator, _filter(translator, "always"), {"properties": {}})
    assert not matches_filter(translator, _filter(translator, "never"), {"properties": {}})


def test_new_signature_contracts_match_pinned_algorithm_inventory():
    optional_binary = frozenset({"leftField", "leftValue", "rightField", "rightValue"})
    for name in (
        "eq", "gt", "gte", "lt", "lte", "neq", "notEquals",
        "greaterThanOrEquals", "lessThanOrEquals", "stringStartsWith",
        "stringEndsWith",
    ):
        assert FILTER_PREPARATION_ARGUMENTS["Filter." + name] == (frozenset(), optional_binary)
    assert FILTER_PREPARATION_ARGUMENTS["Filter.rangeContains"] == (
        frozenset({"field", "minValue", "maxValue"}), frozenset(),
    )
    assert FILTER_PREPARATION_ARGUMENTS["Filter.dayOfYear"] == (
        frozenset({"start", "end"}), frozenset(),
    )
    for name in ("always", "never", "hasGeometry"):
        assert FILTER_PREPARATION_ARGUMENTS["Filter." + name] == (frozenset(), frozenset())
    assert FILTER_DEFERRED_ARGUMENTS["Filter.hasType"] == (frozenset(), optional_binary)

    algorithms = json.loads(Path(__file__).resolve().parents[1].joinpath(
        "vendor/earthengine-js/algorithms.json",
    ).read_text())["algorithms"]
    pinned = {item["name"]: item for item in algorithms}
    contracts = {**FILTER_PREPARATION_ARGUMENTS, **FILTER_DEFERRED_ARGUMENTS}
    for name, (required, optional) in contracts.items():
        descriptor = pinned["algorithms/" + name]
        arguments = descriptor.get("arguments", [])
        pinned_required = frozenset(
            arg["argumentName"] for arg in arguments if not arg.get("optional", False)
        )
        pinned_optional = frozenset(
            arg["argumentName"] for arg in arguments if arg.get("optional", False)
        )
        assert (required, optional) == (pinned_required, pinned_optional)
        types = {arg["argumentName"]: arg["type"] for arg in arguments}
        if name.endswith("rangeContains"):
            assert types == {"field": "String", "minValue": "Object", "maxValue": "Object"}
        elif name.endswith("dayOfYear"):
            assert types == {"start": "Integer", "end": "Integer"}
        elif name.endswith(("always", "never", "hasGeometry")):
            assert types == {}
        else:
            assert types == {
                "leftField": "String", "leftValue": "Object",
                "rightField": "String", "rightValue": "Object",
            }


@pytest.mark.parametrize("name,arguments", [
    ("gte", {"leftField": "v", "rightValue": 1, "unexpected": True}),
    ("gte", {"leftField": "v", "rightValue": True}),
    ("stringContains", {"leftField": "name", "rightValue": 3}),
    ("stringStartsWith", {"leftField": "name", "rightValue": 4}),
    ("stringEndsWith", {"leftField": "name", "rightValue": False}),
    ("rangeContains", {"field": "v", "minValue": 1, "maxValue": "2"}),
    ("dayOfYear", {"start": 2}),
    ("dayOfYear", {"start": 1.0, "end": 2}),
    ("hasGeometry", {"leftField": "x"}),
])
def test_invalid_new_filter_arguments_reject_during_preparation(name, arguments):
    with pytest.raises(ValueError):
        _filter(_Translator(), name, arguments)


def test_finite_catalogue_metadata_runs_string_range_calendar_and_geometry_filters():
    translator = _Translator()
    item = {
        "properties": {
            "system:index": "S2A_20240229T120000",
            "cloud_cover": 20,
            "system:time_start": "2024-02-29T12:00:00Z",
        },
        "geometry": {"type": "Point", "coordinates": [0, 0]},
    }
    assert matches_filter(translator, _filter(translator, "stringStartsWith", {
        "leftField": "system:index", "rightValue": "S2A_",
    }), item)
    assert matches_filter(translator, _filter(translator, "stringEndsWith", {
        "leftField": "system:index", "rightValue": "120000",
    }), item)
    assert matches_filter(translator, _filter(translator, "dayOfYear", {
        "start": 60, "end": 60,
    }), item)
    assert matches_filter(translator, _filter(translator, "hasGeometry"), item)
    assert not matches_filter(translator, _filter(translator, "hasGeometry"), {
        "properties": {}, "geometry": None,
    })


def test_intersects_validates_roi_then_returns_false_for_null_item_geometry():
    translator = _Translator()
    point_roi = {"type": "Point", "coordinates": [0, 0]}
    predicate = _filter(translator, "intersects", {
        "leftField": ".all", "rightValue": point_roi,
    })
    assert matches_filter(translator, predicate, {
        "properties": {}, "geometry": None,
    }) is False
    with pytest.raises(ValueError, match="Unsupported|intersection filtering"):
        _filter(translator, "intersects", {
            "leftField": ".all", "rightValue": point_roi, "unexpected": 1,
        })


def test_intersects_preflight_accepts_owned_geometry_without_flattening_metadata():
    geometry = decode_geometry_bounded(_Translator(), {
        "type": "Polygon", "geodesic": False,
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
    })
    metadata_before = geometry.geometry_metadata.copy()
    predicate = Filter("intersects", {"leftField": ".all", "rightValue": geometry})
    validate_filter_structure(_Translator(), predicate)
    assert matches_filter(_Translator(), predicate, {"properties": {}, "geometry": None}) is False
    assert geometry.geometry_metadata == metadata_before


def test_inline_feature_string_filters_preserve_unknown_and_geometry_semantics():
    translator = _Translator()
    feature = {
        "type": "Feature", "geometry": None,
        "properties": {"name": "plot-17-end", "cloud_cover": 10},
    }
    assert matches_feature_filter(translator, _filter(translator, "stringStartsWith", {
        "leftField": "name", "rightValue": "plot-",
    }), feature) is True
    assert matches_feature_filter(translator, _filter(translator, "stringEndsWith", {
        "leftField": "name", "rightValue": "end",
    }), feature) is True
    missing = Filter("stringStartsWith", {"leftField": "missing", "rightValue": "x"})
    assert matches_feature_filter(translator, missing, feature) is _UNKNOWN
    assert matches_feature_filter(translator, _filter(translator, "hasGeometry"), feature) is False
    intersects = Filter("intersects", {
        "leftField": ".all", "rightValue": {"type": "Point", "coordinates": [0, 0]},
    })
    assert matches_feature_filter(translator, intersects, feature) is False


def test_inline_feature_collection_filter_handles_empty_and_null_geometry_rows():
    translator = _Translator()
    roi = {"type": "Point", "coordinates": [0, 0]}
    predicate = Filter("intersects", {"leftField": ".all", "rightValue": roi})
    collection = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": None, "properties": {"name": "no-footprint"}},
        {"type": "Feature", "geometry": roi, "properties": {"name": "point"}},
    ]}
    result = invoke_feature(translator, "Collection.filter", {
        "collection": collection, "filter": predicate,
    })
    assert [feature["properties"]["name"] for feature in result["features"]] == ["point"]
    empty = invoke_feature(translator, "Collection.filter", {
        "collection": {"type": "FeatureCollection", "features": []},
        "filter": predicate,
    })
    assert empty["features"] == []
    malformed = Filter("intersects", {
        "leftField": ".all", "rightValue": roi, "unexpected": True,
    })
    with pytest.raises(ValueError, match="Unsupported|Filter.intersects"):
        invoke_feature(translator, "Collection.filter", {
            "collection": collection, "filter": malformed,
        })


def test_empty_inline_collection_preflights_invalid_nested_alias_arguments():
    translator = _Translator()
    malformed = Filter("gte", {
        "leftField": "cloud_cover", "rightValue": 5, "unexpected": True,
    })
    filter_with_false_branch = Filter("and", {"filters": [
        Filter("never", {}), malformed,
    ]})
    with pytest.raises(ValueError, match="Unsupported filter arguments"):
        invoke_feature(translator, "Collection.filter", {
            "collection": {"type": "FeatureCollection", "features": []},
            "filter": filter_with_false_branch,
        })


def test_feature_filter_structure_preflight_visits_branches_and_rejects_cycles():
    translator = _Translator()
    nested_bad = Filter("and", {"filters": [
        Filter("never", {}),
        Filter("stringStartsWith", {"leftField": "name", "rightValue": 7}),
    ]})
    with pytest.raises(ValueError, match="literal operands must be strings"):
        validate_filter_structure(translator, nested_bad)

    cycle = Filter("not", {})
    cycle.args["filter"] = cycle
    with pytest.raises(ValueError, match="cycle"):
        validate_filter_structure(_Translator(), cycle)

    with pytest.raises(ValueError, match="calendar field"):
        validate_filter_structure(_Translator(), Filter("calendarRange", {
            "start": 1, "field": [],
        }))
