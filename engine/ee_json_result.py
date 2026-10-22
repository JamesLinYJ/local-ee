"""Owned bounded JSON results for runtime EE tables and matrix accessors."""
from __future__ import annotations

import json
import os
from pathlib import Path

from openeo_driver.save_result import SaveResult

from .ee_sampling_result import SampledFeatureTable


MAX_JSON_BYTES = 1_000_000


def _owned_value(value):
    from gee.table_values import _validate_json
    from gee.compat.earthengine.public_values import public_value

    _validate_json(value)
    return public_value(value)


def _payload(value):
    data = json.dumps(_owned_value(value), ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("Runtime EE JSON exceeds1000000 UTF-8 bytes")
    return data


def _write_json(directory, payload, title):
    from gee.artifacts import artifact_path

    root, job_id, csv_path = SampledFeatureTable._physical_output(directory)
    target = csv_path.with_suffix(".json")
    if not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("Exclusive no-follow output is unavailable")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    descriptor = os.open(target, flags, 0o640)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
    checked = artifact_path(root, job_id, target.name)
    return {checked.name: {"href": str(checked), "title": title,
                           "type": "application/json", "roles": ["data"],
                           "file:size": len(payload)}}


class RuntimeJsonResult(SaveResult):
    """A materialized scalar/list value, writable only inside its owning job."""

    DEFAULT_FORMAT = "JSON"

    def __init__(self, value):
        from gee.rf_validation_spec import validate_metric_value

        super().__init__(format="JSON")
        self._payload = _payload(validate_metric_value(value))

    def _check_format(self):
        if not self.is_format("JSON"):
            raise ValueError("Runtime matrix accessors support JSON only")

    def write_assets(self, directory: str | Path):
        self._check_format()
        return _write_json(directory, self._payload, "Earth Engine computed value")

    def create_flask_response(self):
        from flask import Response

        self._check_format()
        return Response(self._payload, mimetype="application/json")


class RuntimeFeatureTable(SampledFeatureTable):
    """Actual RF feature predictions; getInfo JSON and explicit CSV export."""

    DEFAULT_FORMAT = "JSON"

    def __init__(self, data: dict, columns: list[str]):
        super().__init__(data=data, columns=columns)
        # Validate the whole public shape before any result is published.
        _payload(self._data)
        self.format = "JSON"

    def write_assets(self, directory: str | Path):
        if self.is_format("CSV"):
            return super().write_assets(directory)
        if not self.is_format("JSON"):
            raise ValueError("Classified feature tables support JSON or CSV only")
        return _write_json(directory, _payload(self._data), "Earth Engine classified features")

    def create_flask_response(self):
        if self.is_format("CSV"):
            return super().create_flask_response()
        if not self.is_format("JSON"):
            raise ValueError("Classified feature tables support JSON or CSV only")
        from flask import Response

        return Response(_payload(self._data), mimetype="application/json")


class PendingRuntimeValue(SaveResult):
    """Dry-run source lineage with no fabricated computed value."""

    DEFAULT_FORMAT = "JSON"

    def __init__(self, traces=(), data_tracer=None):
        super().__init__(format="JSON")
        self.traces = tuple(traces)
        self.data_tracer = data_tracer

    def write_assets(self, directory):
        raise ValueError("Pending runtime values cannot be written")

    def create_flask_response(self):
        raise ValueError("Pending runtime values cannot be serialized")


class PendingRuntimeTable(PendingRuntimeValue):
    """Dry-run classified table schema; there are no predicted rows."""

    def __init__(self, columns, traces=(), data_tracer=None):
        if (type(columns) not in (list, tuple) or not 3 <= len(columns) <= 256
                or any(type(name) is not str or len(name) > 256 or "\x00" in name for name in columns)
                or len(set(columns)) != len(columns)
                or columns[0] != "system:index" or columns[-1] != ".geo"):
            raise ValueError("Invalid pending classified table schema")
        super().__init__(traces=traces, data_tracer=data_tracer)
        self.columns = tuple(columns)
