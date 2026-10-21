"""Bounded map-event storage for script-scoped Earth Engine sessions."""

import json

from psycopg.types.json import Jsonb

from .. import db

MAX_EVENTS = 32
MAX_EVENT_BYTES = 65536
SCRIPT_LANGUAGES = {"javascript", "python"}


def _locked_parent(connection, account):
    job_id = account.get("job_id")
    if not job_id:
        raise ValueError("Script token is not bound to a running parent job")
    row = connection.execute(
        "SELECT events,language FROM jobs WHERE id::text=%s AND user_id=%s "
        "AND kind='script' AND status='running' FOR UPDATE",
        (str(job_id), account["user_id"]),
    ).fetchone()
    if not row or row["language"] not in SCRIPT_LANGUAGES:
        raise ValueError("Script parent job is no longer running")
    return row


def _validate_script_account(account):
    if not account.get("job_id"):
        raise ValueError("Script token is not bound to a running parent job")


def _check_capacity(events, event):
    if len(events) >= MAX_EVENTS or len(json.dumps(events)) + len(json.dumps(event)) > MAX_EVENT_BYTES:
        raise ValueError("Script map/event budget exceeded")


def check_event_capacity(account, event):
    """Preflight the bounded event budget before creating a map child task."""
    if account.get("scope") != "script":
        return
    _validate_script_account(account)
    with db.connect() as connection:
        row = _locked_parent(connection, account)
        _check_capacity(row["events"], event)


def record_event(account, event):
    if account.get("scope") != "script":
        return
    _validate_script_account(account)
    with db.connect() as connection:
        row = _locked_parent(connection, account)
        events = row["events"]
        _check_capacity(events, event)
        connection.execute(
            "UPDATE jobs SET events=%s,updated=now() WHERE id::text=%s",
            (Jsonb([*events, event]), str(account["job_id"])),
        )
