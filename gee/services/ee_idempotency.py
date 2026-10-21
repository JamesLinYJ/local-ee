"""Stable request keys for retryable official EE export tasks."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def validate_request_id(value: Any) -> str:
    if not isinstance(value, str) or not _REQUEST_ID.fullmatch(value):
        raise ValueError("request_id must be 1..128 letters, digits, '_' or '-'")
    return value


def idempotency_record(
    request_id: str | None,
    request: dict[str, Any],
) -> dict[str, str] | None:
    if request_id is None:
        return None
    request_id = validate_request_id(request_id)
    try:
        canonical = json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("EE export request cannot be fingerprinted") from error
    return {
        "request_id_hash": hashlib.sha256(request_id.encode("utf-8")).hexdigest(),
        "request_fingerprint": hashlib.sha256(canonical).hexdigest(),
    }
