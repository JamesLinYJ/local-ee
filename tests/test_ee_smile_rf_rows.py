"""Validation and work-budget checks for canonical Smile training rows."""
from __future__ import annotations

import copy
import json

import pytest

from gee.sampling_spec import encode_spec
from gee.smile_rf_spec import (
    MAX_CLASSES,
    MAX_ROWS,
    MAX_TRAINING_WORK,
    decode_rf_rows,
    decode_rf_spec,
    prepare_rf_rows,
    prepare_rf_spec,
    training_work_bound,
)


def _spec(schema=("nir", "red"), *, trees=1, mtry=1, max_nodes=2):
    parameters = {
        "number_of_trees": trees,
        "variables_per_split": mtry,
        "min_leaf_population": 1,
        "bag_fraction": 0.5,
        "max_nodes": max_nodes,
        "seed": 0,
    }
    return decode_rf_spec(prepare_rf_spec(parameters, list(schema), "label"))


def _valid_rows(count=2, dimensions=2):
    return [[index % 2, [index + column / 10 for column in range(dimensions)]]
            for index in range(count)]


def test_rows_prepare_and_decode_canonically_without_mutating_source_arrays():
    spec = _spec()
    rows = [[0, [-2**53, -0.0]], [1, [2**53, 1.0e300]]]
    before = copy.deepcopy(rows)

    text = prepare_rf_rows(rows, spec)

    assert text == encode_spec(json.loads(text))
    assert decode_rf_rows(text, spec) == json.loads(text)
    assert rows == before
    assert decode_rf_rows(text, spec)["rows"] == rows


@pytest.mark.parametrize("count", [0, 1, MAX_ROWS + 1])
def test_training_rows_require_between_two_and_one_thousand_rows(count):
    spec = _spec()
    rows = _valid_rows(count)
    with pytest.raises(ValueError, match="training row count must be an integer in 2..1000"):
        prepare_rf_rows(rows, spec)


def test_row_count_and_class_count_upper_boundaries_are_supported():
    spec = _spec(("x",), trees=1, mtry=1, max_nodes=2)
    rows_at_row_limit = [[index % 2, [index]] for index in range(MAX_ROWS)]
    assert len(decode_rf_rows(prepare_rf_rows(rows_at_row_limit, spec), spec)["rows"]) == MAX_ROWS

    rows_at_class_limit = [[label, [label]] for label in range(MAX_CLASSES)]
    assert len(decode_rf_rows(prepare_rf_rows(rows_at_class_limit, spec), spec)["rows"]) == MAX_CLASSES


@pytest.mark.parametrize("rows", [
    [[0, [1]], [0, [2]]],  # only one class
    [[0, [1]], [2, [2]]],  # a gap in the class labels
    [[1, [1]], [2, [2]]],  # labels must begin at zero
])
def test_rows_require_two_to_sixty_four_contiguous_classes_starting_at_zero(rows):
    with pytest.raises(ValueError, match="contiguous class labels"):
        prepare_rf_rows(rows, _spec(("x",)))


@pytest.mark.parametrize("label", [True, False, 0.0, 1.0, -1, MAX_CLASSES])
def test_class_labels_are_exact_bounded_wire_integers(label):
    with pytest.raises(ValueError, match="class label"):
        prepare_rf_rows([[0, [1]], [label, [2]]], _spec(("x",)))


@pytest.mark.parametrize("row", [
    None, (0, [1, 2]), [0], [0, 1, 2],
    [0, (1, 2)], [0, [1]], [0, [1, 2, 3]],
])
def test_each_row_is_a_two_element_list_with_schema_ordered_vector(row):
    rows = [row, [1, [2, 3]]]
    with pytest.raises(ValueError, match="label and schema-ordered vector"):
        prepare_rf_rows(rows, _spec())


@pytest.mark.parametrize("value", [
    True, False, None, "from_node", {"process_graph": "local_ee_train_smile"},
    [1], float("nan"), float("inf"), float("-inf"), 2**53 + 1, -(2**53 + 1),
])
def test_feature_vectors_reject_non_numeric_nonfinite_and_non_exact_values(value):
    with pytest.raises(ValueError, match="finite exact-domain Float64"):
        prepare_rf_rows([[0, [value]], [1, [2]]], _spec(("process_id",)))


def test_row_values_accept_exact_integer_domain_endpoints_and_finite_float64():
    rows = [[0, [-2**53]], [1, [2**53]], [1, [-1.25e300]]]
    assert decode_rf_rows(prepare_rf_rows(rows, _spec(("from_node",))), _spec(("from_node",)))["rows"] == rows


@pytest.mark.parametrize("row_spec", [
    {"version": True, "rows": [[0, [1]], [1, [2]]]},
    {"version": 2, "rows": [[0, [1]], [1, [2]]]},
    {"version": 1, "rows": [[0, [1]], [1, [2]]], "geometry": None},
    {"version": 1, "rows": [[0, [1]], [1, [2]]], "process_id": "local_ee_map"},
])
def test_rows_decoder_requires_exact_versioned_top_level_fields(row_spec):
    with pytest.raises(ValueError, match="exactly version1 and a rows list"):
        decode_rf_rows(encode_spec(row_spec), _spec(("x",)))


def test_rows_decoder_rejects_duplicate_keys_and_noncanonical_json():
    spec = _spec(("x",))
    canonical = prepare_rf_rows([[0, [1]], [1, [2]]], spec)
    duplicate = canonical[:-1] + ',"version":1}'
    with pytest.raises(ValueError, match="Duplicate specification key"):
        decode_rf_rows(duplicate, spec)
    with pytest.raises(ValueError, match="canonical"):
        decode_rf_rows(canonical + " ", spec)


def test_rows_decoder_rejects_nonfinite_json_tokens_and_non_string_inputs():
    spec = _spec(("x",))
    canonical = prepare_rf_rows([[0, [1]], [1, [2]]], spec)
    raw_nonfinite = canonical.replace('"rows":[[0,[1]],[1,[2]]]', '"rows":[[0,[NaN]],[1,[2]]]')
    with pytest.raises(ValueError, match="finite JSON"):
        decode_rf_rows(raw_nonfinite, spec)
    for value in (None, {}, [], 1):
        with pytest.raises(ValueError):
            decode_rf_rows(value, spec)


def test_training_work_budget_accepts_exact_limit_and_rejects_next_tree():
    schema = tuple(f"feature_{index}" for index in range(8))
    at_limit = _spec(schema, trees=125, mtry=8, max_nodes=None)
    assert training_work_bound(at_limit, MAX_ROWS) == MAX_TRAINING_WORK

    over_limit = _spec(schema, trees=126, mtry=8, max_nodes=None)
    with pytest.raises(ValueError, match="1000000000 training-work budget"):
        training_work_bound(over_limit, MAX_ROWS)


def test_row_work_budget_is_checked_before_inspecting_each_row():
    expensive = _spec(tuple(f"feature_{index}" for index in range(8)),
                      trees=126, mtry=8, max_nodes=None)
    # These rows are intentionally malformed. The aggregate work cap is
    # established from the declared count before the row payload is traversed.
    with pytest.raises(ValueError, match="1000000000 training-work budget"):
        prepare_rf_rows([None] * MAX_ROWS, expensive)


@pytest.mark.parametrize("row_count", [True, 1, MAX_ROWS + 1, 1.0, "2"])
def test_work_bound_rejects_invalid_row_count_types_and_ranges(row_count):
    with pytest.raises(ValueError, match="training row count"):
        training_work_bound(_spec(), row_count)
