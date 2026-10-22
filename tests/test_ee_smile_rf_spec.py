"""Pure canonical-wire coverage for bounded Smile random-forest specs."""
from __future__ import annotations

import json

import pytest

from gee.sampling_spec import encode_spec
from gee.smile_rf_spec import (
    IMPLEMENTATION,
    MAX_SPEC_BYTES,
    MAX_TREES,
    decode_rf_spec,
    prepare_rf_parameters,
    prepare_rf_spec,
)


def _parameters(**changes):
    values = {
        "number_of_trees": 100,
        "variables_per_split": None,
        "min_leaf_population": 1,
        "bag_fraction": 0.5,
        "max_nodes": None,
        "seed": 0,
    }
    values.update(changes)
    return values


def _spec_value(parameters=None, schema=None, class_property="label"):
    return {
        **(_parameters() if parameters is None else parameters),
        "version": 1,
        "implementation": IMPLEMENTATION,
        "schema": ["red", "nir"] if schema is None else schema,
        "class_property": class_property,
    }


def test_sdk_parameter_normalization_and_spec_round_trip_are_stable():
    parameters = prepare_rf_parameters(
        number_of_trees=12.0,
        variables_per_split=2.0,
        min_leaf_population=3.0,
        bag_fraction=0.75,
        max_nodes=9.0,
        seed=-17.0,
    )
    schema = ["red", "nir"]
    parameters_before, schema_before = parameters.copy(), schema.copy()

    text = prepare_rf_spec(parameters, schema, "label")
    decoded = decode_rf_spec(text)

    assert text == encode_spec(json.loads(text))
    assert decoded == json.loads(text)
    assert decoded == _spec_value({
        "number_of_trees": 12,
        "variables_per_split": 2,
        "min_leaf_population": 3,
        "bag_fraction": 0.75,
        "max_nodes": 9,
        "seed": -17,
    })
    assert all(type(decoded[key]) is int for key in (
        "number_of_trees", "variables_per_split", "min_leaf_population", "max_nodes", "seed",
    ))
    assert parameters == parameters_before
    assert schema == schema_before


@pytest.mark.parametrize("parameters", [
    {"number_of_trees": 1, "variables_per_split": 1, "min_leaf_population": 1,
     "bag_fraction": 0.000001, "max_nodes": 2, "seed": -(2**31)},
    {"number_of_trees": MAX_TREES, "variables_per_split": 2, "min_leaf_population": 1000,
     "bag_fraction": 1, "max_nodes": 1000, "seed": 2**31 - 1},
    {"number_of_trees": 3, "variables_per_split": None, "min_leaf_population": 7,
     "bag_fraction": 0.5, "max_nodes": None, "seed": 0},
])
def test_all_six_supported_parameter_boundaries(parameters):
    schema = ["a", "b"]
    text = prepare_rf_spec(parameters, schema, "target")
    assert decode_rf_spec(text)["schema"] == schema


def test_sdk_integer_float_coercion_does_not_weaken_wire_integer_types():
    normalized = prepare_rf_parameters(2.0, 1.0, 1.0, 0.5, 2.0, -1.0)
    assert normalized == _parameters(
        number_of_trees=2,
        variables_per_split=1,
        min_leaf_population=1,
        bag_fraction=0.5,
        max_nodes=2,
        seed=-1,
    )

    float_wire_parameters = _parameters(number_of_trees=2.0)
    with pytest.raises(ValueError, match="number_of_trees must be an integer"):
        prepare_rf_spec(float_wire_parameters, ["x"], "label")

    text = encode_spec(_spec_value(_parameters(number_of_trees=2.0), ["x"]))
    with pytest.raises(ValueError, match="number_of_trees must be an integer"):
        decode_rf_spec(text)


@pytest.mark.parametrize("changes", [
    {"number_of_trees": 0}, {"number_of_trees": MAX_TREES + 1},
    {"variables_per_split": 0}, {"variables_per_split": 9},
    {"min_leaf_population": 0}, {"min_leaf_population": 1001},
    {"bag_fraction": 0}, {"bag_fraction": -0.1}, {"bag_fraction": 1.0001},
    {"max_nodes": 1}, {"max_nodes": 1001},
    {"seed": -(2**31) - 1}, {"seed": 2**31},
])
def test_parameter_values_outside_declared_ranges_reject(changes):
    with pytest.raises(ValueError):
        prepare_rf_spec(_parameters(**changes), ["x", "y"], "label")


@pytest.mark.parametrize("changes", [
    {"number_of_trees": True}, {"number_of_trees": 2.5},
    {"variables_per_split": False}, {"min_leaf_population": 1.0},
    {"bag_fraction": True}, {"bag_fraction": float("nan")},
    {"bag_fraction": float("inf")}, {"bag_fraction": "0.5"},
    {"max_nodes": 2.0}, {"seed": False}, {"seed": 1.5},
])
def test_parameter_types_and_nonfinite_bag_fraction_reject(changes):
    with pytest.raises(ValueError):
        prepare_rf_spec(_parameters(**changes), ["x"], "label")


