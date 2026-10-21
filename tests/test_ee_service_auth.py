"""Script-scoped EE task access and Python map-event persistence."""
from types import SimpleNamespace

import pytest
from openeo_driver.errors import JobNotFoundException

from gee.services import ee


PARENT = "00000000-0000-0000-0000-000000000001"
CHILD = "00000000-0000-0000-0000-000000000002"


class BatchJobs:
    def __init__(self, row=None):
        self.canceled = []
        self.started = []
        self.row = row

    def cancel_job(self, job_id, user_id):
        self.canceled.append((job_id, user_id))
        if self.row and self.row["status"] in {"created", "queued", "running"}:
            self.row["status"] = "canceled"

    def start_job(self, job_id, user):
        self.started.append((job_id, user.user_id))
        if self.row and self.row["status"] == "created":
            self.row["status"] = "queued"


def account(scope="script", job_id=PARENT):
    return {"user_id": "researcher", "scope": scope, "job_id": job_id}


def install_parent(monkeypatch, language="python", status="running"):
    monkeypatch.setattr(
        ee.db,
        "query",
        lambda *args, **kwargs: {"id": PARENT, "language": language, "status": status},
    )


def child(parent_id=PARENT):
    return {
        "id": CHILD,
        "title": "Local task",
        "status": "queued",
        "error": None,
        "assets": {},
        "context": {"protocol": "earthengine", "source_job_id": parent_id},
    }


@pytest.mark.parametrize("language", ["python", "javascript"])
def test_running_script_parent_can_record_local_map_events(monkeypatch, language):
    event = {"type": "map_clear"}
    updates = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, params):
            if statement.startswith("SELECT events"):
                assert params == (PARENT, "researcher")
                return SimpleNamespace(fetchone=lambda: {"events": [], "language": language})
            assert statement.startswith("UPDATE jobs SET events=")
            updates.append(params)
            return SimpleNamespace(fetchone=lambda: None)

    monkeypatch.setattr(ee.db, "connect", Connection)
    ee.record_event(account(), event)
    assert updates[0][0].obj == [event]
    assert updates[0][1] == PARENT


def test_map_events_ignore_user_scope_and_reject_unbound_script_scope(monkeypatch):
    def forbidden():
        raise AssertionError("unrelated user tokens must not write script events")

    monkeypatch.setattr(ee.db, "connect", forbidden)
    ee.record_event(account(scope="user", job_id=None), {"type": "map_clear"})
    with pytest.raises(ValueError, match="not bound"):
        ee.record_event(account(job_id=None), {"type": "map_clear"})


@pytest.mark.parametrize("language", ["python", "javascript"])
def test_ee_child_language_and_parent_are_inherited_from_db(monkeypatch, language):
    def query(sql, params=(), one=False):
        if "SELECT id,language,status FROM jobs" in sql:
            return {"id": PARENT, "language": language, "status": "running"}
        raise AssertionError(f"unexpected post-insert metadata update: {sql}")

    monkeypatch.setattr(ee.db, "query", query)
    monkeypatch.setattr(ee.graph, "validate", lambda _graph: None)

    class Jobs:
        def create_job(self, **kwargs):
            self.user = kwargs["user"]
            return SimpleNamespace(id=CHILD)

        def start_job(self, *_args):
            pass

    jobs = Jobs()
    backend = SimpleNamespace(batch_jobs=jobs)
    compiled = {"process_graph": {"value": {"process_id": "constant", "arguments": {}, "result": True}}, "bands": ["B1"]}
    ee.make_job(backend, account(), compiled, "Python EE", "GTiff", {"source_job_id": "forged"}, False,
                request_id="sdk-request-1", request_payload={"action": "export_image", "expression": {}, "options": {}})

    internal = jobs.user.internal_auth_data
    assert internal["scope"] == "script" and internal["job_id"] == PARENT
    assert len(internal["ee_idempotency"]["request_fingerprint"]) == 64
    assert internal["ee_task_language"] == language
    assert internal["ee_task_context"]["source_job_id"] == PARENT
    assert internal["ee_task_context"]["protocol"] == "earthengine"
    assert internal["ee_task_context"]["request_id_hash"] == internal["ee_idempotency"]["request_id_hash"]


