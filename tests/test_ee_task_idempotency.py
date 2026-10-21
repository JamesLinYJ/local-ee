"""Stable retry behavior for official EE export request IDs."""

from datetime import datetime, timezone
from types import SimpleNamespace

import psycopg
import pytest
from openeo_driver.errors import OpenEOApiException
from openeo_driver.users import User

from gee import backend
from gee.migrations import EE_IDEMPOTENCY_SCHEMA, migrations
from gee.services.ee_idempotency import idempotency_record, validate_request_id


PARENT = "00000000-0000-0000-0000-000000000001"
TASK = "00000000-0000-0000-0000-000000000002"


def record(expression=None, fmt="GTiff", context=None):
    return idempotency_record(
        "sdk-request-1",
        {
            "action": "export_image",
            "expression": expression or {"result": {"process_id": "constant", "result": True}},
            "options": {
                "fileFormat": fmt,
                "description": "export description",
                "context": context or {"result_kind": "export"},
            },
        },
    )


def test_request_id_fingerprint_is_stable_and_covers_export_semantics():
    original = record()
    assert original == record()
    assert original["request_id_hash"] != "sdk-request-1"
    assert record(fmt="CSV")["request_fingerprint"] != original["request_fingerprint"]
    assert record(context={"result_kind": "export", "file_prefix": "other"})["request_fingerprint"] != original["request_fingerprint"]
    assert record(expression={"other": {"process_id": "constant"}})["request_fingerprint"] != original["request_fingerprint"]


def test_fingerprint_uses_client_request_not_catalog_derived_graph():
    request = {
        "action": "export_image",
        "expression": {"image": {"process_id": "load_collection", "arguments": {"id": "S2"}}},
        "options": {"scale": 20, "fileFormat": "GeoTIFF"},
    }
    first = idempotency_record("sdk-request-1", request)
    later_compilation = {"different_cached_catalog_graph": {"item": "new snapshot"}}
    retry = idempotency_record("sdk-request-1", request)
    assert later_compilation != request["expression"]
    assert retry == first


@pytest.mark.parametrize("value", [None, "", "two words", "../bad", "a" * 129, "id.2"])
def test_request_id_rejects_unbounded_or_pathlike_values(value):
    with pytest.raises(ValueError):
        validate_request_id(value)


def test_idempotency_requires_server_scoped_script_parent():
    with pytest.raises(OpenEOApiException) as caught:
        backend._ee_idempotency({"scope": "user", "ee_idempotency": record()}, None)
    assert caught.value.code == "IdempotencyInvalid"


def test_additive_migration_adds_parent_scoped_partial_unique_index():
    assert migrations()[-1] == (4, "ee_task_idempotency", EE_IDEMPOTENCY_SCHEMA)
    assert "CREATE UNIQUE INDEX IF NOT EXISTS jobs_ee_request_id_unique" in EE_IDEMPOTENCY_SCHEMA
    assert "COALESCE(context->>'source_job_id','')" in EE_IDEMPOTENCY_SCHEMA
    assert "context->>'request_id_hash'" in EE_IDEMPOTENCY_SCHEMA
    assert "WHERE context->>'protocol'='earthengine'" in EE_IDEMPOTENCY_SCHEMA


class Cursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def __iter__(self):
        return iter(self.rows)


class MemoryDatabase:
    """Small SQL boundary model for sequential dedupe and unique-collision readback."""

    def __init__(self, hide_request_lookup=False, conflict_on_insert=False, parent_language="python"):
        self.jobs = []
        self.hide_request_lookup = hide_request_lookup
        self.conflict_on_insert = conflict_on_insert
        self.parent_language = parent_language
        self.inserted = 0

    def query(self, sql, params=(), one=False):
        assert "request_id_hash" in sql
        user_id, request_hash, parent_id = params
        rows = [
            row for row in self.jobs
            if row["user_id"] == user_id
            and row["context"].get("request_id_hash") == request_hash
            and row["context"].get("source_job_id") == parent_id
        ]
        return (rows[0] if rows else None) if one else rows

    def connect(self):
        return MemoryConnection(self)


class ExpectedUniqueViolation(psycopg.errors.UniqueViolation):
    @property
    def diag(self):
        return SimpleNamespace(constraint_name=backend.EE_REQUEST_INDEX)


class MemoryConnection:
    def __init__(self, database):
        self.database = database

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        if sql.startswith("SET TRANSACTION"):
            return Cursor()
        if sql.startswith("SELECT id FROM users"):
            return Cursor({"id": "researcher"})
        if "SELECT id,language FROM jobs WHERE id::text" in sql:
            return Cursor({"id": PARENT, "language": self.database.parent_language})
        if "SELECT * FROM jobs WHERE user_id" in sql and "request_id_hash" in sql:
            if self.database.hide_request_lookup:
                return Cursor()
            user_id, request_hash, parent_id = params
            rows = [row for row in self.database.jobs if
                    row["user_id"] == user_id
                    and row["context"].get("request_id_hash") == request_hash
                    and row["context"].get("source_job_id") == parent_id]
            return Cursor(rows[0] if rows else None)
        if "SELECT count(*) AS n FROM jobs" in sql:
            return Cursor({"n": 0})
        if sql.startswith("INSERT INTO jobs"):
            if self.database.conflict_on_insert:
                raise ExpectedUniqueViolation("request id already exists")
            job_id, user_id, title, process, _snapshot, context, language = params
            now = datetime.now(timezone.utc)
            row = {
                "id": job_id,
                "user_id": user_id,
                "kind": "batch",
                "title": title,
                "status": "created",
                "process": process.obj,
                "snapshot": {},
                "context": context.obj,
                "language": language,
                "created": now,
                "updated": now,
                "started": None,
                "finished": None,
            }
            self.database.jobs.append(row)
            self.database.inserted += 1
            return Cursor()
        raise AssertionError(f"Unexpected SQL in fake database: {sql}")