@pytest.mark.parametrize("parameters", [
    {key: value for key, value in _parameters().items() if key != "seed"},
    {**_parameters(), "unknown": 1},
])
def test_parameter_object_requires_exactly_the_six_supported_keys(parameters):
    with pytest.raises(ValueError):
        prepare_rf_spec(parameters, ["x"], "label")


def test_mtry_cannot_exceed_the_declared_input_dimension():
    with pytest.raises(ValueError, match="exceeds the input dimension"):
        prepare_rf_spec(_parameters(variables_per_split=3), ["x", "y"], "label")
    prepare_rf_spec(_parameters(variables_per_split=2), ["x", "y"], "label")


@pytest.mark.parametrize("schema", [
    [], ["x"] * 9, ["x", "x"], ["x.y"], ["x" * 257],
    ["system:index"], [".geo"],
])
def test_schema_must_be_bounded_unique_flat_and_numeric_feature_columns(schema):
    with pytest.raises(ValueError):
        prepare_rf_spec(_parameters(), schema, "label")


@pytest.mark.parametrize("schema", [None, "x", 4])
def test_spec_wire_requires_schema_to_be_a_list(schema):
    value = _spec_value()
    value["schema"] = schema
    with pytest.raises(ValueError):
        decode_rf_spec(encode_spec(value))


def test_prepare_api_normalizes_an_immutable_schema_sequence_to_wire_list():
    text = prepare_rf_spec(_parameters(), ("x",), "label")
    assert decode_rf_spec(text)["schema"] == ["x"]


def test_schema_and_class_property_length_and_mtry_dimension_boundaries_round_trip():
    long_name = "x" * 256
    schema = [long_name, *[f"feature_{index}" for index in range(7)]]
    text = prepare_rf_spec(_parameters(variables_per_split=8), schema, long_name)

    decoded = decode_rf_spec(text)
    assert decoded["schema"] == schema
    assert decoded["class_property"] == long_name
    assert decoded["variables_per_split"] == len(schema)


@pytest.mark.parametrize("class_property", [
    "", "x.y", "x" * 257, "system:index", ".geo", None, 1,
])
def test_class_property_must_be_bounded_flat_and_nonreserved(class_property):
    with pytest.raises(ValueError):
        prepare_rf_spec(_parameters(), ["nir"], class_property)


def test_class_property_may_also_be_an_explicit_schema_column():
    text = prepare_rf_spec(_parameters(), ["nir", "label"], "label")
    decoded = decode_rf_spec(text)
    assert decoded["schema"] == ["nir", "label"]
    assert decoded["class_property"] == "label"


def test_graph_protocol_looking_schema_names_are_canonical_data_not_dependencies():
    text = prepare_rf_spec(
        _parameters(), ["process_id", "from_node", "process_graph"], "class_label",
    )

    assert json.loads(text)["schema"] == ["process_id", "from_node", "process_graph"]
    assert decode_rf_spec(text)["schema"] == ["process_id", "from_node", "process_graph"]

    with pytest.raises(ValueError, match="exact version1"):
        decode_rf_spec(encode_spec({**_spec_value(), "process_id": "local_ee_train_smile"}))


@pytest.mark.parametrize("override", [
    {"version": True}, {"version": 2}, {"version": 1.0},
    {"implementation": "smile-1.5.2"}, {"implementation": None},
])
def test_decoder_requires_exact_version_and_pinned_implementation(override):
    value = _spec_value()
    value.update(override)
    with pytest.raises(ValueError, match="exact version1 Smile1.5.3"):
        decode_rf_spec(encode_spec(value))


def test_decoder_rejects_missing_extra_duplicate_and_noncanonical_fields():
    valid = prepare_rf_spec(_parameters(), ["x"], "label")
    with pytest.raises(ValueError, match="exact version1"):
        decode_rf_spec(encode_spec({key: value for key, value in json.loads(valid).items() if key != "seed"}))
    with pytest.raises(ValueError, match="exact version1"):
        decode_rf_spec(encode_spec({**json.loads(valid), "debug": "ignored"}))
    with pytest.raises(ValueError, match="Duplicate specification key"):
        decode_rf_spec(valid[:-1] + ',"version":1}')
    with pytest.raises(ValueError, match="canonical"):
        decode_rf_spec(valid + " ")


def test_spec_decoder_rejects_non_string_inputs_and_nonfinite_json_tokens():
    for value in (None, {}, [], 1):
        with pytest.raises(ValueError):
            decode_rf_spec(value)

    valid = prepare_rf_spec(_parameters(), ["x"], "label")
    for token in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValueError, match="finite JSON"):
            decode_rf_spec(valid.replace('"bag_fraction":0.5', f'"bag_fraction":{token}'))


def test_spec_limit_is_measured_in_utf8_bytes_before_json_or_schema_validation():
    unicode_text = json.dumps("猫" * 6000, ensure_ascii=False, separators=(",", ":"))
    assert len(unicode_text) < MAX_SPEC_BYTES
    assert len(unicode_text.encode("utf-8")) > MAX_SPEC_BYTES

    with pytest.raises(ValueError, match="exceeds16384 UTF-8 bytes"):
        decode_rf_spec(unicode_text)
    with pytest.raises(ValueError, match="exceeds16384 UTF-8 bytes"):
        decode_rf_spec(" " * (MAX_SPEC_BYTES + 1))