def test_script_token_can_cancel_only_its_own_ee_child(monkeypatch):
    install_parent(monkeypatch)
    task = child()
    monkeypatch.setattr(ee.db, "job", lambda *_args: task)
    batch = BatchJobs(task)
    result = ee.dispatch(SimpleNamespace(batch_jobs=batch), account(), {"action": "cancel", "job_id": CHILD})
    assert result["value"]["state"] == "CANCELLED"
    assert result["value"]["description"] == "Local task"
    assert batch.canceled == [(CHILD, "researcher")]


def test_script_token_cannot_read_or_cancel_sibling_ee_child(monkeypatch):
    install_parent(monkeypatch)
    monkeypatch.setattr(ee.db, "job", lambda *_args: child(parent_id="another-parent"))
    batch = BatchJobs()
    with pytest.raises(JobNotFoundException):
        ee.dispatch(SimpleNamespace(batch_jobs=batch), account(), {"action": "cancel", "job_id": CHILD})
    assert batch.canceled == []


def test_cancel_readback_preserves_a_completed_task(monkeypatch):
    install_parent(monkeypatch)
    task = child()
    task["status"] = "finished"
    monkeypatch.setattr(ee.db, "job", lambda *_args: task)
    batch = BatchJobs(task)
    result = ee.dispatch(SimpleNamespace(batch_jobs=batch), account(), {"action": "cancel", "job_id": CHILD})
    assert result["value"]["state"] == "COMPLETED"
    assert task["status"] == "finished"


def test_start_readback_reports_current_state(monkeypatch):
    install_parent(monkeypatch)
    task = child()
    task["status"] = "running"
    monkeypatch.setattr(ee.db, "job", lambda *_args: task)
    batch = BatchJobs(task)
    result = ee.dispatch(SimpleNamespace(batch_jobs=batch), account(), {"action": "start", "job_id": CHILD})
    assert result["value"]["state"] == "RUNNING"


def test_task_list_returns_only_parent_scoped_local_operations(monkeypatch):
    operation = {**child(), "status": "error", "error": "bounded local failure"}

    def query(sql, params, one=False):
        if "SELECT id,language,status FROM jobs" in sql:
            return {"id": PARENT, "language": "python", "status": "running"}
        assert "context->>'source_job_id'=%s" in sql
        assert "LIMIT 100" in sql
        assert params == ("researcher", PARENT)
        return [operation]

    monkeypatch.setattr(ee.db, "query", query)
    result = ee.dispatch(SimpleNamespace(), account(), {"action": "list"})
    item = result["operations"][0]
    assert item["name"] == f"operations/{CHILD}"
    assert item["metadata"] == {
        "state": "FAILED",
        "description": "Local task",
        "type": "EXPORT_IMAGE",
    }
    assert item["done"] is True
    assert item["error"]["message"] == "bounded local failure"


def test_task_list_refuses_user_wide_enumeration():
    from gee.ee_translate import UnsupportedEEError

    with pytest.raises(UnsupportedEEError, match="script-scoped"):
        ee.dispatch(SimpleNamespace(), account(scope="user", job_id=None), {"action": "list"})


def test_map_zoom_persists_zoom_only_without_changing_center(monkeypatch):
    install_parent(monkeypatch)
    events = []
    monkeypatch.setattr(ee, "record_event", lambda _account, event: events.append(event))
    assert ee.dispatch(SimpleNamespace(), account(), {"action": "map_zoom", "options": {"zoom": 12}}) == {"value": True}
    assert events == [{"type": "map_view", "zoom": 12}]


