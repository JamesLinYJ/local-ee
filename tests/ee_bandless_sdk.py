"""Offline wires from the pinned official Python and JavaScript EE SDKs."""
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
PYTHON_EXAMPLE = ROOT / "examples/72_GEE_python_bandless_accumulator.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/26_零波段累加.js"
FIXTURE = ROOT / "tests/fixtures/ee-bandless-wave68-v1.json"


def load_python_example():
    spec = importlib.util.spec_from_file_location("wave68_bandless_python", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def wire_digest(value):
    payload = json.dumps(_semantic_wire(value), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_graph(value, local=None, parent=None, active=frozenset()):
    """Resolve CompoundValue references without trusting SDK scope numbering."""
    local, parent = local or {}, parent or {}
    if isinstance(value, dict) and value.get("type") == "CompoundValue":
        pairs = value.get("scope", [])
        scope = dict(pairs)
        if len(scope) != len(pairs):
            raise ValueError("official SDK graph contains duplicate scope identifiers")
        return {"type": "CompoundValue", "value": canonical_graph(
            value.get("value"), scope, local, active,
        )}
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


def _javascript_wires():
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node is required for the official JavaScript SDK comparison")
    script = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('Wave68 SDK wire generation attempted networking'); }
for (const name of ['node:http', 'node:https']) { const api = require(name); api.request = deny; api.get = deny; }
const net = require('node:net'); net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
global.fetch = deny; global.window = globalThis;
const ee = require(process.cwd() + '/vendor/earthengine-js/earthengine.cjs'); global.ee = ee;
const raw = JSON.parse(fs.readFileSync('vendor/earthengine-js/algorithms.json', 'utf8')).algorithms;
const signatures = Object.fromEntries(raw.map(a => [a.name.replace(/^algorithms\//, ''), {
  description: a.description, returns: a.returnType,
  args: (a.arguments || []).map(x => ({name: x.argumentName, type: x.type,
    optional: !!x.optional, description: x.description,
    ...('defaultValue' in x ? {default: x.defaultValue} : {})}))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
ee.data.computeValue = deny;
const fixture = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const outputs = require('./examples/javascript/26_零波段累加.js').buildWorkflow(ee, fixture);
const wires = {constructor: ee.Serializer.encode(ee.Image())};
for (const [name, value] of Object.entries(outputs)) wires[name] = ee.Serializer.encode(value);
if (attempts !== 0) throw Error(`JavaScript SDK swallowed ${attempts} network attempts`);
console.log(JSON.stringify({client:'javascript', network_attempts:attempts, wires}));
"""
    result = subprocess.run(
        [node, "-e", script, str(FIXTURE)], cwd=ROOT,
        capture_output=True, text=True, timeout=45,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout)


def official_wires(fixture):
    example = load_python_example()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        outputs = example.build_workflow(ee, fixture)
        python = {"client": "python", "network_attempts": 0,
                  "wires": {"constructor": ee.serializer.encode(
                      ee.Image(), for_cloud_api=False,
                  )}}
        python["wires"].update({name: ee.serializer.encode(
            value, for_cloud_api=False,
        ) for name, value in outputs.items()})
    assert guard.evidence()["attempt_count"] == 0
    javascript = _javascript_wires()
    for payload in (python, javascript):
        payload["wire_sha256"] = {
            name: wire_digest(wire) for name, wire in payload["wires"].items()
        }
    return python, javascript
