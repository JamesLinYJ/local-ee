"""Offline Python/JavaScript parity for Double raster-array selection."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest

from ee_random_split_parity import JAVASCRIPT
from ee_float64_graph_reference import evaluate_float64_graph
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_raster_array_reshape import local as reshape_fixture


ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXAMPLE = ROOT / "examples/57_GEE_python_double_selection.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/11_双精度排序选择.js"
COLLECTION_ID = "sentinel-2-l2a"
PROJECTION = {
    "proj:code": "EPSG:32649",
    "proj:transform": [10, 0, 220000, 0, -10, 3420000],
}
EXPECTED_BANDS = {
    "sorted_double_payload": ["row0_col0", "row0_col1", "row1_col0", "row1_col1"],
    "sorted_mixed_precision_payload": ["row0_col0", "row0_col1", "row1_col0", "row1_col1"],
    "sorted_payload_after_float32_keys": ["row0_col0", "row0_col1", "row1_col0", "row1_col1"],
    "first_max_double_coordinates": ["max_row", "max_column"],
    "first_max_after_float32_coordinates": ["max_row", "max_column"],
    "trimmed_middle_score_mean": ["trimmed_middle_score_mean"],
}
@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


def _example():
    import importlib.util

    spec = importlib.util.spec_from_file_location("double_selection_example", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _local_fixture():
    local = reshape_fixture.__wrapped__()
    item = local["items"][COLLECTION_ID][0]
    item["properties"].update(PROJECTION)
    arrays = local["arrays"]["reshape-scene"]
    adjacent = np.nextafter(1.0, np.inf)
    arrays.update({
        "b4": np.asarray([1.0, np.nan, 2.0, 1.0], dtype=np.float64),
        "b5": np.asarray([adjacent, 3.0, 2.0, 2.0], dtype=np.float64),
        "b6": np.asarray([adjacent, 2.0, 3.0, 3.0], dtype=np.float64),
        "b7": np.asarray([0.5, 1.0, 4.0, 4.0], dtype=np.float64),
    })
    return local


def _make_ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def _encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def _invocation_names(expression):
    return [
        node["functionName"] for _key, node in expression.get("scope", [])
        if isinstance(node, dict) and node.get("type") == "Invocation"
    ]


def _python_results(local):
    metadata, items = local["catalog"][0], local["items"]
    ee = _make_ee()
    outputs = _example().build_workflow(ee, ee.ImageCollection(COLLECTION_ID).first())
    assert set(outputs) == set(EXPECTED_BANDS)
    compiled = {
        name: compile_expression(_encode(ee, value), [metadata], items)
        for name, value in outputs.items()
    }
    encoded = {name: _encode(ee, value) for name, value in outputs.items()}
    return compiled, encoded


def _javascript_expressions():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for pinned JavaScript SDK serialization")
    setup = JAVASCRIPT.split("const config =", 1)[0]
    script = setup + f"""
