"""Offline parity for the official Python and JavaScript label-training APIs.

These checks compare SDK serialization and local compilation only. They do not
evaluate a Google Earth Engine request or claim engine-level compatibility.
"""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ee_label_training_reference import compile_inputs, load_fixture
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
METRICS = ("euclidean", "manhattan", "cosine")
JAVASCRIPT = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('Label-training parity attempted networking'); }
for (const name of ['node:http', 'node:https']) {
  const api = require(name); api.request = deny; api.get = deny;
}
const net = require('node:net');
net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
global.fetch = deny; global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs'); global.ee = ee;
const fixture = JSON.parse(fs.readFileSync('tests/fixtures/ee-label-training-v1.json'));
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
const source = ee.Image('wave24-sampling-a');
const directRemap = source.select(['label_code'])
  .remap([10, 20], [0, 1], null, 'label_code').rename('landcover');
const trainingImage = directRemap.addBands(source.select(['red', 'nir']));
const regions = ee.FeatureCollection(fixture.training_features);
const candidates = trainingImage.sampleRegions({collection: regions,
  properties: fixture.sample_properties, geometries: true});
const samples = candidates.filter(ee.Filter.notNull(fixture.sample_filter.not_null))
  .filter(ee.Filter.expression(fixture.sample_filter.expression))
  .limit(fixture.sample_filter.limit);
const outputs = {
  direct_remap: ee.Serializer.encode(directRemap),
  sample_table: ee.Serializer.encode(samples)
};
for (const metric of ['euclidean', 'manhattan', 'cosine']) {
  const classifier = ee.Classifier.minimumDistance(metric, 1).train({
    features: samples, classProperty: fixture.class_property,
    inputProperties: fixture.input_properties});
  const classified = ee.ImageCollection(fixture.collection_id).map(image =>
    ee.Image(image).select(['nir', 'red']).classify(classifier, fixture.output_name));
  outputs[metric] = ee.Serializer.encode(ee.ImageCollection(classified).first());
}
if (attempts) throw Error('Networking attempts: ' + attempts);
console.log(JSON.stringify({outputs, attempts}));
"""


@pytest.fixture(scope="module")
def javascript_descriptors():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for official JavaScript serializer parity")
    result = subprocess.run([node, "-e", JAVASCRIPT], cwd=ROOT,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["attempts"] == 0
    return output["outputs"]


def test_official_python_and_javascript_label_sdk_paths_compile_identically(javascript_descriptors):
    data = load_fixture()
    catalog, items, *_ = compile_inputs(data)
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        source = ee.Image("wave24-sampling-a")
        direct_remap = source.select(["label_code"]).remap(
            [10, 20], [0, 1], bandName="label_code",
        ).rename("landcover")
        training_image = direct_remap.addBands(source.select(["red", "nir"]))
        samples = training_image.sampleRegions(
            collection=ee.FeatureCollection(data["training_features"]),
            properties=data["sample_properties"], geometries=True,
        ).filter(ee.Filter.notNull(data["sample_filter"]["not_null"]))
        samples = samples.filter(
            ee.Filter.expression(data["sample_filter"]["expression"]),
        ).limit(data["sample_filter"]["limit"])
        expressions = {
            "direct_remap": direct_remap,
            "sample_table": samples,
        }
        for metric in METRICS:
            classifier = ee.Classifier.minimumDistance(metric, 1).train(
                features=samples, classProperty=data["class_property"],
                inputProperties=data["input_properties"],
            )
            classified = ee.ImageCollection(data["collection_id"]).map(
                lambda image: ee.Image(image).select(["nir", "red"]).classify(
                    classifier, data["output_name"],
                ),
            )
            expressions[metric] = ee.ImageCollection(classified).first()
        python = {
            name: compile_expression(
                ee.serializer.encode(value, for_cloud_api=False), catalog, items,
            )
            for name, value in expressions.items()
        }
    assert guard.evidence()["attempt_count"] == 0
    assert set(javascript_descriptors) == set(python)
    javascript = {
        name: compile_expression(expression, catalog, items)
        for name, expression in javascript_descriptors.items()
    }
    assert python == javascript
    for descriptor in python.values():
        validate(descriptor["process_graph"])
