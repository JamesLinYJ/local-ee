"""Trusted pinned-SDK harness; synthetic graphs are not Spark execution."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np

from ee_random_split_parity import JAVASCRIPT, semantic_wire
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-collection-link-wave58-v1.json"
PYTHON_EXAMPLE = ROOT / "examples/63_GEE_python_collection_link.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/17_集合匹配.js"


def fixture():
    return json.loads(FIXTURE_PATH.read_text())


def example():
    spec = importlib.util.spec_from_file_location("collection_link_example", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def compile_outputs(outputs, data):
    catalog, items = example().declared_local_data(data)
    return {key: compile_expression(expression, catalog, items)
            for key, expression in outputs.items()}


def python_graphs(data):
    with OfflineGuard() as guard:
        ee = make_ee()
        values = example().build_workflow(ee, data)
        encoded = {key: ee.serializer.encode(value, for_cloud_api=False)
                   for key, value in values.items()}
        compiled = compile_outputs(encoded, data)
    assert guard.evidence()["attempt_count"] == 0
    return compiled, encoded


def javascript_graphs(data):
    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node is required for pinned JavaScript parity")
    # Reuse only the existing official-client initialization and network guards.
    initialization = JAVASCRIPT.split("const config =", 1)[0]
    script = initialization + r"""
const vm = require('node:vm');
vm.runInThisContext(fs.readFileSync('examples/javascript/17_集合匹配.js', 'utf8'));
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const values = buildCollectionLinkWorkflow(ee, fixture);
const expressions = Object.fromEntries(Object.entries(values).map(([key, value]) =>
  [key, ee.Serializer.encode(value)]));
if (attempts !== 0) throw Error('Collection-link parity attempted networking');
console.log(JSON.stringify({expressions, attempts}));
"""
    process = subprocess.run(
        [node, "-e", script], cwd=ROOT, input=json.dumps(data),
        capture_output=True, text=True, timeout=30,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["attempts"] == 0
    return compile_outputs(result["expressions"], data), result["expressions"]


def semantic_compiled(outputs):
    return semantic_wire(json.loads(json.dumps(outputs)))


def sample_arrays(data):
    return {
        scene["id"]: {
            name: np.asarray([np.nan if value is None else value for value in values],
                             dtype=np.float64)
            for name, values in scene["arrays"].items()
        } for scene in data["scenes"]
    }
