"""Pinned JavaScript SDK harness for the feature-preparation workflow."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]

JAVASCRIPT = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('Feature preparation attempted networking'); }
for (const name of ['node:http', 'node:https']) {
  const api = require(name); api.request = deny; api.get = deny;
}
const net = require('node:net');
net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
global.fetch = deny; global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs'); global.ee = ee;
const raw = JSON.parse(fs.readFileSync('vendor/earthengine-js/algorithms.json')).algorithms;
const signatures = Object.fromEntries(raw.map(a => [a.name.replace(/^algorithms\//, ''), {
  description: a.description, returns: a.returnType,
  args: (a.arguments || []).map(x => ({name: x.argumentName, type: x.type,
    optional: !!x.optional, description: x.description,
    ...('defaultValue' in x ? {default: x.defaultValue} : {})}))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
ee.data.computeValue = deny;
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const example = require('./examples/javascript/15_要素数据整理.js');
const workflows = {
  stations: example.buildStationWorkflow(ee, fixture.source),
  catalog: example.buildCatalogWorkflow(ee, fixture.source)
};
const expressions = Object.fromEntries(Object.entries(workflows).map(([mode, values]) =>
  [mode, Object.fromEntries(Object.entries(values).map(([name, value]) =>
    [name, ee.Serializer.encode(value)]))]));
if (attempts !== 0) throw Error(`SDK swallowed ${attempts} network attempts`);
process.stdout.write(JSON.stringify({expressions, attempts}));
"""


def javascript_expressions(fixture):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for pinned official JavaScript SDK parity")
    process = subprocess.run(
        [node, "-e", JAVASCRIPT], cwd=ROOT,
        input=json.dumps({"source": fixture}, ensure_ascii=False),
        capture_output=True, text=True, timeout=30,
    )
    assert process.returncode == 0, process.stderr
    document = json.loads(process.stdout)
    assert document["attempts"] == 0
    return document["expressions"]
