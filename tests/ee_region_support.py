"""Shared offline fixtures for focused EE region boundary tests."""
from __future__ import annotations

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError
from gee.services import ee as ee_service
from scripts.ee_python_api.probe_cases import synthetic_inputs


def _polygon(geodesic_marker=...):
    value = {
        "type": "Polygon",
        "coordinates": [[[100, 30], [101, 30], [101, 31], [100, 30]]],
    }
    if geodesic_marker is not ...:
        value["geodesic"] = geodesic_marker
    return value


@pytest.fixture
def sdk():
    import ee

    configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path="vendor/earthengine-js/algorithms.json",
    )
    return ee


def _without_native_s2_validation(monkeypatch):
    # These tests exercise the Python edge-model boundary. Keep native S2
    # loading outside the test so they remain deterministic and offline.
    from gee.compat.earthengine import geometry_topology

    monkeypatch.setattr(geometry_topology, "validate_geometry_topology", lambda *_args, **_kwargs: None)


def _service_export_probe(monkeypatch, sdk):
    metadata, items, _ = synthetic_inputs()
    monkeypatch.setattr(
        ee_service, "catalog_snapshot", lambda: ([metadata], items),
    )
    state = {"pixel": [], "jobs": []}

    def pixel_budget(compiled, _items, options, max_pixels):
        state["pixel"].append((compiled, options, max_pixels))
        return 23

    def make_job(_backend, _account, compiled, *_args, **_kwargs):
        state["jobs"].append(compiled)
        return {"job_id": "synthetic", "warnings": []}

    monkeypatch.setattr(ee_service, "pixel_budget", pixel_budget)
    monkeypatch.setattr(ee_service, "make_job", make_job)
    expression = sdk.serializer.encode(
        sdk.ImageCollection("sentinel-2-l2a").first().select("nir"),
        for_cloud_api=False,
    )
    account = {"user_id": "synthetic-user", "scope": "user"}
    return state, expression, account
