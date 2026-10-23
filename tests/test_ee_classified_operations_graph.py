"""Closed graph edges and sequential schemas for post-classification tables."""
from copy import deepcopy

import pytest

from gee.compat.earthengine.ir import Filter
from gee.graph import validate
from gee.image_sampling_spec import prepare_image_sample_spec
from gee.random_column_spec import prepare_random_column_spec
from gee.rf_validation_spec import prepare_matrix_spec
from gee.runtime_table_graph import runtime_table_columns
from gee.runtime_table_spec import PROCESS, runtime_columns
from gee.sample_table_spec import prepare_sample_filter, prepare_sample_limit
from test_ee_rf_validation_processes import program


def operations_graph(count=1):
    nodes = program()
    source = "table"
    for index in range(count):
        key = f"op{index}"
        nodes[key] = {"process_id": PROCESS, "arguments": {
            "data": {"from_node": source}, "spec": prepare_sample_limit(None),
        }}
        source = key
    nodes["matrix"]["arguments"]["data"] = {"from_node": source}
    return nodes, source


def test_runtime_columns_and_direct_json_csv_matrix_consumers():
    nodes, source = operations_graph()
    nodes[source]["arguments"]["spec"] = prepare_random_column_spec(
        column_name="after", seed=31, row_keys=["prediction"],
    )
    headers = runtime_table_columns(nodes, source)
    assert headers == ["system:index", "x", "truth", "prediction", "after", ".geo"]
    validate(nodes)
    for format in ("JSON", "CSV"):
        exported = deepcopy(nodes)
        exported["value"].pop("result")
        exported["sink"] = {"process_id": "save_result", "arguments": {
            "data": {"from_node": source}, "format": format}, "result": True}
        validate(exported)


def test_random_columns_use_current_headers_and_do_not_mutate_base():
    nodes, source = operations_graph(2)
    base = nodes["table"]["arguments"]["spec"]
    nodes["op0"]["arguments"]["spec"] = prepare_random_column_spec(
        column_name="derived", row_keys=["prediction"],
    )
    nodes[source]["arguments"]["spec"] = prepare_random_column_spec(
        column_name="derived", row_keys=["derived"], distribution="normal",
    )
    assert runtime_table_columns(nodes, source).count("derived") == 1
    validate(nodes)
    assert "derived" not in runtime_columns(base)
    nodes["op0"]["arguments"]["spec"] = prepare_random_column_spec(row_keys=["missing"])
    with pytest.raises(ValueError, match="rowKeys"):
        validate(nodes)


@pytest.mark.parametrize("producer", ["model", "matrix", "training", "value"])
def test_runtime_operation_requires_classified_producer(producer):
    nodes, source = operations_graph()
    nodes[source]["arguments"]["data"] = {"from_node": producer}
    with pytest.raises(ValueError, match="audited"):
        validate(nodes)


@pytest.mark.parametrize("consumer,argument", [
    ("add", "x"), ("local_ee_sample_table_op", "data"),
    ("local_ee_train_smile_rf_samples", "data"),
])
@pytest.mark.parametrize("nested", [False, True])
def test_runtime_operations_cannot_escape_into_wrong_consumers(consumer, argument, nested):
    nodes, source = operations_graph()
    ref = {"from_node": source}
    arguments = {argument: [ref] if nested else ref}
    if consumer == "add":
        arguments["y"] = 1
    elif consumer == "local_ee_sample_table_op":
        arguments["spec"] = prepare_sample_limit(1)
    else:
        arguments["spec"] = nodes["model"]["arguments"]["spec"]
    nodes["escape"] = {"process_id": consumer, "arguments": arguments}
    with pytest.raises(ValueError):
        validate(nodes)


def test_runtime_operations_count_and_cycles_fail_closed():
    nodes, _ = operations_graph(16)
    validate(nodes)
    nodes, _ = operations_graph(17)
    with pytest.raises(ValueError, match="16"):
        validate(nodes)


def test_sampled_and_post_classification_operations_share_the_sixteen_step_cap():
    nodes, post = operations_graph()
    region = {"type": "Polygon", "coordinates": [
        [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
    ]}
    nodes["load"] = {"process_id": "load_collection", "arguments": {"id": "local"}}
    nodes["sample"] = {"process_id": "local_ee_sample_regions", "arguments": {
        "data": {"from_node": "load"},
        "spec": prepare_image_sample_spec(region, ["x", "truth"]),
    }}
    source = "sample"
    for index in range(16):
        key = f"sample_op{index}"
        nodes[key] = {"process_id": "local_ee_sample_table_op", "arguments": {
            "data": {"from_node": source}, "spec": prepare_sample_limit(None),
        }}
        source = key
    nodes["table"]["process_id"] = "local_ee_smile_rf_classify_samples"
    nodes["table"]["arguments"].pop("rows")
    nodes["table"]["arguments"]["data"] = {"from_node": source}
    with pytest.raises(ValueError, match="16"):
        validate(nodes)
    nodes.pop(post)
    nodes["matrix"]["arguments"]["data"] = {"from_node": "table"}
    validate(nodes)
    nodes, source = operations_graph()
    nodes[source]["arguments"]["data"] = {"from_node": source}
    with pytest.raises(ValueError, match="cycle"):
        validate(nodes)


def test_empty_after_limit_needs_explicit_matrix_order():
    nodes, source = operations_graph()
    nodes[source]["arguments"]["spec"] = prepare_sample_limit(0)
    validate(nodes)
    nodes["matrix"]["arguments"]["spec"] = prepare_matrix_spec("truth", "prediction")
    with pytest.raises(ValueError, match="explicit order"):
        validate(nodes)


def test_canonical_filter_spec_is_data_and_result_format_stays_narrow():
    nodes, source = operations_graph()
    nodes[source]["arguments"]["spec"] = prepare_sample_filter(
        Filter("equals", {"leftField": "truth", "rightValue": 0}),
    )
    validate(nodes)
    nodes["value"].pop("result")
    nodes["sink"] = {"process_id": "save_result", "arguments": {
        "data": {"from_node": source}, "format": "GTiff"}, "result": True}
    with pytest.raises(ValueError, match="CSV or JSON"):
        validate(nodes)
