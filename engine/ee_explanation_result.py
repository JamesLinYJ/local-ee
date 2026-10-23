"""Owned JSON results for the closed Smile RF explanation views."""
from __future__ import annotations

from pathlib import Path

from openeo_driver.save_result import SaveResult
from .ee_json_result import PendingRuntimeValue


def _precharge_spec(spec, output_bytes=0):
    from .ee_smile_rf_training import _RuntimeWork, _WireScan, _utf8_size

    size = _utf8_size(spec, 16_384, "RF explanation specification")
    work = _RuntimeWork()
    wire = _WireScan()
    # Reserve parsing plus the largest closed projected value copy before either
    # operation. The JSON writer enforces output_bytes independently as well.
    work.charge(size * 2 + 8192)
    wire.charge(size * 2 + output_bytes)


class RuntimeRFExplanationResult(SaveResult):
    """A validated projected RF explanation with its exact trusted spec."""

    DEFAULT_FORMAT = "JSON"

    def __init__(self, value, spec):
        from gee.rf_explanation_spec import decode_explanation_spec, validate_explanation_value
        from .ee_json_result import MAX_JSON_BYTES, _payload

        if type(spec) is not str:
            raise ValueError("RF explanation result requires its exact canonical specification")
        _precharge_spec(spec, MAX_JSON_BYTES)
        decoded = decode_explanation_spec(spec)
        owned = validate_explanation_value(value, decoded)
        super().__init__(format="JSON")
        self.explanation_spec = spec
        self._payload = _payload(owned)

    def _check_format(self):
        if not self.is_format("JSON"):
            raise ValueError("Runtime RF explanations support JSON only")

    def write_assets(self, directory: str | Path):
        from .ee_json_result import _write_json

        self._check_format()
        return _write_json(directory, self._payload, "Earth Engine random forest explanation")

    def create_flask_response(self):
        from flask import Response

        self._check_format()
        return Response(self._payload, mimetype="application/json")


class PendingRFExplanationResult(PendingRuntimeValue):
    """Dry-run lineage only; never contains a guessed model explanation."""

    DEFAULT_FORMAT = "JSON"

    def __init__(self, spec, traces=(), data_tracer=None):
        from gee.rf_explanation_spec import decode_explanation_spec

        if type(spec) is not str:
            raise ValueError("Pending RF explanation requires its exact canonical specification")
        _precharge_spec(spec)
        decode_explanation_spec(spec)
        super().__init__(traces=traces, data_tracer=data_tracer)
        self.explanation_spec = spec
