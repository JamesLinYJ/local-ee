"""Typed bounded EE sample tables and their dry-run counterparts."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any

from openeo_driver.save_result import SaveResult


class SampledFeatureTable(SaveResult):
    """Actual bounded FeatureCollection samples, writable only as audited CSV."""

    DEFAULT_FORMAT = "CSV"

    def __init__(self, data: dict[str, Any], columns: list[str]):
        from gee.sampling_values import render_sample_csv

        if type(columns) is not list or not columns or any(type(name) is not str for name in columns):
            raise ValueError("Sample table columns must be a non-empty string list")
        # Validate before retaining an owned copy. This also applies the shared
        # row, column, cell, JSON, geometry and CSV budgets.
        render_sample_csv(data, columns)
        super().__init__(format="CSV")
        self._data = copy.deepcopy(data)
        self._columns = tuple(columns)
        # Cache the work of copying the full owned FeatureCollection, including
        # unselected properties and geometry. Strings are immutable, while
        # nested containers and their field/value slots are copied per node.
        self._data_copy_work = self._measure_copy_work(self._data)

    @staticmethod
    def _measure_copy_work(data: dict[str, Any]) -> int:
        stack = [data]
        work = 0
        while stack:
            value = stack.pop()
            work += 1  # container or scalar value node
            if type(value) is dict:
                work += len(value)  # copied mapping field slots
                stack.extend(value.values())
            elif type(value) in (list, tuple):
                work += len(value)  # copied sequence slots
                stack.extend(value)
        return work

    @property
    def data(self) -> dict[str, Any]:
        """Return an owned bounded FeatureCollection for trusted consumers."""
        return copy.deepcopy(self._data)

    @property
    def columns(self) -> list[str]:
        return list(self._columns)

    @property
    def row_count(self) -> int:
        """Return the validated row count without copying sampled features."""
        return len(self._data["features"])

    @property
    def data_copy_work(self) -> int:
        """Cached full-structure work needed before returning ``data`` copy."""
        return self._data_copy_work

    def _csv_bytes(self) -> bytes:
        from gee.sampling_values import render_sample_csv

        text = render_sample_csv(self._data, list(self._columns))
        try:
            return text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("Sample CSV must be valid UTF-8") from exc

    @staticmethod
    def _physical_output(directory: str | Path) -> tuple[Path, str, Path]:
        """Resolve the runner's `<job>/out/out` SaveResult prefix physically."""
        from gee.artifacts import output_dir

        prefix = Path(directory).absolute()
        if prefix.name != "out":
            raise ValueError("Sample CSV output must use the existing batch out path")
        folder = prefix.parent
        job = folder.parent
        jobs = job.parent
        if folder.name != "out" or jobs.name != "jobs":
            raise ValueError("Sample CSV output must belong to a physical job directory")
        root = jobs.parent
        canonical = output_dir(root, job.name)
        if prefix != canonical / "out" or folder != canonical:
            raise ValueError("Sample CSV output escaped its physical job")
        return root, job.name, canonical / "openEO.csv"

    def write_assets(self, directory: str | Path) -> dict[str, dict[str, Any]]:
        """Write one exclusive, no-follow CSV in the owning job's output folder."""
        if not self.is_format("CSV"):
            raise ValueError("Sampled FeatureCollections support CSV output only")
        from gee.artifacts import artifact_path

        root, job_id, target = self._physical_output(directory)
        payload = self._csv_bytes()
        if len(payload) > 1_000_000:
            raise ValueError("Sample CSV exceeds 1000000 UTF-8 bytes")
        if not hasattr(os, "O_NOFOLLOW"):
            raise ValueError("Exclusive no-follow output is unavailable")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        descriptor = os.open(target, flags, 0o640)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(payload)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        checked = artifact_path(root, job_id, target.name)
        return {
            checked.name: {
                "href": str(checked),
                "title": "Sampled Earth Engine features",
                "type": "text/csv",
                "roles": ["data"],
                "file:size": len(payload),
            }
        }

    def create_flask_response(self):
        if not self.is_format("CSV"):
            raise ValueError("Sampled FeatureCollections support CSV output only")
        from flask import Response

        return Response(self._csv_bytes(), mimetype="text/csv")

    def __repr__(self) -> str:
        return f"SampledFeatureTable(rows={len(self._data['features'])}, columns={len(self._columns)})"


class PendingSampledTable(SaveResult):
    """SaveResult-compatible dry-run schema with no sample rows or output."""

    DEFAULT_FORMAT = "CSV"

    def __init__(
        self,
        columns: tuple[str, ...],
        sample_spec: str,
        traces: tuple[Any, ...] = (),
        data_tracer: Any = None,
    ):
        # Upstream save_result copies SaveResult instances and assigns .format
        # and .options on the copy. Keep this mutable base type, while storing
        # only the declared schema and source trace state for dry-run use.
        super().__init__(format="CSV")
        self.columns = tuple(columns)
        self.sample_spec = sample_spec
        self.traces = tuple(traces)
        self.data_tracer = data_tracer

    def write_assets(self, directory: str | Path) -> dict[str, dict[str, Any]]:
        raise ValueError("Pending dry-run sample tables cannot be written")

    def create_flask_response(self):
        raise ValueError("Pending dry-run sample tables cannot be serialized")

    def __repr__(self) -> str:
        return f"PendingSampledTable(columns={self.columns!r}, rows=unavailable)"


@dataclass(frozen=True)
class PendingMinimumDistanceModel:
    """Typed training result for dry-run classification, with no fake centers."""

    metric: str
    schema: tuple[str, ...]
    class_property: str
    traces: tuple[Any, ...] = ()
    data_tracer: Any = field(default=None, compare=False, repr=False)
