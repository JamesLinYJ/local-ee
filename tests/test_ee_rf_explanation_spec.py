"""Closed projection and native-wire contracts for Smile RF explanation values."""
from __future__ import annotations

import json

import pytest

from gee.rf_explanation_spec import (
    decode_explanation_spec,
    decode_native_explanation,
    prepare_explanation_spec,
    project_explanation,
    validate_explanation_value,
)


FULL = {
    "importance": {"signal": 1.5, "constant": 0.0},
    "numberOfTrees": 3,
    "outOfBagErrorEstimate": 0.0,
}
SCHEMA = ["signal", "constant"]


def test_specs_are_canonical_and_keep_the_model_schema_order():
    text = prepare_explanation_spec(tuple(SCHEMA), 3)
    assert text == '{"schema":["signal","constant"],"trees":3,"version":1,"view":"explanation"}'
    assert decode_explanation_spec(text) == {
        "version": 1, "schema": SCHEMA, "trees": 3, "view": "explanation",
    }


def test_ordered_value_projections_keep_duplicate_keys():
    spec = decode_explanation_spec(prepare_explanation_spec(
        SCHEMA, 3, view="importance_values", keys=["constant", "signal", "constant"],
    ))
    assert project_explanation(FULL, spec) == [0.0, 1.5, 0.0]
    root_values = decode_explanation_spec(prepare_explanation_spec(
        SCHEMA, 3, view="values", keys=["numberOfTrees", "importance", "numberOfTrees"],
    ))
    values = project_explanation(FULL, root_values)
    assert values == [3, FULL["importance"], 3]
    assert values[1] is not FULL["importance"]


def test_importance_validation_accepts_sorted_json_and_returns_schema_order():
    sorted_wire_value = json.loads(json.dumps(FULL, sort_keys=True))
    spec = decode_explanation_spec(prepare_explanation_spec(SCHEMA, 3))
    owned = validate_explanation_value(sorted_wire_value, spec)
    assert list(sorted_wire_value["importance"]) == ["constant", "signal"]
    assert list(owned["importance"]) == SCHEMA
    assert owned == FULL
    assert owned is not sorted_wire_value
    assert owned["importance"] is not sorted_wire_value["importance"]


@pytest.mark.parametrize("text", [
    '{"schema":["signal"],"trees":3,"version":1,"view":"explanation","view":"importance"}',
    '{"schema":["signal"],"trees":3,"version":1,"view":"explanation","keys":[]}',
    '{"keys":["unknown"],"schema":["signal"],"trees":3,"version":1,"view":"values"}',
])
def test_specs_reject_duplicate_object_keys_and_wrong_projection_shape(text):
    with pytest.raises(ValueError):
        decode_explanation_spec(text)


@pytest.mark.parametrize(("schema", "trees", "view", "keys"), [
    (["signal", "signal"], 3, "explanation", None),
    (["signal"], True, "explanation", None),
    (["signal"], 257, "explanation", None),
    (["signal"], 3, "importance_value", []),
    (["signal"], 3, "importance_value", ["other"]),
    (["signal"], 3, "values", ["trees"]),
    (["signal"], 3, "importance", []),
    (["signal"], 3, "values", ["signal"] * 65),
])
def test_prepare_rejects_unbounded_or_mismatched_specs(schema, trees, view, keys):
    with pytest.raises(ValueError):
        prepare_explanation_spec(schema, trees, view=view, keys=keys)


def test_native_envelope_maps_actual_numeric_values_to_exact_three_field_result():
    spec = decode_explanation_spec(prepare_explanation_spec(SCHEMA, 3))
    native = '{"version":1,"importance":[1.5,0.0],"number_of_trees":3,"out_of_bag_error":0.0}'
    assert decode_native_explanation(native, spec) == FULL


@pytest.mark.parametrize("native", [
    '{"version":1,"importance":[1.5,0.0],"importance":[1.5,0.0],"number_of_trees":3,"out_of_bag_error":0.0}',
    '{"version":1,"importance":[1.5],"number_of_trees":3,"out_of_bag_error":0.0}',
    '{"version":1,"importance":[-1.0,0.0],"number_of_trees":3,"out_of_bag_error":0.0}',
    '{"version":1,"importance":[1.5,0.0],"number_of_trees":4,"out_of_bag_error":0.0}',
    '{"version":1,"importance":[1.5,0.0],"number_of_trees":3,"out_of_bag_error":1.1}',
    '{"version":1,"importance":[1.5,0.0],"number_of_trees":3,"out_of_bag_error":NaN}',
])
def test_native_envelope_rejects_duplicate_forged_or_out_of_domain_values(native):
    spec = decode_explanation_spec(prepare_explanation_spec(SCHEMA, 3))
    with pytest.raises(ValueError):
        decode_native_explanation(native, spec)


def test_public_values_reject_nonfinite_and_inexact_integer_values():
    spec = decode_explanation_spec(prepare_explanation_spec(SCHEMA, 3, view="values",
                                                            keys=["importance", "outOfBagErrorEstimate"]))
    with pytest.raises(ValueError):
        validate_explanation_value([{"signal": 1.0, "constant": 0.0}, float("nan")], spec)
    importance_value = decode_explanation_spec(prepare_explanation_spec(
        SCHEMA, 3, view="importance_value", keys=["signal"],
    ))
    with pytest.raises(ValueError):
        validate_explanation_value(2**53 + 1, importance_value)
