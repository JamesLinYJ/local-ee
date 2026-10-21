"""Shared compiler regressions from both unmodified, pinned SDK serializers."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
JAVASCRIPT = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('Parity fixture attempted networking'); }
for (const module of ['node:http', 'node:https']) {
  const api = require(module); api.request = deny; api.get = deny;
}
const net = require('node:net');
net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
global.fetch = deny;
global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs');
global.ee = ee;
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
const c = ee.ImageCollection('sentinel-2-l2a');
const joined = ee.ImageCollection(ee.Join.saveFirst('match').apply(
  c, c, ee.Filter.equals({leftField:'system:index', rightField:'system:index'})));
const values = {
  sequence: ee.List.sequence(0, 1, 99, 5),
  emptyKeys: ee.Dictionary({a:1}).values([]),
  missingDefault: ee.Dictionary({a:1}).get('missing', false),
  matrixMultiply: ee.Array([[1,2],[3,4]]).matrixMultiply([[1],[1]]),
  matrixSolve: ee.Array([[1,0],[1,1],[1,2]]).matrixSolve([[1],[3],[5]]),
  notNull: c.filter(ee.Filter.notNull(['cloud'])).size(),
  matchId: ee.Image(ee.Image(joined.first()).get('match')).get('system:index'),
  clippedBands: c.first().clip(ee.Geometry.Rectangle([100.1,30.1,100.9,30.9],null,false)).bandNames()
};
const expressions = Object.fromEntries(Object.entries(values).map(([k,v]) => [k,ee.Serializer.encode(v)]));
if (attempts !== 0) throw Error('SDK swallowed a network attempt');
console.log(JSON.stringify(expressions));
"""


@pytest.fixture(scope="module")
def parity_values():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for live official JavaScript serializer parity")
    result = subprocess.run([node, "-e", JAVASCRIPT], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    js = json.loads(result.stdout)
    ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
    c = ee.ImageCollection("sentinel-2-l2a")
    joined = ee.ImageCollection(ee.Join.saveFirst("match").apply(
        c, c, ee.Filter.equals(leftField="system:index", rightField="system:index")))
    py = {
        "sequence": ee.List.sequence(0, 1, 99, 5),
        "emptyKeys": ee.Dictionary({"a": 1}).values([]),
        "missingDefault": ee.Dictionary({"a": 1}).get("missing", False),
        "matrixMultiply": ee.Array([[1, 2], [3, 4]]).matrixMultiply([[1], [1]]),
        "matrixSolve": ee.Array([[1, 0], [1, 1], [1, 2]]).matrixSolve([[1], [3], [5]]),
        "notNull": c.filter(ee.Filter.notNull(["cloud"])).size(),
        "matchId": ee.Image(ee.Image(joined.first()).get("match")).get("system:index"),
        "clippedBands": c.first().clip(ee.Geometry.Rectangle(
            [100.1, 30.1, 100.9, 30.9], proj="EPSG:4326", geodesic=False)).bandNames(),
    }
    metadata, items, _ = synthetic_inputs()
    return js, {key: ee.serializer.encode(value, for_cloud_api=False)
                for key, value in py.items()}, [metadata], items


@pytest.mark.parametrize("case", ["sequence", "emptyKeys", "missingDefault", "matrixMultiply",
                                 "matrixSolve", "notNull", "matchId", "clippedBands"])
def test_python_and_javascript_reach_the_same_local_result(parity_values, case):
    javascript, python, metadata, items = parity_values
    left = compile_expression(javascript[case], metadata, items)
    right = compile_expression(python[case], metadata, items)
    assert left == right
    assert left["kind"] == "value"
