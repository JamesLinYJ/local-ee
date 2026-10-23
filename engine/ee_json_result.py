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
        self.classification_origin_spec = None
        self.classification_origin_verified = False
        self.runtime_operations = ()
        self.prior_sample_operation_count = None
        self.prior_sample_operation_work = None
        self.runtime_operation_work = None
        self.traces = ()
        self.data_tracer = None
        # Validate the whole public shape before any result is published.
        _payload(self._data)
        self.format = "JSON"

    def _validate_classification_origin(self):
        from .ee_runtime_table_ops import has_classification_origin, validate_runtime_table_origin

        if has_classification_origin(self):
            from .ee_sample_table_ops import _SampleOperationContext

            work = _SampleOperationContext(self.runtime_operation_work)
            validate_runtime_table_origin(self, work)

    def write_assets(self, directory: str | Path):
        self._validate_classification_origin()
        if self.is_format("CSV"):
            return super().write_assets(directory)
        if not self.is_format("JSON"):
            raise ValueError("Classified feature tables support JSON or CSV only")
        return _write_json(directory, _payload(self._data), "Earth Engine classified features")

    def create_flask_response(self):
        self._validate_classification_origin()
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
        self.classification_origin_spec = None
        self.classification_origin_verified = False
        self.runtime_operations = ()
        self.prior_sample_operation_count = None
        self.prior_sample_operation_work = None
        self.runtime_operation_work = None


def attach_classification_origin(
    table, specification, *, prior_sample_operation_count=0,
    prior_sample_operation_work=0, operations=(), operation_work=None,
):
    """Attach the immutable classification lineage used by runtime table ops."""
    if type(table) not in (RuntimeFeatureTable, PendingRuntimeTable):
        raise ValueError("Classification origin requires an exact runtime feature table")
    if type(specification) is not str:
        raise ValueError("Classification origin specification must be exact JSON text")
    if (type(prior_sample_operation_count) is not int
            or not 0 <= prior_sample_operation_count <= 16
            or type(prior_sample_operation_work) is not int
            or not 0 <= prior_sample_operation_work <= 50_000):
        raise ValueError("Inherited sample operation count/work is outside its bounded domain")
    if prior_sample_operation_count and prior_sample_operation_work == 0:
        raise ValueError("Inherited sample operation count/work is inconsistent")
    if (type(operations) is not tuple or len(operations) > 16
            or any(type(item) is not str for item in operations)):
        raise ValueError("Runtime feature operation chain must be an exact text tuple")
    if prior_sample_operation_count + len(operations) > 16:
        raise ValueError("Inherited and classified operation metadata is inconsistent")
    if operation_work is None:
        operation_work = prior_sample_operation_work
    if (type(operation_work) is not int
            or not prior_sample_operation_work <= operation_work <= 50_000):
        raise ValueError("Runtime feature operation work is outside its cumulative budget")
    table.classification_origin_spec = specification
    table.classification_origin_verified = True
    table.runtime_operations = operations
    table.prior_sample_operation_count = prior_sample_operation_count
    table.prior_sample_operation_work = prior_sample_operation_work
    table.runtime_operation_work = operation_work
    return table