def create_task(jobs, idempotency, task_context=None, task_language="python"):
    return jobs.create_job(
        user=User("researcher", internal_auth_data={
            "scope": "script", "job_id": PARENT, "ee_idempotency": idempotency,
            "ee_task_context": task_context or {
                "protocol": "earthengine", "source_job_id": PARENT,
                "result_kind": "export", "bands": ["B1"], "pixel_budget": 100,
            },
            "ee_task_language": task_language,
        }),
        process={"process_graph": {}},
        api_version="1.2",
        metadata={"title": "export description"},
    )


def test_jobs_create_job_returns_existing_task_for_same_request(monkeypatch):
    database = MemoryDatabase()
    monkeypatch.setattr(backend.db, "connect", database.connect)
    monkeypatch.setattr(backend.db, "query", database.query)
    monkeypatch.setattr(backend.db, "job", lambda job_id, _user_id: next(row for row in database.jobs if row["id"] == job_id))
    monkeypatch.setattr(backend.graph, "validate", lambda _graph: None)
    jobs = backend.Jobs()
    first = create_task(jobs, record())
    second = create_task(jobs, record())
    assert str(first.id) == str(second.id)
    assert len(database.jobs) == 1
    assert database.inserted == 1
    assert database.jobs[0]["language"] == "python"


def test_retry_does_not_overwrite_original_compiled_context(monkeypatch):
    database = MemoryDatabase()
    monkeypatch.setattr(backend.db, "connect", database.connect)
    monkeypatch.setattr(backend.db, "query", database.query)
    monkeypatch.setattr(backend.db, "job", lambda job_id, _user_id: next(row for row in database.jobs if row["id"] == job_id))
    monkeypatch.setattr(backend.graph, "validate", lambda _graph: None)
    jobs = backend.Jobs()
    first_context = {
        "protocol": "earthengine", "source_job_id": PARENT, "result_kind": "export",
        "bands": ["B1"], "pixel_budget": 100,
    }
    changed_catalog_context = {
        "protocol": "earthengine", "source_job_id": PARENT, "result_kind": "export",
        "bands": ["B1", "B2"], "pixel_budget": 200,
    }
    create_task(jobs, record(), first_context)
    result = create_task(jobs, record(), changed_catalog_context)
    assert len(database.jobs) == 1
    assert database.inserted == 1
    assert result.id == database.jobs[0]["id"]
    assert database.jobs[0]["context"] == first_context | record()


def test_jobs_insert_script_language_from_verified_parent(monkeypatch):
    database = MemoryDatabase(parent_language="javascript")
    monkeypatch.setattr(backend.db, "connect", database.connect)
    monkeypatch.setattr(backend.db, "query", database.query)
    monkeypatch.setattr(backend.db, "job", lambda job_id, _user_id: next(row for row in database.jobs if row["id"] == job_id))
    monkeypatch.setattr(backend.graph, "validate", lambda _graph: None)
    create_task(backend.Jobs(), record(), task_language="javascript")
    assert database.jobs[0]["language"] == "javascript"


def test_jobs_create_job_rejects_request_id_with_changed_payload(monkeypatch):
    database = MemoryDatabase()
    monkeypatch.setattr(backend.db, "connect", database.connect)
    monkeypatch.setattr(backend.db, "query", database.query)
    monkeypatch.setattr(backend.db, "job", lambda job_id, _user_id: next(row for row in database.jobs if row["id"] == job_id))
    monkeypatch.setattr(backend.graph, "validate", lambda _graph: None)
    jobs = backend.Jobs()
    create_task(jobs, record())
    with pytest.raises(OpenEOApiException) as caught:
        create_task(jobs, record(fmt="CSV"))
    assert caught.value.code == "IdempotencyConflict"
    assert len(database.jobs) == 1


def test_unique_index_collision_returns_winning_job(monkeypatch):
    database = MemoryDatabase(hide_request_lookup=True)
    now = datetime.now(timezone.utc)
    idem = record()
    database.jobs.append({
        "id": TASK, "user_id": "researcher", "kind": "batch", "title": "export description",
        "status": "created", "process": {"process_graph": {}}, "snapshot": {},
        "context": {"protocol": "earthengine", "source_job_id": PARENT, **idem},
        "created": now, "updated": now, "started": None, "finished": None,
    })
    database.conflict_on_insert = True
    monkeypatch.setattr(backend.db, "connect", database.connect)
    monkeypatch.setattr(backend.db, "query", database.query)
    monkeypatch.setattr(backend.graph, "validate", lambda _graph: None)
    result = create_task(backend.Jobs(), idem)
    assert str(result.id) == TASK
