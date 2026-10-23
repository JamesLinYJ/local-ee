"""Strict finite protocol and public graph admission for pixel matrices."""
import json

import pytest

from gee.integer_values_spec import constant_operand
from gee.local_processes import process_spec, validate_local_process
from gee.matrix_values_spec import (
    PROCESS_ID, decode_matrix_values_spec, matrix_input_bands,
    matrix_output_shape, prepare_matrix_values_spec,
)
from gee.sampling_graph import validate_sampling_dependencies


def _spec(op="solve", rows=2, cols=2, rhs=1, operands=None):
    count = rows * cols + (rows * rhs if op == "solve" else 0)
    return prepare_matrix_values_spec(
        op, rows, cols, rhs,
        [{"band": index} for index in range(count)] if operands is None else operands,
    )


@pytest.mark.parametrize("op,rows,cols,rhs,output", [
    ("solve", 3, 2, 2, (2, 2)), ("solve", 2, 3, 1, (3, 1)),
    ("inverse", 8, 8, 0, (8, 8)), ("pinverse", 1, 8, 0, (8, 1)),
])
def test_shapes_round_trip_without_summing_input_and_output_budgets(op, rows, cols, rhs, output):
    encoded = _spec(op, rows, cols, rhs)
    decoded = decode_matrix_values_spec(encoded)
    assert matrix_output_shape(decoded) == output
    assert matrix_input_bands(decoded) == rows * cols + rows * rhs
    assert encoded == json.dumps(decoded, sort_keys=True, separators=(",", ":"))
    assert len(encoded) <= 8192


def test_finite_constants_signed_zero_and_repeated_bands_keep_exact_bits():
    operands = [{"band": 0}, constant_operand(-0.0), constant_operand(5e-324), {"band": 0}]
    decoded = decode_matrix_values_spec(_spec("pinverse", 2, 2, 0, operands))
    assert decoded["operands"] == operands
    assert operands[1] == {"constant": "8000000000000000"}
    assert matrix_input_bands(decoded) == 1


@pytest.mark.parametrize("change", [
    {"v": True}, {"v": 2}, {"op": "svd"}, {"op": []},
    {"rows": 0}, {"rows": 9}, {"rows": True}, {"cols": 2.0},
    {"rhs_cols": 0}, {"rhs_cols": 9}, {"rhs_cols": True},
    {"operands": []}, {"operands": [{"band": 0}] * 7},
    {"operands": [{"band": True}] * 6},
    {"operands": [{"band": 64}] * 6},
    {"operands": [{"band": 1}] * 6},
    {"operands": [{"band": 0}, {"band": 2}] * 3},
    {"operands": [{"constant": "0000000000000000"}] * 6},
    {"operands": [{"constant": "7ff0000000000000"}] * 5 + [{"band": 0}]},
    {"operands": [{"constant": "7ff8000000000000"}] * 5 + [{"band": 0}]},
    {"operands": [{"constant": "3FF0000000000000"}] * 5 + [{"band": 0}]},
    {"operands": [{"band": 0, "constant": "0000000000000000"}] * 6},
    {"operands": [{"from_node": "x"}] * 6}, {"extra": 1},
])
def test_decoder_rejects_malformed_wire(change):
    value = json.loads(_spec())
    value.update(change)
    with pytest.raises(ValueError):
        decode_matrix_values_spec(json.dumps(value, sort_keys=True, separators=(",", ":")))


@pytest.mark.parametrize("encoded", [
    "", "{}", "[]", "null", "NaN", "é", " " * 8193,
    "[" * 2000 + "]" * 2000,
    '{"v":1,"v":1}',
])
def test_decoder_rejects_invalid_or_noncanonical_json(encoded):
    with pytest.raises(ValueError):
        decode_matrix_values_spec(encoded)


def test_decoder_rejects_duplicate_nested_keys_and_whitespace():
    encoded = _spec()
    for altered in (" " + encoded, encoded.replace('{"band":0}', '{"band":0,"band":0}')):
        with pytest.raises(ValueError):
            decode_matrix_values_spec(altered)


@pytest.mark.parametrize("op,rows,cols,rhs", [
    ("inverse", 2, 3, 0), ("inverse", 2, 2, 1),
    ("pinverse", 2, 2, 1), ("solve", 8, 8, 1),
])
def test_shape_and_combined_input_overflow_reject_before_execution(op, rows, cols, rhs):
    with pytest.raises(ValueError):
        _spec(op, rows, cols, rhs)


def test_process_contract_and_top_level_cube_admission():
    spec = _spec()
    assert process_spec(PROCESS_ID)["id"] == PROCESS_ID
    args = {"data": {"from_node": "source"}, "spec": spec}
    validate_local_process(PROCESS_ID, args, 0)
    for depth, altered in ((1, args), (0, {**args, "url": "x"}),
                           (0, {**args, "data": {"from_parameter": "data"}}),
                           (0, {**args, "spec": {"from_node": "spec"}})):
        with pytest.raises(ValueError):
            validate_local_process(PROCESS_ID, altered, depth)


@pytest.mark.parametrize("producer", [
    "local_ee_table", "local_ee_train_minimum_distance", "local_ee_sample_regions",
    "local_ee_train_smile_rf_rows", "save_result", "constant",
])
def test_matrix_cube_dependency_rejects_tables_models_scalars_and_sinks(producer):
    # This is the dependency type pass, after individual node validation.
    nodes = {"matrix": {"process_id": PROCESS_ID, "arguments": {
                 "data": {"from_node": "bad"}, "spec": _spec()}},
             "bad": {"process_id": producer, "arguments": {}}}
    with pytest.raises(ValueError, match="audited raster cube|opaque random forest model"):
        validate_sampling_dependencies(nodes)


def test_matrix_is_audited_raster_input_for_a_second_matrix():
    nodes = {"load": {"process_id": "load_collection", "arguments": {}},
             "a": {"process_id": PROCESS_ID, "arguments": {
                 "data": {"from_node": "load"}, "spec": _spec()}},
             "b": {"process_id": PROCESS_ID, "arguments": {
                 "data": {"from_node": "a"}, "spec": _spec()}}}
    validate_sampling_dependencies(nodes)
