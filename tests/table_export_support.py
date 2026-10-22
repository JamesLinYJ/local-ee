"""Reusable trusted fixture boundary for inline EE table integration tests."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import uuid
from types import SimpleNamespace

from gee.ee_python_client import configure_local_ee
from gee.services import ee as ee_service


USER = "synthetic-table-user"
URL = "http://127.0.0.1:8787/openeo/1.2"
ROOT = Path(__file__).resolve().parents[1]


class MemoryStore:
    """Minimal database semantics used by dispatch and worker lifecycle."""

    def __init__(self):
        self.parent_id = str(uuid.uuid4())
        self.sibling_id = str(uuid.uuid4())
        self.parents = {
            self.parent_id: self._parent(self.parent_id),
            self.sibling_id: self._parent(self.sibling_id),
        }
        self.rows = {}

    @staticmethod
    def _parent(parent_id):
        return {"id": parent_id, "user_id": USER, "kind": "script",
                "language": "python", "status": "running"}

    def job(self, job_id, user_id):
        from openeo_driver.errors import JobNotFoundException

        row = self.rows.get(str(job_id))
        if row is None or row["user_id"] != user_id:
            raise JobNotFoundException(str(job_id))
        return row

    def query(self, sql, args=(), one=False):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT id,language,status FROM jobs"):
            parent_id, user_id = map(str, args)
            parent = self.parents.get(parent_id)
            return parent if parent and parent["user_id"] == user_id else None
        if normalized.startswith("SELECT id,title,status,error,context,process FROM jobs"):
            user_id, parent_id = args
            rows = [row for row in self.rows.values()
                    if row["user_id"] == user_id
                    and row["context"].get("protocol") == "earthengine"
                    and row["context"].get("source_job_id") == str(parent_id)
                    and row["context"].get("result_kind") == "export"]
            rows.sort(key=lambda row: row["created"], reverse=True)
            return rows[:100]
        if normalized.startswith("UPDATE jobs SET status=%s,error=%s,logs=%s,assets=%s"):
            status, error, logs, assets, job_id = args
            row = self.rows.get(str(job_id))
            if row and row["status"] == "running":
                row.update(status=status, error=error, logs=logs,
                           assets=getattr(assets, "obj", assets))
            return None
        if normalized.startswith("DELETE FROM tokens"):
            return None
        raise AssertionError(f"Unexpected database operation in fixture: {normalized}")


class MemoryBatchJobs:
    """Queue state only; tests drive real worker and engine entry points."""

    def __init__(self, store):
        self.store = store
        self.start_calls = []
        self.create_calls = 0

    def create_job(self, *, user, process, api_version, metadata, job_options=None):
        from openeo_driver.errors import OpenEOApiException

        assert api_version == "1.2" and job_options is None
        internal = user.internal_auth_data
        context = dict(internal["ee_task_context"])
        context.update(internal.get("ee_idempotency", {}))
        idem = internal.get("ee_idempotency")
        if idem:
            for row in self.store.rows.values():
                if (row["user_id"] == user.user_id
                        and row["context"].get("request_id_hash") == idem["request_id_hash"]
                        and row["context"].get("source_job_id") == context["source_job_id"]):
                    if row["context"].get("request_fingerprint") != idem["request_fingerprint"]:
                        raise OpenEOApiException(
                            "EE task request ID was reused with different export contents",
                            code="IdempotencyConflict", status_code=409)
                    return SimpleNamespace(id=row["id"])
        job_id = str(uuid.uuid4())
        self.create_calls += 1
        self.store.rows[job_id] = {
            "id": job_id, "user_id": user.user_id, "kind": "batch",
            "title": metadata["title"], "status": "created", "error": None,
            "process": json.loads(json.dumps(process)), "snapshot": {},
            "context": context, "language": internal["ee_task_language"],
            "assets": {}, "logs": "", "created": self.create_calls,
        }
        return SimpleNamespace(id=job_id)

    def start_job(self, job_id, user):
        self.store.job(job_id, user.user_id)["status"] = "queued"
        self.start_calls.append(str(job_id))

    def cancel_job(self, job_id, user_id):
        self.store.job(job_id, user_id)["status"] = "canceled"


class MemoryBackend:
    def __init__(self, store):
        self.batch_jobs = MemoryBatchJobs(store)


class FinishedTask:
    """Successful worker-finish input; no native supervisor is launched."""

    attrs = {"State": {"ExitCode": 0, "OOMKilled": False}, "Config": {"Env": []}}

    def logs(self, tail=2000):
        return b""

    def remove(self):
        self.removed = True


def install(monkeypatch, root: Path):
    """Install a trusted in-memory fixture around real dispatch and CSV execution.

    Call inside ``OfflineGuard`` so ordinary transport/socket/DNS entry points
    remain denied. Only database/queue storage and NativeTask launch are faked.
    """
    import ee
    import gee.ee_python_tasks as ee_tasks
    import gee.worker as worker
    import gee.backend as backend_module

    ee.Reset()
    for name in ("_local_ee_runtime", "Map"):
        if hasattr(ee, name):
            delattr(ee, name)
    if hasattr(ee.data, "_local_ee_tasks_installed"):
        del ee.data._local_ee_tasks_installed
    importlib.reload(ee.data)
    importlib.reload(ee.oauth)
    importlib.reload(ee)

    store = MemoryStore()
    backend = MemoryBackend(store)
    account = {"user_id": USER, "scope": "script", "job_id": store.parent_id}
    requests = []
    monkeypatch.setattr(ee_service, "catalog_snapshot", lambda: ([], {}))
    monkeypatch.setattr(ee_service.db, "query", store.query)
    monkeypatch.setattr(ee_service.db, "job", store.job)
    monkeypatch.setattr(worker, "ROOT", root)
    monkeypatch.setattr(backend_module, "DATA", root)

    def dispatch(payload):
        requests.append(json.loads(json.dumps(payload)))
        return ee_service.dispatch(backend, account, payload)

    official_install_tasks = ee_tasks.install_tasks

    def install_with_local_dispatch(module, _transport_send, encode):
        official_install_tasks(module, dispatch, encode)

    monkeypatch.setattr(ee_tasks, "install_tasks", install_with_local_dispatch)
    configured_ee = configure_local_ee(
        URL, "a" * 48, signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")

    def evaluate(value):
        response = dispatch({
            "action": "evaluate",
            "expression": configured_ee.serializer.encode(value, for_cloud_api=False),
        })
        if "value" not in response:
            raise ValueError("Synthetic local evaluation returned no value")
        return response["value"]

    monkeypatch.setattr(configured_ee.data, "computeValue", evaluate)
    return SimpleNamespace(root=root, store=store, backend=backend,
                           account=account, requests=requests, ee=configured_ee,
                           worker=worker, dispatch=dispatch)


def run_batch(fixture, job_id):
    """Run the real prepare, pure-CSV engine branch and finish lifecycle."""
    from engine.native_run import run as native_run

    row = fixture.store.job(job_id, fixture.account["user_id"])
    job_dir = fixture.worker.prepare(row)
    row["status"] = "running"  # represent queue claim; no NativeTask is launched
    container = FinishedTask()
    previous_umask = os.umask(0)
    os.umask(previous_umask)
    try:
        native_run(job_dir)
    finally:
        os.umask(previous_umask)
    fixture.worker.finish(row, container)
    return SimpleNamespace(row=row, job_dir=job_dir, container=container)
