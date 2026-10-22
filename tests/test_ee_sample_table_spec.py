"""Canonical sampled-feature filter and limit operation wire tests."""
from __future__ import annotations

import copy
import json

import pytest

from gee.compat.earthengine.ir import Filter
from gee.sample_table_spec import (
    MAX_DEPTH,
    MAX_OPERATION_BYTES,
    decode_sample_operation,
    decode_sample_predicate,
    prepare_sample_filter,
    prepare_sample_limit,
)
from gee.sampling_spec import encode_spec


def _filter(name, arguments):
    return Filter(name, arguments)


def _wire(name, arguments):
    return {"name": name, "arguments": arguments}


@pytest.mark.parametrize("filt", [
    _filter("and", {"filters": [
        _filter("equals", {"leftField": "process_id", "rightValue": "local_ee_map"}),
        _filter("notNull", {"properties": ["from_node"]}),
    ]}),
    _filter("or", {"filters": [
        _filter("lessThan", {"leftField": "band", "rightValue": 4}),
        _filter("greaterThan", {"leftValue": 7, "rightField": "class"}),
    ]}),
    _filter("not", {"filter": _filter("stringContains", {
        "leftField": "process_graph", "rightValue": "node_1",
    })}),
    _filter("notNull", {"properties": []}),
    _filter("equals", {"leftValue": False, "rightField": "flag"}),
    _filter("lessThan", {"leftField": "elevation", "rightValue": 10.5}),
    _filter("greaterThan", {"leftValue": -2, "rightField": "offset"}),
    _filter("stringContains", {"leftField": "name", "rightValue": "猫"}),
    _filter("inList", {"leftField": "label", "rightValue": ["a", 2, False]}),
    _filter("listContains", {"leftValue": [1, "x"], "rightField": "tags"}),
    _filter("maxDifference", {
        "difference": 0.25, "leftField": "x", "rightValue": 2.0,
    }),
])
def test_supported_sample_filters_round_trip_as_canonical_data(filt):
    text = prepare_sample_filter(filt)
    operation = decode_sample_operation(text)

    assert text == encode_spec(json.loads(text))
    assert operation == json.loads(text)
    assert operation["version"] == 1
    assert operation["operation"] == "filter"
    assert decode_sample_predicate(operation["predicate"]) == filt


def test_filter_preparation_does_not_mutate_nested_filter_ir():
    filt = _filter("and", {"filters": [
        _filter("notNull", {"properties": ["a", "b"]}),
        _filter("inList", {"leftField": "kind", "rightValue": ["x", 1]}),
    ]})
    before = copy.deepcopy(filt)

    prepare_sample_filter(filt)

    assert filt == before


def test_graph_protocol_looking_names_remain_filter_data_in_the_json_string():
    filt = _filter("equals", {
        "leftField": "process_id",
        "rightValue": "local_ee_sample_table_op",
    })
    text = prepare_sample_filter(filt)
    parsed = json.loads(text)

    assert parsed == {
        "operation": "filter",
        "predicate": _wire("equals", {
            "leftField": "process_id",
            "rightValue": "local_ee_sample_table_op",
        }),
        "version": 1,
    }
    assert "from_node" not in parsed
    assert "process_graph" not in parsed


@pytest.mark.parametrize("filt", [
    _filter("dateRangeContains", {"leftField": "date", "rightValue": "2020"}),
    _filter("calendarRange", {"start": 1, "end": 12, "field": "month"}),
    _filter("intersects", {"leftField": "geometry", "rightValue": {"type": "Point"}}),
    _filter("expression", {"expression": "foo == 1"}),
    _filter("mystery", {}),
])
def test_unsupported_dynamic_calendar_geometry_and_unknown_filters_reject(filt):
    with pytest.raises(ValueError, match="Unsupported"):
        prepare_sample_filter(filt)


@pytest.mark.parametrize("arguments", [
    {"leftField": "x"},
    {"rightValue": 1},
    {"leftField": "x", "leftValue": 1, "rightValue": 2},
    {"leftValue": 1, "rightField": "x", "extra": 1},
    {"leftField": "x", "rightField": "y", "leftValue": 1},
])
def test_binary_filters_require_exactly_one_operand_per_side(arguments):
    with pytest.raises(ValueError):
        prepare_sample_filter(_filter("equals", arguments))


@pytest.mark.parametrize("field", ["", "a.b", "x" * 257, None, 7])
def test_sample_filters_require_bounded_flat_string_fields(field):
    with pytest.raises(ValueError):
        prepare_sample_filter(_filter("equals", {"leftField": field, "rightValue": 1}))


def test_sample_filter_field_and_scalar_boundaries():
    valid = _filter("equals", {
        "leftField": "x" * 256, "rightValue": "v" * 4096,
    })
    assert decode_sample_operation(prepare_sample_filter(valid))["operation"] == "filter"

    with pytest.raises(ValueError):
        prepare_sample_filter(_filter("equals", {
            "leftField": "x", "rightValue": "v" * 4097,
        }))


@pytest.mark.parametrize("literal", [
    None, {}, {"nested": 1}, [1], float("nan"), float("inf"), float("-inf"),
    2**53 + 1, -(2**53 + 1),
])
def test_scalar_operands_reject_null_objects_arrays_and_out_of_domain_numbers(literal):
    with pytest.raises(ValueError):
        prepare_sample_filter(_filter("equals", {"leftValue": literal, "rightValue": 2}))


