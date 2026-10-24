"""Pinned official Python/JavaScript SDK wire generation for Wave67."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

from ee_weighted_sampling_helpers import _semantic_wire
from gee.ee_python_client import configure_local_ee
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXAMPLE = ROOT / "examples/71_GEE_python_empty_expression.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/25_空影像表达式.js"


def python_example():
    spec = importlib.util.spec_from_file_location("wave67_empty_expression_python", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def wire_digest(value):
    payload = json.dumps(_semantic_wire(value), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_graph(value, local=None, parent=None, active=frozenset()):
    """Resolve CompoundValue references so SDK scope numbering cannot mask parity."""
    local = local or {}
    parent = parent or {}
    if isinstance(value, dict) and value.get("type") == "CompoundValue":
        pairs = value.get("scope", [])
        scope = dict(pairs)
        if len(scope) != len(pairs):
            raise ValueError("official SDK graph contains duplicate scope identifiers")
        return {
            "type": "CompoundValue",
            "value": canonical_graph(value.get("value"), scope, local, active),
        }
    if isinstance(value, dict) and value.get("type") == "ValueRef":
        key = value.get("value")
        owner = local if key in local else parent
        if key not in owner:
            raise ValueError(f"official SDK graph has unresolved ValueRef {key!r}")
        token = (id(owner), key)
        if token in active:
            raise ValueError(f"official SDK graph has cyclic ValueRef {key!r}")
        return canonical_graph(owner[key], local, parent, active | {token})
    if isinstance(value, dict):
        return {key: canonical_graph(item, local, parent, active)
                for key, item in value.items()}
    if isinstance(value, list):
        return [canonical_graph(item, local, parent, active) for item in value]
    return value


def javascript_wires(fixture):
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node is required for the official JavaScript SDK comparison")
    script = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('Wave67 SDK wire generation attempted networking'); }
for (const module of ['node:http', 'node:https']) {
  const api = require(module); api.request = deny; api.get = deny;
}
const net = require('node:net');
net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
global.fetch = deny; global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs');
global.ee = ee;
const fixture = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const algorithms = JSON.parse(fs.readFileSync('vendor/earthengine-js/algorithms.json', 'utf8')).algorithms;
const signatures = Object.fromEntries(algorithms.map(row => [row.name.replace(/^algorithms\//, ''), {
  description: row.description, returns: row.returnType,
  args: (row.arguments || []).map(arg => ({name: arg.argumentName, type: arg.type,
    optional: !!arg.optional, description: arg.description,
    ...('defaultValue' in arg ? {default: arg.defaultValue} : {})}))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
ee.data.computeValue = deny;
const example = require('./examples/javascript/25_空影像表达式.js');
const image = ee.Image(ee.ImageCollection(fixture.source_id).first());
const expressions = example.buildExpressionImages(ee, image);
const outputs = example.buildWorkflow(ee, image, fixture);
const encode = value => ee.Serializer.encode(value);
if (attempts !== 0) throw Error('JavaScript SDK swallowed a network attempt');
console.log(JSON.stringify({attempts,
  constructor: encode(ee.Image()),
  expressions: Object.fromEntries(Object.entries(expressions).map(([k, v]) => [k, encode(v)])),
  workflow: Object.fromEntries(Object.entries(outputs).map(([k, v]) => [k, encode(v)]))}));
"""
    result = subprocess.run(
        [node, "-e", script, str(ROOT / "tests/fixtures/ee-empty-expression-wave67-v1.json")],
        cwd=ROOT, capture_output=True, text=True, timeout=45,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    payload = json.loads(result.stdout)
    assert payload["attempts"] == 0
    return payload


def official_wires(fixture):
    example = python_example()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        source = ee.Image(ee.ImageCollection(fixture["source_id"]).first())
        expressions = example.build_expression_images(ee, source)
        outputs = example.build_workflow(ee, source, fixture)
        encode = lambda value: ee.serializer.encode(value, for_cloud_api=False)
        python = {
            "constructor": encode(ee.Image()),
            "expressions": {name: encode(value) for name, value in expressions.items()},
            "workflow": {name: encode(value) for name, value in outputs.items()},
        }
    assert guard.evidence()["attempt_count"] == 0
    javascript = javascript_wires(fixture)
    return python, javascript
