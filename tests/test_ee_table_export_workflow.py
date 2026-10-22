"""Trusted synthetic integration for official-SDK inline table export.

This exercises the local dispatch, worker, CSV runner, finalizer and result
reader in-process. The queue/database and NativeTask launch are test doubles;
it is not native-process, Seatbelt, browser or Google Earth Engine acceptance.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from gee import graph
from gee.graph import collection_loads, materialize
from gee.ee_translate import UnsupportedEEError
from gee.services import ee as ee_service
from gee.table_graph import TABLE_PROCESS, validate_table_graph
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import USER, install, run_batch


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def integration(tmp_path, monkeypatch):
    with OfflineGuard() as guard:
        fixture = install(monkeypatch, tmp_path)
        yield fixture
    assert guard.evidence()["attempt_count"] == 0


def _prediction_collection(ee, fixture):
    training = ee.FeatureCollection([
        ee.Feature(None, row) for row in fixture["training"]
    ])
    model = ee.Classifier.minimumDistance(metric="euclidean", kNearest=1).train(
        features=training,
        classProperty="landcover",
        inputProperties=fixture["input_properties"],
    )
    notes = ['城市, "甲"\n第二行', "含有雪和逗号，继续", "普通样点", "引号 \"乙\"", "结束"]
    validation = []
    for index, row in enumerate(fixture["validation"]):
        properties = {
            **row,
            "system:index": f"validation-{index}",
            "note": notes[index],
            "nested": {"标签": "样本", "values": [index, None]},
        }
        if index in {0, 2}:
            properties["nullable"] = None if index == 0 else {"present": True}
        feature = ee.Feature(
            ee.Geometry.Point([100 + index, 30 + index]), properties
        )
        validation.append(feature)
    return ee.FeatureCollection(validation).classify(model, "predicted")


def _drive_task(ee, collection, *, description="分类预测", prefix="分类,结果"):
    return ee.batch.Export.table.toDrive(
        collection=collection,
        description=description,
        folder="synthetic-research-folder",
        fileNamePrefix=prefix,
        fileFormat="CSV",
        selectors=["predicted", "note", "system:index", "nested", "nullable", ".geo"],
    )


def test_official_trained_classifier_export_runs_through_dispatch_worker_and_reader(integration):
    fixture = json.loads((ROOT / "tests/fixtures/ee-minimum-distance-v1.json").read_text())
    ee = integration.ee
    task = _drive_task(ee, _prediction_collection(ee, fixture))
    task.start()
    job_id = task.id
    row = integration.store.job(job_id, USER)

    assert row["kind"] == "batch"
    assert row["language"] == "python"
    assert row["context"]["source_job_id"] == integration.store.parent_id
    assert row["context"]["result_kind"] == "export"
    assert row["process"]["process_graph"]["gee_result"]["arguments"] == {
        "data": {"from_node": "gee_table"}, "format": "CSV",
    }
    data, selected = validate_table_graph(row["process"]["process_graph"])
    assert selected == ["predicted", "note", "system:index", "nested", "nullable", ".geo"]
    graph.validate(row["process"]["process_graph"])
    assert collection_loads(row["process"]["process_graph"]) == {}
    assert materialize(row["process"]["process_graph"], {}, str(integration.root / "unused")) == row["process"]["process_graph"]

    # Retry the captured official task request. It must reuse the child job;
    # changing its contents under the same id must fail without another row.
    export_request = next(call for call in integration.requests if call["action"] == "export_table")
    retry = ee_service.dispatch(integration.backend, integration.account, export_request)
    assert retry["job_id"] == job_id
    assert integration.backend.batch_jobs.create_calls == 1
    changed = json.loads(json.dumps(export_request))
    changed["options"]["fileNamePrefix"] = "different-content"
    from openeo_driver.errors import OpenEOApiException
    with pytest.raises(OpenEOApiException):
        ee_service.dispatch(integration.backend, integration.account, changed)
    assert integration.backend.batch_jobs.create_calls == 1

    run = run_batch(integration, job_id)
    row = run.row
    physical = integration.root / "jobs" / job_id
    assert run.job_dir == physical
    assert (physical / "graph.json").is_file()
    assert list(physical.glob("catalog-*.json")) == []
    assert not (physical / "out" / "openEO.csv").exists()
    assert (physical / "out" / "分类,结果.csv").is_file()
    assert run.container.removed
    assert row["status"] == "finished"
    assert row["assets"] == {"分类,结果.csv": {
        "type": "text/csv", "roles": ["data"],
        "file:size": (physical / "out" / "分类,结果.csv").stat().st_size,
    }}

    # The independent fixture gives the trained class means and held-out
    # labels; a separate distance calculation checks predictions in the CSV.
    means = {
        label: tuple(sum(item[name] for item in fixture["training"]
                         if item["landcover"] == label) / sum(
                             item["landcover"] == label for item in fixture["training"])
                     for name in fixture["input_properties"])
        for label in (1, 3)
    }
    validation = fixture["validation"]
    expected = [min(means, key=lambda label: sum(
        (sample[name] - means[label][i]) ** 2
        for i, name in enumerate(fixture["input_properties"]))) for sample in validation]
    assert expected == fixture["predictions"]

    from gee.backend import Jobs
    reader = Jobs()
    assets = reader.get_result_assets(job_id, USER)
    csv_path = Path(assets["分类,结果.csv"]["href"])
    assert csv_path == physical / "out" / "分类,结果.csv"
    from openeo_driver.errors import JobNotFoundException
    with pytest.raises(JobNotFoundException):
        reader.get_result_assets(job_id, "another-synthetic-user")
    with csv_path.open(encoding="utf-8", newline="") as stream:
        records = list(csv.DictReader(stream))
    assert list(records[0]) == selected
    assert [int(record["predicted"]) for record in records] == expected
    assert [record["system:index"] for record in records] == [
        f"validation-{i}" for i in range(len(expected))
    ]
    assert records[0]["note"] == '城市, "甲"\n第二行'
    assert json.loads(records[0]["nested"]) == {"标签": "样本", "values": [0, None]}
    assert records[0]["nullable"] == ""
    assert records[1]["nullable"] == ""
    assert json.loads(records[0][".geo"]) == {
        "type": "Point", "coordinates": [100, 30],
    }
    assert task.status()["state"] == ee.batch.Task.State.COMPLETED
    assert {item.id for item in ee.batch.Task.list()} == {job_id}
    assert ee.batch.Task.list()[0].task_type == ee.batch.Task.Type.EXPORT_TABLE


def test_table_rejections_do_not_enqueue_and_sibling_script_cannot_read_or_cancel(integration, monkeypatch):
    ee = integration.ee
    collection = _prediction_collection(ee, json.loads(
        (ROOT / "tests/fixtures/ee-minimum-distance-v1.json").read_text()))
    expression = ee.serializer.encode(collection, for_cloud_api=False)
    account = integration.account

    invalid = [
        {"action": "export_table", "expression": expression,
         "options": {"fileFormat": "GeoJSON"}},
        {"action": "export_table", "expression": expression,
         "options": {"selectors": ["not-a-column"]}},
        {"action": "export_table",
         "expression": ee.serializer.encode(ee.Number(7), for_cloud_api=False),
         "options": {}},
    ]
    for request in invalid:
        with pytest.raises((ValueError, TypeError, UnsupportedEEError)):
            ee_service.dispatch(integration.backend, account, request)
    assert integration.backend.batch_jobs.create_calls == 0

    def mixed_graph(data, columns):
        return {
            "table": {"process_id": TABLE_PROCESS,
                      "arguments": {"data": data, "columns": columns}, "result": True},
            "other": {"process_id": "add", "arguments": {"x": 1}},
        }

    with monkeypatch.context() as patcher:
        patcher.setattr(ee_service, "table_input_graph", mixed_graph)
        with pytest.raises(ValueError, match="exactly an input|one input"):
            ee_service.dispatch(integration.backend, account, {
                "action": "export_table", "expression": expression,
                "request_id": "mixed-graph-request", "options": {},
            })
    assert integration.backend.batch_jobs.create_calls == 0

    # Create an export through the official SDK, then prove the sibling script
    # sees the same-user child as not found and cannot change its state.
    task = _drive_task(ee, collection, description="scoped task", prefix="scoped")
    task.start()
    job_id = task.id
    before = integration.store.job(job_id, USER)["status"]
    sibling_account = {"user_id": USER, "scope": "script",
                       "job_id": integration.store.sibling_id}
    from openeo_driver.errors import JobNotFoundException
    for action in ("status", "cancel"):
        with pytest.raises(JobNotFoundException):
            ee_service.dispatch(integration.backend, sibling_account,
                                {"action": action, "job_id": job_id})
    assert integration.store.job(job_id, USER)["status"] == before == "queued"

    task.cancel()
    assert task.status()["state"] == ee.batch.Task.State.CANCELLED
    listed = ee.batch.Task.list()
    assert any(item.id == job_id for item in listed)
    assert integration.store.job(job_id, USER)["status"] == "canceled"