def test_sample_filter_accepts_exact_numeric_endpoints_boolean_and_finite_float():
    for literal in (-2**53, 2**53, True, False, -1.25e300):
        text = prepare_sample_filter(_filter("equals", {
            "leftValue": literal, "rightValue": "ok",
        }))
        assert decode_sample_operation(text)["predicate"]["arguments"]["leftValue"] == literal


def test_in_list_and_list_contains_allow_only_bounded_scalar_arrays():
    accepted = list(range(64))
    for name, side in (("inList", "rightValue"), ("listContains", "leftValue")):
        field_side = "leftField" if name == "inList" else "rightField"
        filt = _filter(name, {field_side: "values", side: accepted})
        assert decode_sample_operation(prepare_sample_filter(filt))["operation"] == "filter"
        with pytest.raises(ValueError, match="at most64"):
            prepare_sample_filter(_filter(name, {field_side: "values", side: accepted + [64]}))
        for invalid in ([None], [[1]], [{"x": 1}]):
            with pytest.raises(ValueError):
                prepare_sample_filter(_filter(name, {field_side: "values", side: invalid}))


def test_boolean_predicate_children_and_not_null_properties_are_bounded():
    children = [_filter("notNull", {"properties": []}) for _ in range(63)]
    prepare_sample_filter(_filter("and", {"filters": children}))  # root + 63 nodes = 64
    with pytest.raises(ValueError, match="64 nodes"):
        prepare_sample_filter(_filter("and", {"filters": children + [children[0]]}))
    with pytest.raises(ValueError, match="0..64"):
        prepare_sample_filter(_filter("or", {
            "filters": [_filter("notNull", {"properties": []}) for _ in range(65)],
        }))

    properties = [f"p{index}" for index in range(64)]
    prepare_sample_filter(_filter("notNull", {"properties": properties}))
    with pytest.raises(ValueError, match="0..64"):
        prepare_sample_filter(_filter("notNull", {"properties": properties + ["overflow"]}))


def test_predicate_nesting_depth_accepts_16_and_rejects_17():
    nested = _filter("notNull", {"properties": []})
    for _ in range(MAX_DEPTH):
        nested = _filter("not", {"filter": nested})
    prepare_sample_filter(nested)

    nested = _filter("not", {"filter": nested})
    with pytest.raises(ValueError, match="depth16"):
        prepare_sample_filter(nested)


def test_max_difference_accepts_nonnegative_finite_numeric_threshold():
    for difference in (0, 1, 0.0001, 2**53):
        prepare_sample_filter(_filter("maxDifference", {
            "difference": difference, "leftValue": 1, "rightValue": 2,
        }))
    for difference in (-1, True, None, float("nan"), float("inf"), float("-inf"), "1", 2**53 + 1):
        with pytest.raises(ValueError):
            prepare_sample_filter(_filter("maxDifference", {
                "difference": difference, "leftValue": 1, "rightValue": 2,
            }))


@pytest.mark.parametrize("count", [None, 0, 1, 1000])
def test_sample_limit_accepts_none_and_integer_boundaries(count):
    text = prepare_sample_limit(count)
    assert text == encode_spec({"version": 1, "operation": "limit", "count": count})
    assert decode_sample_operation(text) == json.loads(text)


@pytest.mark.parametrize("count", [True, False, -1, 1001, 1.0, "1", [], {}])
def test_sample_limit_rejects_bool_non_integer_and_out_of_range_values(count):
    with pytest.raises(ValueError):
        prepare_sample_limit(count)


def test_sample_operation_decoder_rejects_unknown_fields_versions_and_duplicate_keys():
    valid = prepare_sample_limit(1)
    with pytest.raises(ValueError, match="version"):
        decode_sample_operation(valid.replace('"version":1', '"version":true'))
    with pytest.raises(ValueError, match="Unsupported"):
        decode_sample_operation(encode_spec({"version": 2, "operation": "limit", "count": 1}))
    with pytest.raises(ValueError, match="Unsupported"):
        decode_sample_operation(encode_spec({"version": 1, "operation": "limit", "count": 1, "key": "x"}))
    with pytest.raises(ValueError, match="Duplicate specification key"):
        decode_sample_operation('{"count":1,"operation":"limit","version":1,"count":2}')
    with pytest.raises(ValueError, match="canonical"):
        decode_sample_operation(valid + " ")
    with pytest.raises(ValueError, match="finite JSON"):
        decode_sample_operation(valid.replace('"count":1', '"count":NaN'))


def test_sample_operation_utf8_byte_limit_applies_to_canonical_unicode_json():
    children = [
        _filter("equals", {"leftField": f"name{index}", "rightValue": "猫" * 1500})
        for index in range(4)
    ]
    filt = _filter("and", {"filters": children})
    predicate = _wire("and", {"filters": [
        _wire("equals", {"leftField": f"name{index}", "rightValue": "猫" * 1500})
        for index in range(4)
    ]})
    canonical = encode_spec({"version": 1, "operation": "filter", "predicate": predicate})
    # The UTF-8 size, not character count, crosses the 16 KiB protocol bound.
    assert len(canonical) < MAX_OPERATION_BYTES
    assert len(canonical.encode("utf-8")) > MAX_OPERATION_BYTES
    with pytest.raises(ValueError, match="<=16384 bytes"):
        prepare_sample_filter(filt)


def test_sample_operation_decoder_rejects_oversized_non_json_text_before_parsing():
    with pytest.raises(ValueError, match="16384 bytes"):
        decode_sample_operation(" " * (MAX_OPERATION_BYTES + 1))
