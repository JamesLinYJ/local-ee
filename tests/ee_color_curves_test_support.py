"""Shared bounded fixtures and graph assertions for color/curve tests."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from gee.integer_values_spec import decode_integer_values_spec
from gee.local_processes import process_spec
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
BANDS = ["blue", "green", "red", "nir", "SCL"]
GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [20, 0], [20, 1], [0, 1], [0, 0]]],
}


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


@pytest.fixture
def local():
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {
        "bands": {"values": BANDS}}}]
    items = {"sentinel-2-l2a": [{
        "id": "scene-a", "bbox": [0, 0, 20, 1], "geometry": GEOMETRY,
        "properties": {"system:index": "scene-a", "system:time_start": 1000,
                       "proj:code": "EPSG:32649",
                       "proj:transform": [10, 0, 220000, 0, -10, 3420000]},
    }, {
        "id": "scene-b", "bbox": [0, 0, 20, 1], "geometry": GEOMETRY,
        "properties": {"system:index": "scene-b", "system:time_start": 2000,
                       "proj:code": "EPSG:32649",
                       "proj:transform": [20, 0, 220000, 0, -20, 3420000]},
    }]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def find_invocation(value, function_name):
    if isinstance(value, dict):
        if value.get("type") == "Invocation" and value.get("functionName") == function_name:
            return value
        for child in value.values():
            result = find_invocation(child, function_name)
            if result is not None:
                return result
    elif isinstance(value, (list, tuple)):
        for child in value:
            result = find_invocation(child, function_name)
            if result is not None:
                return result
    return None


def nodes(result, process_id):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == process_id]


def assert_graph_budget(result):
    assert len(result["process_graph"]) <= 500
    assert len(json.dumps(result["process_graph"], separators=(",", ":"))) <= 1_000_000
    validate(result["process_graph"])
    integer_nodes = nodes(result, "local_ee_integer_values")
    if integer_nodes:
        process = process_spec("local_ee_integer_values")
        assert process["id"] == "local_ee_integer_values"
        assert {parameter["name"] for parameter in process["parameters"]} == {"data", "spec"}
        assert process["parameters"][1]["schema"]["maxLength"] == 1024
        for node in integer_nodes:
            assert set(node["arguments"]) == {"data", "spec"}
            decode_integer_values_spec(node["arguments"]["spec"])


def pixels(red, green, blue, *, nir=None, scl=None):
    length = len(red)
    return {"scene-a": {
        "blue": np.asarray(blue, dtype=np.float64),
        "green": np.asarray(green, dtype=np.float64),
        "red": np.asarray(red, dtype=np.float64),
        "nir": np.zeros(length) if nir is None else np.asarray(nir, dtype=np.float64),
        "SCL": np.ones(length) if scl is None else np.asarray(scl, dtype=np.float64),
    }}
