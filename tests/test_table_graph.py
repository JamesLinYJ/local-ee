"""Data-only table DAG and physical batch-output contracts."""
import copy
import csv
import json
import os
import uuid
from pathlib import Path

import pytest

from gee import graph
from gee.local_processes import process_spec
from gee.table_graph import (TABLE_PROCESS, execute_table_graph, table_input_graph,
                             validate_table_graph)


def table():
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": None, "id": "row-1",
        "properties": {"value": 0.25},
    }]}


def process(data=None, selected=None):
    result = table_input_graph(table() if data is None else data,
                               ["system:index", "value"] if selected is None else selected)
    result["gee_table"].pop("result")
    result["out"] = {"process_id": "save_result", "arguments": {
        "data": {"from_node": "gee_table"}, "format": "CSV"}, "result": True}
    return result


def job_folder(tmp_path):
    job = tmp_path / "jobs" / str(uuid.uuid4())
    (job / "out").mkdir(parents=True)
    return job


def test_literal_keys_never_become_processes_or_catalog_dependencies():
    data = table()
    properties = data["features"][0]["properties"]
    properties.update({"process_id": "load_collection", "arguments": {"id": "secret"},
                       "from_node": "outside", "namespace": "https://outside.example",
                       "process_graph": {"load": {"process_id": "run_udf"}}})
    before = copy.deepcopy(data)
    value = process(data, ["value", "process_id", "from_node"])
    graph.validate(value)
    assert graph.collection_loads(value) == {}
    materialized = graph.materialize(value, {}, "/unused")
    assert materialized == value
    assert materialized is not value
    assert data == before
    assert validate_table_graph(value)[0] == data


@pytest.mark.parametrize("mutation", [
    lambda g: g.update(extra={"process_id": "load_collection", "arguments": {"id": "x"}}),
    lambda g: g["out"]["arguments"].update(format="GTiff"),
    lambda g: g["out"]["arguments"].update(options={"filename": "/tmp/escape.csv"}),
    lambda g: g["out"]["arguments"].update(data={"from_node": "out"}),
    lambda g: g["out"].update(namespace="outside"),
    lambda g: g["out"].update(result=False),
    lambda g: g["gee_table"].update(result=True),
    lambda g: g["gee_table"]["arguments"].update(url="https://outside.example"),
    lambda g: g["gee_table"]["arguments"].update(data={"from_node": "out"}),
    lambda g: g["gee_table"]["arguments"].update(columns=["missing"]),
    lambda g: g["gee_table"]["arguments"].update(columns=["value", "value"]),
    lambda g: g["gee_table"].update(description={"unexpected": True}),
    lambda g: g["out"].update(result=1),
])
def test_table_graph_rejects_mixed_or_malformed_execution(mutation):
    value = process()
    mutation(value)
    with pytest.raises((ValueError, TypeError)):
        graph.validate(value)


def test_table_process_cannot_be_hidden_in_a_callback():
    value = {"outer": {"process_id": "apply", "arguments": {
        "data": [1], "process": {"process_graph": process()}}, "result": True}}
    with pytest.raises(ValueError, match="top-level table-only"):
        graph.validate(value)


def test_incomplete_table_input_is_not_a_public_executable_graph():
    value = table_input_graph(table(), ["value"])
    with pytest.raises(ValueError, match="exactly"):
        graph.validate(value)


def test_existing_serialized_graph_cap_still_counts_escaped_unicode():
    data = table()
    data["features"][0]["properties"]["value"] = "雪" * 167000
    value = process(data, ["value"])
    with pytest.raises(ValueError, match="1 MB"):
        graph.validate(value)


def test_process_spec_advertises_feature_table_and_explicit_columns():
    spec = process_spec(TABLE_PROCESS)
    assert spec["returns"]["schema"]["subtype"] == "vector-cube"
    assert [p["name"] for p in spec["parameters"]] == ["data", "columns"]


def test_batch_entrypoint_writes_real_csv_without_initializing_spark(tmp_path, monkeypatch):
    from engine import native_run
    job = job_folder(tmp_path)
    (job / "graph.json").write_text(json.dumps(process()))
    monkeypatch.setattr(native_run, "setup", lambda *_: pytest.fail("CSV started a JVM"))
    original_umask = os.umask(0o077)
    try:
        native_run.run(job)
    finally:
        os.umask(original_umask)
    target = job / "out/openEO.csv"
    with target.open(newline="", encoding="utf-8") as stream:
        assert list(csv.reader(stream)) == [["system:index", "value"], ["row-1", "0.25"]]
    assert target.stat().st_mode & 0o007 == 0


def test_non_table_graph_delegates_without_creating_artifacts(tmp_path):
    assert execute_table_graph({"a": {"process_id": "sum"}}, tmp_path) is False
    assert list(tmp_path.iterdir()) == []


def test_existing_result_and_symlink_cannot_be_overwritten(tmp_path):
    job = job_folder(tmp_path)
    target = job / "out/openEO.csv"
    target.write_text("keep existing")
    with pytest.raises(FileExistsError):
        execute_table_graph(process(), job)
    assert target.read_text() == "keep existing"
    target.unlink()
    outside = tmp_path / "outside.csv"
    outside.write_text("private")
    target.symlink_to(outside)
    with pytest.raises(FileExistsError):
        execute_table_graph(process(), job)
    assert outside.read_text() == "private"


def test_symlink_output_directory_and_non_job_location_are_rejected(tmp_path):
    job = job_folder(tmp_path)
    output = job / "out"
    output.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    output.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="physical"):
        execute_table_graph(process(), job)
    assert list(outside.iterdir()) == []
    unrelated = tmp_path / "other" / str(uuid.uuid4())
    (unrelated / "out").mkdir(parents=True)
    with pytest.raises((ValueError, FileNotFoundError)):
        execute_table_graph(process(), unrelated)


def test_root_alias_uses_the_same_physical_job_and_child_symlinks_still_reject(tmp_path):
    root = tmp_path / "physical"
    job = job_folder(root)
    alias = tmp_path / "root_alias"
    alias.symlink_to(root, target_is_directory=True)
    assert execute_table_graph(process(), alias / "jobs" / job.name) is True
    assert (job / "out/openEO.csv").is_file()
    other_id = str(uuid.uuid4())
    (root / "jobs" / other_id).symlink_to(job, target_is_directory=True)
    with pytest.raises(ValueError, match="physical"):
        execute_table_graph(process(), alias / "jobs" / other_id)


@pytest.mark.parametrize("collection_id", [None, [], {}, 12, False])
def test_catalog_load_ids_remain_typed_before_snapshot_scan(collection_id):
    value = {"load": {"process_id": "load_collection", "arguments": {"id": collection_id},
                      "result": True}}
    with pytest.raises(ValueError, match="字符串"):
        graph.validate(value)
