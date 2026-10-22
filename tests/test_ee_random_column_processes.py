"""Typed graph lineage retains new random fields without adding public processes."""
import copy

import pytest

from ee_sampling_contract_helpers import _valid_sampling_graph
from gee import graph
from gee.random_column_spec import prepare_random_column_spec
from gee.sample_table_spec import prepare_sample_limit
from gee.sampling_graph import sample_chain


def with_operation(text):
    nodes = _valid_sampling_graph()
    nodes["random"] = {"process_id": "local_ee_sample_table_op", "arguments": {
        "data": {"from_node": "samples"}, "spec": text}}
    nodes["model"]["arguments"]["data"] = {"from_node": "random"}
    return nodes


def test_typed_chain_exposes_new_training_schema_and_leaves_strings_opaque():
    text = prepare_random_column_spec("split", row_keys=["process_id"])
    nodes = with_operation(text)
    from gee.sampling_spec import encode_spec

    nodes["model"]["arguments"]["spec"] = encode_spec({
        "version": 1, "metric": "euclidean", "class_property": "from_node", "schema": ["split"]})
    before = copy.deepcopy(nodes)
    graph.validate(nodes)
    assert nodes == before
    origin, operations = sample_chain(nodes, "random")
    assert origin is nodes["samples"] and operations == (text,)


def test_every_random_schema_is_validated_even_without_training_consumer():
    nodes = with_operation(prepare_random_column_spec(row_keys=["not_a_column"]))
    nodes.pop("model")
    nodes.pop("classify")
    nodes["random"]["result"] = True
    with pytest.raises(ValueError, match="rowKeys"):
        graph.validate(nodes)


def test_operation_order_allows_only_preexisting_or_earlier_derived_keys():
    nodes = with_operation(prepare_random_column_spec("split"))
    second = prepare_random_column_spec("second", row_keys=["split"])
    nodes["second"] = {"process_id": "local_ee_sample_table_op", "arguments": {
        "data": {"from_node": "random"}, "spec": second}}
    nodes["model"]["arguments"]["data"] = {"from_node": "second"}
    graph.validate(nodes)
    assert sample_chain(nodes, "second")[1] == (nodes["random"]["arguments"]["spec"], second)
    nodes["random"]["arguments"]["spec"] = prepare_random_column_spec("split", row_keys=["second"])
    with pytest.raises(ValueError, match="rowKeys"):
        graph.validate(nodes)


def test_chain_limit_and_wrong_producer_remain_closed():
    nodes = with_operation(prepare_random_column_spec())
    previous = "random"
    for index in range(16):
        name = f"limit{index}"
        nodes[name] = {"process_id": "local_ee_sample_table_op", "arguments": {
            "data": {"from_node": previous}, "spec": prepare_sample_limit(1)}}
        previous = name
    nodes["model"]["arguments"]["data"] = {"from_node": previous}
    with pytest.raises(ValueError, match="16"):
        graph.validate(nodes)
    wrong = with_operation(prepare_random_column_spec())
    wrong["random"]["arguments"]["data"] = {"from_node": "model"}
    with pytest.raises(ValueError):
        graph.validate(wrong)
