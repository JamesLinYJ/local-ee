"""Cross-family independent values and actual Python/JS SDK serialization."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ee_random_split_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "scores": {"red": 0, "nir": 8, "quality": 10, "version": 1},
    "score_vector": [0, 8, 10], "normalized_nir": 0.8,
    "label_count": 2, "label_path": "wet/land/wet", "spliced": [1, 2, 8, 9, 4],
    "trig_identity": [0, 0.5, 1], "signed_remainder": [-1, 1], "name": "scene",
    "json_roundtrip": {"red": 0, "nir": 8, "quality": 10, "version": 1},
}


def python_results():
    spec = importlib.util.spec_from_file_location(
        "static_families_example", ROOT / "examples/38_GEE_python_static_families.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        result = {key: compile_expression(ee.serializer.encode(value, for_cloud_api=False), [], {})
                  for key, value in module.build_workflow(ee).items()}
    assert guard.evidence()["attempt_count"] == 0
    return result


def test_static_family_workflow_matches_independent_expectations():
    compiled = python_results()
    for key, expected in EXPECTED.items():
        assert compiled[key]["kind"] == "value"
        if key == "trig_identity":
            assert compiled[key]["value"] == pytest.approx(expected, abs=2e-15)
        else:
            assert compiled[key]["value"] == expected


def test_static_family_python_javascript_clients_compute_identical_outputs():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for pinned JavaScript serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
let scores = ee.Dictionary.fromLists(['red','nir','cloud'],[-2,8,15]);
scores = scores.map((_key,value) => ee.Number(value).clamp(0,10));
scores = scores.rename(['cloud'],['quality']);
scores = scores.combine(ee.Dictionary({version:1}),true);
const labels=ee.List(['water','cloud','land','water']);
const clean=labels.removeAll(['cloud']).replaceAll('water','wet');
const values={scores,score_vector:scores.toArray(['red','nir','quality'],0),
 normalized_nir:scores.getNumber('nir').unitScale(0,10),label_count:labels.frequency('water'),
 label_path:clean.join('/'),spliced:ee.List([1,2,3,4]).splice(-2,1,[8,9]),
 trig_identity:ee.Array([0,0.5,1]).asin().sin(),
 signed_remainder:ee.Array([-7,7]).mod(ee.Array([3,-3])),
 name:ee.String('  SCENE_2024  ').trim().toLowerCase().slice(0,5),
 json_roundtrip:ee.String.encodeJSON(scores).decodeJSON()};
const outputs=Object.fromEntries(Object.entries(values).map(([key,value])=>[key,ee.Serializer.encode(value)]));
if(attempts !== 0) throw Error('unexpected networking');
console.log(JSON.stringify({outputs,attempts}));
"""
    result = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    outputs = json.loads(result.stdout)
    assert outputs["attempts"] == 0
    expected = python_results()
    for key, expression in outputs["outputs"].items():
        assert compile_expression(expression, [], {}) == expected[key]