const source = fs.readFileSync({json.dumps(JAVASCRIPT_EXAMPLE)}, 'utf8');
const outputs = new Function('ee', source + '\\nreturn outputs;')(ee);
console.log(JSON.stringify({{
  attempts,
  outputs: Object.fromEntries(Object.entries(outputs).map(([name, value]) =>
    [name, ee.Serializer.encode(value)]))
}}));
"""
    completed = subprocess.run(
        [node, "-e", script], cwd=ROOT, capture_output=True,
        text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["attempts"] == 0
    return result["outputs"]


def _numeric_result(compiled, name, local):
    result = compiled[name]
    validate(result["process_graph"])
    assert result["kind"] == "image"
    assert len(result["process_graph"]) <= 500
    assert result["source_item_ids"] == ["reshape-scene"]
    values, names, timed = evaluate_float64_graph(result, local["arrays"], grid=local["grid"],
        source_geometries={"reshape-scene": local["geometry"]})
    assert names == EXPECTED_BANDS[name]
    assert timed is False
    return values


def _payload_values(local):
    arrays = local["arrays"]["reshape-scene"]
    return np.stack([arrays[band] for band in ("blue", "green", "red", "nir")], axis=1).reshape(
        (len(local["grid"]), 2, 2),
    )


def _key_values(local):
    arrays = local["arrays"]["reshape-scene"]
    return np.stack([arrays["b5"], arrays["b4"]], axis=1).reshape((-1, 1, 2))


def _stable_slice_sort(payload, keys):
    samples, rows, columns = payload.shape
    valid = np.isfinite(payload).all(axis=(1, 2)) & np.isfinite(keys).all(axis=(1, 2))
    result = np.full((samples, rows * columns), np.nan, dtype=np.float64)
    for sample in np.flatnonzero(valid):
        permutation = sorted(range(columns), key=lambda index: float(keys[sample, 0, index]))
        result[sample] = np.take(payload[sample], permutation, axis=1).reshape(-1)
    return result.T


def _expected_coordinates(values):
    valid = np.isfinite(values).all(axis=1)
    result = np.full((2, len(values)), np.nan, dtype=np.float64)
    for sample in np.flatnonzero(valid):
        result[:, sample] = np.unravel_index(int(np.argmax(values[sample])), (2, 2))
    return result


def test_pinned_python_javascript_selection_graphs_match_with_metadata_and_caps():
    local = _local_fixture()
    python, encoded = _python_results(local)
    javascript = _javascript_expressions()

    assert set(javascript) == set(python) == set(EXPECTED_BANDS)
    for name, expression in javascript.items():
        result = compile_expression(expression, local["catalog"], local["items"])
        assert result == python[name], name
        assert result["bands"] == EXPECTED_BANDS[name]
        assert len(result["process_graph"]) <= 500
        assert _invocation_names(expression) == _invocation_names(encoded[name])
        properties = result["properties"]
        assert properties["workflow"] == _example().SYNTHETIC_VERSION
        assert properties["system:index"] == "reshape-scene"
        assert properties["system:time_start"] == 1000
        assert properties["proj:code"] == "EPSG:32649"
        assert properties["proj:transform"] == PROJECTION["proj:transform"]

    sort_calls = _invocation_names(encoded["sorted_double_payload"])
    assert "Image.arraySort" in sort_calls
    assert sort_calls.index("Image.arrayReshape") < sort_calls.index("Image.arraySort")
    assert "Image.arrayArgmax" in _invocation_names(
        encoded["first_max_double_coordinates"],
    )
    trimmed_calls = _invocation_names(encoded["trimmed_middle_score_mean"])
    assert {"Image.arraySort", "Image.arraySlice", "Image.arrayReduce", "Image.arrayGet"} <= set(
        trimmed_calls,
    )


def test_double_sort_first_max_and_trimmed_mean_match_independent_numpy_reference():
    local = _local_fixture()
    compiled, _encoded = _python_results(local)
    payload = _payload_values(local)
    keys = _key_values(local)
    actual = {
        name: _numeric_result(compiled, name, local)
        for name in EXPECTED_BANDS
    }

    np.testing.assert_array_equal(actual["sorted_double_payload"], _stable_slice_sort(payload, keys))
    float_payload = payload.astype(np.float32).astype(np.float64)
    np.testing.assert_array_equal(
        actual["sorted_mixed_precision_payload"], _stable_slice_sort(float_payload, keys),
    )
    rounded_keys = keys.astype(np.float32).astype(np.float64)
    np.testing.assert_array_equal(actual["sorted_payload_after_float32_keys"],
                                  _stable_slice_sort(payload, rounded_keys))

    arrays = local["arrays"]["reshape-scene"]
    scores = np.stack(
        [arrays[band] for band in ("b4", "b5", "b6", "b7")], axis=1,
    )
    np.testing.assert_array_equal(
        actual["first_max_double_coordinates"],
        _expected_coordinates(scores),
    )
    rounded_scores = scores.astype(np.float32).astype(np.float64)
    np.testing.assert_array_equal(
        actual["first_max_after_float32_coordinates"],
        _expected_coordinates(rounded_scores),
    )

    valid_scores = np.isfinite(scores).all(axis=1)
    expected_mean = np.full((1, len(scores)), np.nan, dtype=np.float64)
    for sample in np.flatnonzero(valid_scores):
        ordered = sorted(float(value) for value in scores[sample])
        expected_mean[0, sample] = np.mean(ordered[1:3])
    np.testing.assert_array_equal(
        actual["trimmed_middle_score_mean"], expected_mean,
    )

    # The b4 key is missing at pixel 1; red is independently missing at pixel 2.
    for name in (
        "sorted_double_payload", "sorted_mixed_precision_payload",
        "sorted_payload_after_float32_keys",
    ):
        assert np.isnan(actual[name][:, 1]).all()
        assert np.isnan(actual[name][:, 2]).all()
    assert np.isnan(actual["first_max_double_coordinates"][:, 1]).all()
    assert np.isnan(actual["first_max_after_float32_coordinates"][:, 1]).all()
    assert np.isnan(actual["trimmed_middle_score_mean"][0, 1])

    # A one-ULP binary64 key swap disappears after a nested Float32 cast.
    assert actual["sorted_double_payload"][:, 0].tolist() == [
        10.0, 16_777_217.0, 1000.0, 100.0,
    ]
    assert actual["sorted_payload_after_float32_keys"][:, 0].tolist() == [
        16_777_217.0, 10.0, 100.0, 1000.0,
    ]
    assert actual["first_max_double_coordinates"][:, 0].tolist() == [0.0, 1.0]
    assert actual["first_max_after_float32_coordinates"][:, 0].tolist() == [0.0, 0.0]


def test_example_cli_compiles_six_bounded_graphs_without_network():
    local = _local_fixture()
    catalog, items = _example().synthetic_catalog()
    assert catalog == local["catalog"]
    assert items == local["items"]

    script = f"""
import contextlib, io, json, runpy
from scripts.ee_python_api.offline import OfflineGuard
captured = io.StringIO()
with OfflineGuard() as guard:
    with contextlib.redirect_stdout(captured):
        runpy.run_path({str(PYTHON_EXAMPLE)!r}, run_name="__main__")
print(json.dumps({{
    "network_attempts": guard.evidence()["attempt_count"],
    "output": captured.getvalue(),
}}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT,
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["network_attempts"] == 0
    records = [
        json.loads(line) for line in report["output"].splitlines() if line.strip()
    ]
    assert {record["output"] for record in records} == set(EXPECTED_BANDS)
    assert len(records) == len(EXPECTED_BANDS)
    for record in records:
        assert record["fixture"] == _example().SYNTHETIC_VERSION
        assert record["bands"] == EXPECTED_BANDS[record["output"]]
        assert type(record["graph_nodes"]) is int
        assert 1 <= record["graph_nodes"] <= 500
