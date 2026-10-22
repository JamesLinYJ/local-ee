"""Bounded owned JSON readback for RF feature and matrix getInfo tasks."""
from __future__ import annotations

import json
import os
import stat

from ..artifacts import artifact_path
from ..sampling_values import render_sample_csv
from ..rf_validation_spec import validate_metric_value


MAX_BYTES = 1_000_000


def result_context(compiled):
    kind = compiled.get("kind")
    if kind not in {"runtime_table", "runtime_value"}:
        raise ValueError("Expected an audited runtime EE result")
    return {"result_kind": "runtime_json", "runtime_json_type": kind,
            "runtime_columns": list(compiled.get("bands", [])) if kind == "runtime_table" else []}


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate runtime result key")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("Runtime result must contain finite JSON")


def read_result(root, row):
    context = row.get("context") or {}
    kind = context.get("runtime_json_type")
    if (context.get("protocol") != "earthengine"
            or context.get("result_kind") != "runtime_json"
            or kind not in {"runtime_table", "runtime_value"}):
        raise ValueError("Task is not an owned runtime EE JSON value result")
    names = [name for name in row.get("assets", {}) if name.endswith(".json")]
    if len(names) != 1:
        raise ValueError("Expected one runtime EE JSON result")
    path = artifact_path(root, row["id"], names[0])
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise ValueError("Runtime JSON must be a bounded regular file")
        payload = stream.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("Runtime JSON exceeds1000000 UTF-8 bytes")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_nonfinite)
        if kind == "runtime_table":
            render_sample_csv(value, context.get("runtime_columns"))
        else:
            validate_metric_value(value)
    except (UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("Invalid bounded UTF-8 runtime EE result") from exc
    return value
