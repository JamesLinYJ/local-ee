"""Official SDK graph parity and independent synthetic statistics.

The evaluator is a test oracle. Actual native tiles have their own opt-in
probe; neither establishes a deployed Spark/export/browser workflow.
"""
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from ee_random_split_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
CATALOG = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": ["red", "nir"]}}}]
ITEMS = {"sentinel-2-l2a": [{
    "id": key, "bbox": [0, 0, 2, 1],
    "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 1], [0, 1], [0, 0]]]},
    "properties": {"system:time_start": 1000 + index, "system:index": key,
                   "proj:code": "EPSG:3857", "proj:transform": [10, 0, 0, 0, -10, 10]},
} for index, key in enumerate(("a", "b", "c"))]}
ARRAYS = {key: {
    "red": np.array([red, math.nan, 7 if key == "a" else math.nan, math.nan]),
    "nir": np.array([red * 2, math.nan, 9 if key == "a" else math.nan, math.nan]),
} for key, red in (("a", 1), ("b", 3), ("c", 5))}


def python_results():
    spec = importlib.util.spec_from_file_location(
        "raster_statistics_example", ROOT / "examples/45_GEE_python_raster_statistics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        outputs = module.build_workflow(ee, ee.ImageCollection("sentinel-2-l2a"))
        results = {key: compile_expression(ee.serializer.encode(value, for_cloud_api=False),
                                          CATALOG, ITEMS) for key, value in outputs.items()}
    assert guard.evidence()["attempt_count"] == 0
    return results


def test_band_time_and_field_axis_workflow_has_independent_hand_values():
    results = python_results()
    static = [8 / 3, math.sqrt(8 / 3), 4, 1, 5, 15]
    np.testing.assert_allclose(results["static_stats"]["value"], [static], rtol=2e-15)
    expected = {
        "band_stats": [.25, .5, .5, 1, 2, 2],
        "time_stats": [*static, 32 / 3, math.sqrt(32 / 3), 16, 2, 10, 120],
        "repeated_stats": [8 / 9, math.sqrt(8 / 9), 4 / 3, 1, 3, 3,
                           32 / 9, math.sqrt(32 / 9), 16 / 3, 2, 6, 24],
        "array_stats": [.25, .5, .5, 1, 2, 2],
    }
    for name, reference in expected.items():
        result = results[name]
        validate(result["process_graph"])
        values, names, timed = evaluate_graph(result, ARRAYS)
        assert not timed and names == result["bands"]
        np.testing.assert_allclose(values[:, 0], reference, rtol=2e-15)
        assert np.isnan(values[:, [1, 3]]).all()
        if name in {"time_stats", "repeated_stats"}:
            sample_var = 0 if name == "repeated_stats" else math.nan
            np.testing.assert_allclose(values[:, 2], [0, 0, sample_var, 7, 7,
                49 if name == "repeated_stats" else 7, 0, 0, sample_var, 9, 9,
                81 if name == "repeated_stats" else 9], equal_nan=True)
        assert any(node["process_id"] == "local_ee_reduce_bands"
                   for node in result["process_graph"].values())
    assert results["time_stats"]["source_item_ids"] == ["a", "b", "c"]


def test_python_and_javascript_share_five_statistics_workflow_outputs():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for pinned JS SDK serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const collection=ee.ImageCollection('sentinel-2-l2a');
const reducer=ee.Reducer.variance()
 .combine({reducer2:ee.Reducer.stdDev(),sharedInputs:true})
 .combine({reducer2:ee.Reducer.sampleVariance().setOutputs(['sample_var']),sharedInputs:true})
 .combine({reducer2:ee.Reducer.minMax(),sharedInputs:true})
 .combine({reducer2:ee.Reducer.product(),sharedInputs:true});
const first=collection.first(), selected=collection.toList(2);
const repeated=ee.ImageCollection.fromImages([
 ee.Image(selected.get(0)),ee.Image(selected.get(1)),ee.Image(selected.get(0))]);
const values={band_stats:first.reduce(reducer),time_stats:collection.reduce(reducer),
 repeated_stats:repeated.reduce(reducer),
 array_stats:first.toArray().toArray(1).arrayReduce(reducer,[0],1)
 .arrayFlatten([['bands'],['variance','stdDev','sample_var','min','max','product']]),
 static_stats:ee.Array([[1],[3],[5]]).reduce(reducer,[0],1)};
console.log(JSON.stringify({attempts,outputs:Object.fromEntries(
 Object.entries(values).map(([k,v])=>[k,ee.Serializer.encode(v)]))}));
"""
    result = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert decoded["attempts"] == 0
    expected = python_results()
    assert set(decoded["outputs"]) == set(expected)
    for name, value in decoded["outputs"].items():
        assert compile_expression(value, CATALOG, ITEMS) == expected[name]