@pytest.mark.parametrize("zoom", [True, -1, 23, float("inf"), "12"])
def test_map_zoom_rejects_invalid_values(monkeypatch, zoom):
    install_parent(monkeypatch)
    with pytest.raises(ValueError, match="zoom"):
        ee.dispatch(SimpleNamespace(), account(), {"action": "map_zoom", "options": {"zoom": zoom}})


def test_map_budget_preflight_prevents_child_creation(monkeypatch):
    install_parent(monkeypatch)
    monkeypatch.setattr(ee, "catalog_snapshot", lambda: ({}, []))
    monkeypatch.setattr(ee, "compile_expression", lambda *_args: {
        "kind": "image", "process_graph": {}, "bands": ["B1"], "has_time_dimension": False,
    })
    monkeypatch.setattr(ee, "pixel_budget", lambda *_args: 1)
    monkeypatch.setattr(ee, "check_event_capacity", lambda *_args: (_ for _ in ()).throw(ValueError("event budget")))
    monkeypatch.setattr(ee, "make_job", lambda *_args, **_kwargs: pytest.fail("must not create a child"))

    with pytest.raises(ValueError, match="event budget"):
        ee.dispatch(SimpleNamespace(), account(), {"action": "map", "expression": "image"})


def test_map_event_race_cancels_unstarted_child(monkeypatch):
    install_parent(monkeypatch)
    monkeypatch.setattr(ee, "catalog_snapshot", lambda: ({}, []))
    monkeypatch.setattr(ee, "compile_expression", lambda *_args: {
        "kind": "image", "process_graph": {}, "bands": ["B1"], "has_time_dimension": False,
    })
    monkeypatch.setattr(ee, "pixel_budget", lambda *_args: 1)
    monkeypatch.setattr(ee, "check_event_capacity", lambda *_args: None)
    starts = []
    cancels = []
    monkeypatch.setattr(ee, "make_job", lambda *args, **_kwargs: (starts.append(args[-1]) or {"job_id": CHILD, "warnings": []}))
    monkeypatch.setattr(ee, "record_event", lambda *_args: (_ for _ in ()).throw(ValueError("event budget")))
    backend = SimpleNamespace(batch_jobs=SimpleNamespace(
        start_job=lambda *_args: pytest.fail("must remain unstarted"),
        cancel_job=lambda *args: cancels.append(args),
    ))

    with pytest.raises(ValueError, match="event budget"):
        ee.dispatch(backend, account(), {"action": "map", "expression": "image"})
    assert starts == [False]
    assert cancels == [(CHILD, "researcher")]


def test_map_start_failure_keeps_event_index_and_cancels_child(monkeypatch):
    install_parent(monkeypatch)
    monkeypatch.setattr(ee, "catalog_snapshot", lambda: ({}, []))
    monkeypatch.setattr(ee, "compile_expression", lambda *_args: {
        "kind": "image", "process_graph": {}, "bands": ["B1"], "has_time_dimension": False,
    })
    monkeypatch.setattr(ee, "pixel_budget", lambda *_args: 1)
    monkeypatch.setattr(ee, "check_event_capacity", lambda *_args: None)
    events = []
    cancels = []
    monkeypatch.setattr(ee, "make_job", lambda *_args, **_kwargs: {"job_id": CHILD, "warnings": []})
    monkeypatch.setattr(ee, "record_event", lambda _account, event: events.append(event))
    def start(*_args):
        raise RuntimeError("scheduler unavailable")
    backend = SimpleNamespace(batch_jobs=SimpleNamespace(
        start_job=start,
        cancel_job=lambda *args: cancels.append(args),
    ))

    with pytest.raises(RuntimeError, match="scheduler unavailable"):
        ee.dispatch(backend, account(), {"action": "map", "expression": "image"})
    assert events[0]["job_id"] == CHILD
    assert cancels == [(CHILD, "researcher")]
