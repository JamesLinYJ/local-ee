"""Owned explanation publication and permissions; storage/queue are fixtures.

These tests run real dispatch, JSON writer, worker finish and result validation.
They do not start a service, fit a model or execute unconfined user code.
"""
import json

import pytest
from openeo_driver.errors import JobNotFoundException

from engine.ee_explanation_result import RuntimeRFExplanationResult
from engine.ee_json_result import RuntimeJsonResult
from gee.services import ee as service
from gee.services import ee_runtime_results as results
from gee.services.ee_explanation_limits import preflight_explanation
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import FinishedTask, USER, install


VALUE = {"importance": {"x": 1.5}, "numberOfTrees": 3,
         "outOfBagErrorEstimate": 0.0}


@pytest.fixture
def integration(tmp_path, monkeypatch):
    with OfflineGuard() as guard:
        fixture = install(monkeypatch, tmp_path)
        monkeypatch.setattr(service, "DATA", tmp_path)
        yield fixture
    assert guard.evidence()["attempt_count"] == 0


def expression(fixture):
    ee = fixture.ee
    training = ee.FeatureCollection([
        ee.Feature(None, {"x": 0, "truth": 0}),
        ee.Feature(None, {"x": 1, "truth": 0}),
        ee.Feature(None, {"x": 9, "truth": 1}),
        ee.Feature(None, {"x": 10, "truth": 1}),
    ])
    model = ee.Classifier.smileRandomForest(3).train(training, "truth", ["x"])
    return ee.serializer.encode(model.explain(), for_cloud_api=False)


def enqueue(fixture):
    response = fixture.dispatch({"action": "evaluate", "expression": expression(fixture)})
    return fixture.store.job(response["job_id"], USER)


def finish(fixture, row, payload=None):
    folder = fixture.root / "jobs" / row["id"] / "out"
    folder.mkdir(parents=True)
    result = RuntimeRFExplanationResult(VALUE, row["context"]["explanation_spec"])
    result.write_assets(folder / "out")
    path = folder / "openEO.json"
    if payload is not None:
        path.write_bytes(payload)
    row["status"] = "running"
    fixture.worker.finish(row, FinishedTask())
    return path


def test_getinfo_context_owned_writer_readback_and_permissions(integration):
    fixture = integration
    row = enqueue(fixture)
    assert row["status"] == "queued"
    assert row["context"]["runtime_json_type"] == "runtime_explanation"
    assert row["context"]["source_job_id"] == fixture.store.parent_id
    assert json.loads(row["context"]["explanation_spec"])["schema"] == ["x"]
    assert fixture.dispatch({"action": "result", "job_id": row["id"]})["pending"]
    finish(fixture, row)
    assert row["status"] == "finished", row["error"]
    assert set(row["assets"]) == {"openEO.json"}
    assert fixture.dispatch({"action": "result", "job_id": row["id"]})["value"] == VALUE
    sibling = {**fixture.account, "job_id": fixture.store.sibling_id}
    for account in (sibling, {"user_id": "other", "scope": "session"}):
        for action in ("result", "status", "cancel"):
            with pytest.raises(JobNotFoundException):
                service.dispatch(fixture.backend, account,
                                 {"action": action, "job_id": row["id"]})


@pytest.mark.parametrize("payload", [
    b'{"unexpected":1}',
    b'{"importance":{"x":1},"numberOfTrees":2,"outOfBagErrorEstimate":0}',
    b'{"importance":{"x":1,"x":2},"numberOfTrees":3,"outOfBagErrorEstimate":0}',
    b'{"importance":{"x":NaN},"numberOfTrees":3,"outOfBagErrorEstimate":0}',
    b'{"importance":{"y":1},"numberOfTrees":3,"outOfBagErrorEstimate":0}',
])
def test_worker_refuses_wrong_shape_duplicate_nonfinite_or_spec(integration, payload):
    fixture = integration
    row = enqueue(fixture)
    finish(fixture, row, payload)
    assert row["status"] == "error" and row["assets"] == {}


@pytest.mark.parametrize("context_key,context_value", [
    ("result_kind", "unrelated"),
    ("runtime_json_type", "runtime_value"),
    ("explanation_spec", "{}"),
])
def test_wrong_trusted_context_cannot_publish_dictionary(integration, context_key, context_value):
    fixture = integration
    row = enqueue(fixture)
    original_spec = row["context"]["explanation_spec"]
    folder = fixture.root / "jobs" / row["id"] / "out"
    folder.mkdir(parents=True)
    RuntimeRFExplanationResult(VALUE, original_spec).write_assets(folder / "out")
    row["context"][context_key] = context_value
    row["status"] = "running"
    fixture.worker.finish(row, FinishedTask())
    assert row["status"] == "error" and row["assets"] == {}


def test_existing_numeric_result_boundary_stays_closed():
    with pytest.raises(ValueError):
        RuntimeJsonResult(VALUE)


@pytest.mark.parametrize("action", ["map", "export_image", "export_table"])
def test_explanation_is_getinfo_json_only(integration, action):
    fixture = integration
    with pytest.raises(ValueError):
        fixture.dispatch({"action": action, "expression": expression(fixture)})
    assert fixture.backend.batch_jobs.create_calls == 0


def test_physical_result_file_cannot_be_replaced_with_symlink(integration):
    fixture = integration
    row = enqueue(fixture)
    path = finish(fixture, row)
    target = fixture.root / "unrelated.json"
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(ValueError):
        fixture.dispatch({"action": "result", "job_id": row["id"]})


@pytest.mark.parametrize("payload", [b"[" * 33 + b"0" + b"]" * 33,
                                     b"[" + b"0," * 8192 + b"0]"])
def test_payload_structure_rejects_before_json_parse(integration, monkeypatch, payload):
    fixture = integration
    row = enqueue(fixture)
    path = finish(fixture, row)
    path.write_bytes(payload)
    original = json.loads
    parsed_payload = []

    def checked_loads(text, *args, **kwargs):
        if text == payload.decode():
            parsed_payload.append(True)
            raise AssertionError("Oversized result was parsed before structural preflight")
        return original(text, *args, **kwargs)

    monkeypatch.setattr(results.json, "loads", checked_loads)
    with pytest.raises(ValueError, match="bounded structure"):
        results.read_result(fixture.root, row)
    assert not parsed_payload


def test_preflight_counts_quoted_punctuation_as_text(integration):
    row = enqueue(integration)
    spec = row["context"]["explanation_spec"]
    payload = json.dumps("[{:" * 9000 + '\\"').encode()
    assert preflight_explanation(spec, payload)["view"] == "explanation"
    with pytest.raises(ValueError):
        preflight_explanation(spec, b"x" * 1_000_001)
    with pytest.raises(ValueError):
        preflight_explanation("x" * 16_385)
