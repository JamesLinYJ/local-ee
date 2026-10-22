"""Live pinned Python/JS serializers feeding the same raster classifier compiler."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ee_raster_classification_helpers import compile_inputs, load_fixture
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
JAVASCRIPT = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('Classifier parity attempted networking'); }
for (const name of ['node:http', 'node:https']) {
  const api = require(name); api.request = deny; api.get = deny;
}
const net = require('node:net');
net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
global.fetch = deny; global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs'); global.ee = ee;
const fixture = JSON.parse(fs.readFileSync('tests/fixtures/ee-raster-classification-v1.json'));
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
const outputs = {};
for (const metric of ['euclidean', 'manhattan', 'cosine']) {
  const classifier = ee.Classifier.minimumDistance(metric).train({
    features: ee.FeatureCollection(fixture.training_rows.map(row => ee.Feature(null, row))),
    classProperty: fixture.class_property, inputProperties: fixture.input_properties
  });
  const source = ee.ImageCollection(fixture.collection_id);
  outputs[metric] = ee.Serializer.encode(source.map(image => image.select(['aux','red','nir'])
    .classify({classifier: classifier, outputName: fixture.output_name})));
}
if (attempts) throw Error('Networking attempts: ' + attempts);
console.log(JSON.stringify({outputs, attempts}));
"""


@pytest.fixture(scope="module")
def serialized():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for actual official JavaScript serialization")
    process = subprocess.run([node, "-e", JAVASCRIPT], cwd=ROOT,
                             capture_output=True, text=True, timeout=15)
    assert process.returncode == 0, process.stderr
    javascript = json.loads(process.stdout)
    assert javascript["attempts"] == 0
    return javascript["outputs"]


@pytest.mark.parametrize("metric", ["euclidean", "manhattan", "cosine"])
def test_official_python_and_js_raster_classifier_graphs_match(serialized, metric):
    data = load_fixture()
    catalog, items, *_ = compile_inputs(data)
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        classifier = ee.Classifier.minimumDistance(metric).train(
            features=ee.FeatureCollection([ee.Feature(None, row) for row in data["training_rows"]]),
            classProperty=data["class_property"], inputProperties=data["input_properties"],
        )
        value = ee.ImageCollection(data["collection_id"]).map(
            lambda image: image.select(["aux", "red", "nir"]).classify(
                classifier=classifier, outputName=data["output_name"]))
        python = compile_expression(ee.serializer.encode(value, for_cloud_api=False), catalog, items)
        javascript = compile_expression(serialized[metric], catalog, items)
    assert guard.evidence()["attempt_count"] == 0
    assert python == javascript
    validate(python["process_graph"])
