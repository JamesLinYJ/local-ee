"""SDK/compiler and actual JSON/CSV task publication; RF/JVM tested separately.

Database/queue and worker input values are explicit fixtures. No native task,
model fitting, Spark, browser or Google service is exercised by these tests.
"""
import json

import pytest
from openeo_driver.errors import JobNotFoundException

from engine.ee_json_result import RuntimeFeatureTable, RuntimeJsonResult
from gee import graph
from gee.services import ee as service
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import FinishedTask, USER, install


@pytest.fixture
def integration(tmp_path, monkeypatch):
    with OfflineGuard() as guard:
        fixture = install(monkeypatch, tmp_path)
        monkeypatch.setattr(service, "DATA", tmp_path)
        yield fixture
    assert guard.evidence()["attempt_count"] == 0


def expression(fixture, table=False):
    ee = fixture.ee
    training = ee.FeatureCollection([
        ee.Feature(None, {"x": 0, "truth": 0}),
        ee.Feature(None, {"x": 1, "truth": 0}),
        ee.Feature(None, {"x": 9, "truth": 1}),
        ee.Feature(None, {"x": 10, "truth": 1}),
    ])
    model = ee.Classifier.smileRandomForest(3).train(training, "truth", ["x"])
    predictions = training.classify(model)
    value = predictions if table else predictions.errorMatrix("truth", "classification", [0, 1]).accuracy()
    return ee.serializer.encode(value, for_cloud_api=False)


def finish(fixture, row, table=False, invalid_json=False):
    folder = fixture.root / "jobs" / row["id"] / "out"
    folder.mkdir(parents=True)
    value = 0.75
    if table:
        value = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": None, "id": "fixture-id",
            "properties": {"x": 0, "truth": 0, "classification": 0},
        }]}
        result = RuntimeFeatureTable(value, row["context"]["bands"])
    else:
        result = RuntimeJsonResult(value)
    sink = next(node for node in row["process"]["process_graph"].values() if node.get("result"))
    result.format = sink["arguments"]["format"]
    result.write_assets(folder / "out")
    if invalid_json:
        (folder / "openEO.json").write_text('{"unexpected":"object"}')
    row["status"] = "running"
    fixture.worker.finish(row, FinishedTask())
    return value


@pytest.mark.parametrize("table", [False, True])
def test_runtime_getinfo_creates_json_task_and_authorized_readback(integration, table):
    fixture = integration
    result = fixture.dispatch({"action": "evaluate", "expression": expression(fixture, table)})
    row = fixture.store.job(result["job_id"], USER)
    assert result["pending"] is True and row["status"] == "queued"
    assert row["context"]["result_kind"] == "runtime_json"
    assert row["context"]["source_job_id"] == fixture.store.parent_id
    assert fixture.dispatch({"action": "result", "job_id": row["id"]})["pending"] is True
    graph.validate(row["process"]["process_graph"])
    value = finish(fixture, row, table)
    assert row["status"] == "finished", row["error"]
    assert row["assets"]["openEO.json"]["type"] == "application/json"
    assert fixture.dispatch({"action": "result", "job_id": row["id"]})["value"] == value
    sibling = {**fixture.account, "job_id": fixture.store.sibling_id}
    for action in ("result", "status", "cancel"):
        with pytest.raises(JobNotFoundException):
            service.dispatch(fixture.backend, sibling, {"action": action, "job_id": row["id"]})
    with pytest.raises(JobNotFoundException):
        service.dispatch(fixture.backend, {"user_id": "other", "scope": "session"},
                         {"action": "result", "job_id": row["id"]})


def test_runtime_table_csv_export_uses_existing_selectors_and_publication(integration):
    fixture = integration
    result = fixture.dispatch({"action": "export_table", "expression": expression(fixture, True),
                              "options": {"selectors": ["classification", "x"],
                                          "fileNamePrefix": "验证", "fileFormat": "CSV"}})
    row = fixture.store.job(result["job_id"], USER)
    assert row["status"] == "created"
    fixture.dispatch({"action": "start", "job_id": row["id"]})
    finish(fixture, row, True)
    assert row["status"] == "finished", row["error"]
    assert set(row["assets"]) == {"验证.csv"}
    assert (fixture.root / "jobs" / row["id"] / "out" / "验证.csv").read_text().splitlines() == ["classification,x", "0,0"]


def test_worker_refuses_invalid_runtime_json_before_publishing(integration):
    fixture = integration
    result = fixture.dispatch({"action": "evaluate", "expression": expression(fixture)})
    row = fixture.store.job(result["job_id"], USER)
    finish(fixture, row, invalid_json=True)
    assert row["status"] == "error" and row["assets"] == {}
    with pytest.raises(ValueError):
        fixture.dispatch({"action": "result", "job_id": row["id"]})


def test_unrelated_batch_cannot_publish_json_and_wrong_actions_do_not_enqueue(integration):
    fixture = integration
    encoded = expression(fixture, True)
    for action in ("map", "export_image"):
        with pytest.raises(ValueError):
            fixture.dispatch({"action": action, "expression": encoded})
    assert fixture.backend.batch_jobs.create_calls == 0
    result = fixture.dispatch({"action": "evaluate", "expression": expression(fixture)})
    row = fixture.store.job(result["job_id"], USER)
    row["context"]["result_kind"] = "unrelated"
    finish(fixture, row)
    assert row["status"] == "error" and row["assets"] == {}
