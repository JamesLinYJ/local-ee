"""Official Python SDK construction and bounded local aggregate semantics."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_core import StaticArray
from gee.compat.earthengine.aggregate_statistics import (
    AGGREGATE_STATISTICS_NAMES,
    invoke_aggregate_statistics,
)
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, ImageSequence, Pixel, Source, Collection
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2",
        "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def compile_sdk(ee, value):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, [], {})["value"]


def evaluate_sdk_with_steps(ee, value):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    translator = Translator([], {}, None)
    return translator.evaluate(expression), translator.steps


def compile_sdk_with_synthetic_catalog(ee, value):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    metadata, items, _ = synthetic_inputs()
    return compile_expression(expression, [metadata], items)["value"]


def _fc(rows):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": None, "properties": row} for row in rows
    ]}


def _invoke(name, rows, *, steps=0):
    translator = Translator([], {}, None)
    translator.steps = steps
    result = invoke_aggregate_statistics(
        translator,
        "AggregateFeatureCollection." + name,
        {"collection": _fc(rows), "property": "value"},
    )
    return result, translator.steps


def test_official_sdk_serializes_and_compiles_each_scalar_aggregate(ee):
    collection = ee.FeatureCollection([
        ee.Feature(None, {"value": 4}),
        ee.Feature(None, {"value": 0}),
        ee.Feature(None, {"value": 2}),
        ee.Feature(None, {"other": "missing"}),
        ee.Feature(None, {"value": None}),
    ])
    cases = [
        ("aggregate_first", 4),
        ("aggregate_count", 3),
        ("aggregate_count_distinct", 3),
        ("aggregate_min", 0),
        ("aggregate_max", 4),
        ("aggregate_mean", 2.0),
        ("aggregate_product", 0.0),
        ("aggregate_sum", 6.0),
        ("aggregate_sample_sd", 2.0),
        ("aggregate_sample_var", 4.0),
        ("aggregate_total_sd", math.sqrt(8 / 3)),
        ("aggregate_total_var", 8 / 3),
        ("aggregate_histogram", {"0": 1, "2": 1, "4": 1}),
    ]
    assert len(AGGREGATE_STATISTICS_NAMES) == len(cases) + 1  # includes aggregate_stats
    for method, expected in cases:
        assert compile_sdk(ee, getattr(collection, method)("value")) == expected
    assert compile_sdk(ee, collection.aggregate_stats("value")) == {
        "max": 4,
        "mean": 2.0,
        "min": 0,
        "sample_sd": 2.0,
        "sample_var": 4.0,
        "sum": 6.0,
        "sum_sq": 20.0,
        "total_count": 5,
        "total_sd": math.sqrt(8 / 3),
        "total_var": 8 / 3,
        "valid_count": 3,
        "weight_sum": 3,
        "weighted_sum": 6.0,
    }


def test_official_sdk_1000_simple_features_fit_shared_budget(ee):
    collection = ee.FeatureCollection([
        ee.Feature(None, {"v": 1}) for _ in range(1000)
    ])
    count, count_steps = evaluate_sdk_with_steps(ee, collection.aggregate_count("v"))
    total, sum_steps = evaluate_sdk_with_steps(ee, collection.aggregate_sum("v"))
    assert count == 1000
    assert total == 1000.0
    assert count_steps < 50_000
    assert sum_steps < 50_000


def test_first_keeps_collection_order_and_count_ignores_null_and_missing(ee):
    collection = ee.FeatureCollection([
        ee.Feature(None, {"value": None}),
        ee.Feature(None, {"other": 7}),
        ee.Feature(None, {"value": "later"}),
    ])
    assert compile_sdk(ee, collection.aggregate_first("value")) is None
    assert compile_sdk(ee, collection.aggregate_count("value")) == 1
    assert compile_sdk(ee, collection.aggregate_count_distinct("value")) == 1
    assert compile_sdk(ee, collection.aggregate_histogram("value")) == {"later": 1}


def test_empty_and_singleton_numeric_contract_is_explicit(ee):
    empty = ee.FeatureCollection([])
    assert compile_sdk(ee, empty.aggregate_first("value")) is None
    assert compile_sdk(ee, empty.aggregate_count("value")) == 0
    assert compile_sdk(ee, empty.aggregate_count_distinct("value")) == 0
    assert compile_sdk(ee, empty.aggregate_min("value")) is None
    assert compile_sdk(ee, empty.aggregate_max("value")) is None
    assert compile_sdk(ee, empty.aggregate_mean("value")) is None
    assert compile_sdk(ee, empty.aggregate_product("value")) == 1.0
    assert compile_sdk(ee, empty.aggregate_sum("value")) == 0.0
    assert compile_sdk(ee, empty.aggregate_sample_sd("value")) is None
    assert compile_sdk(ee, empty.aggregate_sample_var("value")) is None
    assert compile_sdk(ee, empty.aggregate_total_sd("value")) is None
    assert compile_sdk(ee, empty.aggregate_total_var("value")) is None
    assert compile_sdk(ee, empty.aggregate_histogram("value")) == {}

    singleton = ee.FeatureCollection([ee.Feature(None, {"value": 7})])
    assert compile_sdk(ee, singleton.aggregate_sample_sd("value")) is None
    assert compile_sdk(ee, singleton.aggregate_sample_var("value")) is None
    assert compile_sdk(ee, singleton.aggregate_total_sd("value")) == 0.0
    assert compile_sdk(ee, singleton.aggregate_total_var("value")) == 0.0


def test_shifted_variance_retains_small_differences_at_large_offsets(ee):
    base = 1_000_000_000_000
    collection = ee.FeatureCollection([
        ee.Feature(None, {"value": base}),
        ee.Feature(None, {"value": base + 1}),
        ee.Feature(None, {"value": base + 2}),
    ])
    assert compile_sdk(ee, collection.aggregate_mean("value")) == base + 1.0
    assert compile_sdk(ee, collection.aggregate_total_var("value")) == pytest.approx(2 / 3)
    assert compile_sdk(ee, collection.aggregate_sample_var("value")) == pytest.approx(1.0)
    assert compile_sdk(ee, collection.aggregate_sample_sd("value")) == pytest.approx(1.0)


def test_mean_and_scaled_variance_do_not_require_unrelated_finite_squares(ee):
    repeated_huge = ee.FeatureCollection([
        ee.Feature(None, {"value": 1e200}),
        ee.Feature(None, {"value": 1e200}),
    ])
    assert compile_sdk(ee, repeated_huge.aggregate_mean("value")) == 1e200
    assert compile_sdk(ee, repeated_huge.aggregate_total_var("value")) == 0.0

    opposite = ee.FeatureCollection([
        ee.Feature(None, {"value": 1e154}),
        ee.Feature(None, {"value": -1e154}),
    ])
    assert compile_sdk(ee, opposite.aggregate_mean("value")) == 0.0
    assert compile_sdk(ee, opposite.aggregate_total_var("value")) == pytest.approx(1e308)
    assert compile_sdk(ee, opposite.aggregate_sample_sd("value")) == pytest.approx(
        math.sqrt(2) * 1e154,
    )
    with pytest.raises(UnsupportedEEError, match="sum_sq"):
        compile_sdk(ee, repeated_huge.aggregate_stats("value"))


def test_text_ordering_and_mixed_numeric_string_errors_are_explicit(ee):
    strings = ee.FeatureCollection([
        ee.Feature(None, {"value": "2"}),
        ee.Feature(None, {"value": "10"}),
        ee.Feature(None, {"value": "a"}),
    ])
    assert compile_sdk(ee, strings.aggregate_min("value")) == "10"
    assert compile_sdk(ee, strings.aggregate_max("value")) == "a"
    with pytest.raises(UnsupportedEEError, match="homogeneous numeric"):
        compile_sdk(ee, strings.aggregate_sum("value"))

    mixed = ee.FeatureCollection([
        ee.Feature(None, {"value": 1}), ee.Feature(None, {"value": "1"}),
    ])
    with pytest.raises(UnsupportedEEError, match="numeric or all strings"):
        compile_sdk(ee, mixed.aggregate_min("value"))
    with pytest.raises(UnsupportedEEError, match="homogeneous numeric"):
        compile_sdk(ee, mixed.aggregate_mean("value"))


def test_distinct_and_histogram_preserve_types_and_reject_string_key_collisions(ee):
    values = ee.FeatureCollection([
        ee.Feature(None, {"value": 1}),
        ee.Feature(None, {"value": 1.0}),
        ee.Feature(None, {"value": True}),
        ee.Feature(None, {"value": "true"}),
    ])
    assert compile_sdk(ee, values.aggregate_count_distinct("value")) == 3
    with pytest.raises(UnsupportedEEError, match="collide after conversion"):
        compile_sdk(ee, values.aggregate_histogram("value"))

    collision = ee.FeatureCollection([
        ee.Feature(None, {"value": 1}), ee.Feature(None, {"value": "1"}),
    ])
    with pytest.raises(UnsupportedEEError, match="collide after conversion"):
        compile_sdk(ee, collision.aggregate_histogram("value"))


def test_nested_json_properties_are_countable_but_not_scalar_statistic_inputs(ee):
    collection = ee.FeatureCollection([
        ee.Feature(None, {"value": {"x": 1}}),
        ee.Feature(None, {"value": [1, 2]}),
    ])
    assert compile_sdk(ee, collection.aggregate_count("value")) == 2
    with pytest.raises(UnsupportedEEError, match="scalar"):
        compile_sdk(ee, collection.aggregate_first("value"))
    with pytest.raises(UnsupportedEEError, match="scalar string"):
        compile_sdk(ee, collection.aggregate_histogram("value"))

    with pytest.raises(UnsupportedEEError, match="bounded JSON"):
        _invoke("count", [{"value": Image([], {})}])
    with pytest.raises(UnsupportedEEError, match="bounded JSON"):
        _invoke("count", [{"value": StaticArray(np.asarray([1.0]))}])
    with pytest.raises(UnsupportedEEError, match="object keys must be strings"):
        _invoke("count", [{"value": {1: "not JSON"}}])


def test_actual_image_collection_metadata_is_supported_without_pixel_fabrication(ee):
    collection = ee.ImageCollection("sentinel-2-l2a")
    assert compile_sdk_with_synthetic_catalog(ee, collection.aggregate_count("system:index")) == 3
    assert compile_sdk_with_synthetic_catalog(ee, collection.aggregate_first("system:index")) == "scene-a"
    assert compile_sdk_with_synthetic_catalog(ee, collection.aggregate_count_distinct("system:index")) == 3
    assert compile_sdk_with_synthetic_catalog(ee, collection.aggregate_min("system:index")) == "scene-a"
    assert compile_sdk_with_synthetic_catalog(ee, collection.aggregate_mean("cloud")) == pytest.approx(35 / 3)
    assert compile_sdk_with_synthetic_catalog(ee, collection.aggregate_sum("cloud")) == 35.0
    assert compile_sdk_with_synthetic_catalog(ee, collection.aggregate_histogram("system:index")) == {
        "scene-a": 1, "scene-b": 1, "scene-c": 1,
    }


def test_inline_result_ownership_budget_row_cap_and_exact_integer_contract():
    collection = _fc([{"value": "red"}, {"value": "blue"}, {"value": "red"}])
    translator = Translator([], {}, None)
    result = invoke_aggregate_statistics(
        translator, "AggregateFeatureCollection.histogram",
        {"collection": collection, "property": "value"},
    )
    result["red"] = 100
    assert collection["features"][0]["properties"]["value"] == "red"

    with pytest.raises(UnsupportedEEError, match="work budget"):
        _invoke("count", [{"value": 1}], steps=49_999)
    with pytest.raises(UnsupportedEEError, match="1000 inline features"):
        _invoke("count", [{"value": 1}] * 1_001)
    with pytest.raises(UnsupportedEEError, match=r"exact ±2\^53"):
        _invoke("mean", [{"value": 2**53 + 1}])


def test_statistics_require_exact_arguments_and_reject_dynamic_sources():
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_aggregate_statistics(
            translator,
            "AggregateFeatureCollection.count",
            {"collection": _fc([]), "property": "value", "extra": True},
        )
    with pytest.raises(UnsupportedEEError, match="finite declared image metadata only"):
        invoke_aggregate_statistics(
            translator,
            "AggregateFeatureCollection.count",
            {"collection": object(), "property": "value"},
        )

    cyclic = {"type": "FeatureCollection", "features": []}
    feature = {"type": "Feature", "geometry": None, "properties": {"value": cyclic}}
    cyclic["features"].append(feature)
    with pytest.raises(UnsupportedEEError, match="cycle"):
        invoke_aggregate_statistics(
            Translator([], {}, None),
            "AggregateFeatureCollection.count",
            {"collection": cyclic, "property": "value"},
        )


def test_selected_strings_and_image_metadata_ids_are_precharged_before_scan_or_lookup():
    with pytest.raises(UnsupportedEEError, match="work budget"):
        _invoke("count", [{"value": "x" * 50_001}])

    long_id = "i" * 50_001
    collection = Collection(
        Source("local", (long_id,), ()),
        Image([], {}),
    )
    translator = Translator([], {
        "local": [{"id": long_id, "properties": {"value": 1}}],
    }, None)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_aggregate_statistics(
            translator,
            "AggregateFeatureCollection.count",
            {"collection": collection, "property": "value"},
        )


def test_hand_built_collection_metadata_aggregation_reads_declared_properties_only():
    items = [{"id": "a", "properties": {"name": "first", "n": 3}},
             {"id": "b", "properties": {"name": "second", "n": 9}}]
    collection = Collection(
        Source("local", ("a", "b"), ("red",)),
        Image([("red", Pixel("constant", (1,)))], {}, inherit_props=True),
    )
    translator = Translator([], {"local": items}, None)
    assert invoke_aggregate_statistics(
        translator,
        "AggregateFeatureCollection.mean",
        {"collection": collection, "property": "n"},
    ) == 6.0
    assert invoke_aggregate_statistics(
        Translator([], {"local": items}, None),
        "AggregateFeatureCollection.first",
        {"collection": collection, "property": "name"},
    ) == "first"


def test_finite_image_sequence_uses_only_actual_image_properties():
    sequence = ImageSequence([
        Image([("red", Pixel("constant", (1,)))], {"label": "a", "value": 2}),
        Image([("red", Pixel("constant", (1,)))], {"label": "b", "value": 8}),
    ])
    translator = Translator([], {}, None)
    assert invoke_aggregate_statistics(
        translator,
        "AggregateFeatureCollection.mean",
        {"collection": sequence, "property": "value"},
    ) == 5.0
    assert invoke_aggregate_statistics(
        Translator([], {}, None),
        "AggregateFeatureCollection.first",
        {"collection": sequence, "property": "label"},
    ) == "a"
