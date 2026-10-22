"""Actual pinned Python/JavaScript SDK parity for Smile RF syntax and graphs."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_smile_rf_workflow import local_metadata, load_fixture


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ["red", "nir"]
JAVASCRIPT = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('Smile RF parity attempted networking'); }
for (const name of ['node:http', 'node:https']) {
  const api = require(name); api.request = deny; api.get = deny;
}
const net = require('node:net');
net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
global.fetch = deny; global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs'); global.ee = ee;
const fixture = JSON.parse(fs.readFileSync('tests/fixtures/ee-smile-rf-workflow-v1.json'));
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
function classifier(p) {
  return ee.Classifier.smileRandomForest(p.number_of_trees,
    p.variables_per_split, p.min_leaf_population, p.bag_fraction,
    p.max_nodes, p.seed);
}
function classifyTargets(trained) {
  return ee.ImageCollection(fixture.collection_id).filter(ee.Filter.eq('role', 'target'))
    .map(image => ee.Image(image).select(fixture.input_properties)
      .classify(trained, fixture.output_name));
}
const staticFeatures = ee.FeatureCollection(fixture.static_training_features);
const staticModel = classifier(fixture.example_parameters).train({
  features: staticFeatures, classProperty: fixture.class_property,
  inputProperties: fixture.input_properties, subsampling: 1, subsamplingSeed: 0});
const source = ee.Image(fixture.training_scene_id)
  .select([fixture.class_property, ...fixture.input_properties]);
const candidates = source.sampleRegions({
  collection: ee.FeatureCollection(fixture.training_regions),
  properties: fixture.sample_properties, geometries: true,
  scale: fixture.training_scale});
const samples = candidates.filter(ee.Filter.notNull(fixture.sample_filter.not_null))
  .filter(ee.Filter.expression(fixture.sample_filter.expression))
  .limit(fixture.sample_filter.limit);
const sampledModel = classifier(fixture.alternate_parameters).train({
  features: samples, classProperty: fixture.class_property,
  inputProperties: fixture.input_properties, subsampling: 1, subsamplingSeed: 0});
const outputs = {
  static_map: ee.Serializer.encode(classifyTargets(staticModel)),
  sampled_map: ee.Serializer.encode(classifyTargets(sampledModel)),
  sampled_table: ee.Serializer.encode(samples)
};
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


def test_official_python_and_javascript_smile_rf_paths_compile_identically(javascript_descriptors):
    data = load_fixture()
    catalog, items = local_metadata(data)
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        static_features = ee.FeatureCollection(data["static_training_features"])
        static_model = ee.Classifier.smileRandomForest(
            numberOfTrees=data["example_parameters"]["number_of_trees"],
            variablesPerSplit=data["example_parameters"]["variables_per_split"],
            minLeafPopulation=data["example_parameters"]["min_leaf_population"],
            bagFraction=data["example_parameters"]["bag_fraction"],
            maxNodes=data["example_parameters"]["max_nodes"],
            seed=data["example_parameters"]["seed"],
        ).train(
            features=static_features, classProperty=data["class_property"],
            inputProperties=SCHEMA, subsampling=1, subsamplingSeed=0,
        )
        source = ee.Image(data["training_scene_id"]).select(
            [data["class_property"], *SCHEMA],
        )
        candidates = source.sampleRegions(
            collection=ee.FeatureCollection(data["training_regions"]),
            properties=data["sample_properties"], geometries=True,
            scale=data["training_scale"],
        )
        samples = candidates.filter(
            ee.Filter.notNull(data["sample_filter"]["not_null"]),
        ).filter(
            ee.Filter.expression(data["sample_filter"]["expression"]),
        ).limit(data["sample_filter"]["limit"])
        parameters = data["alternate_parameters"]
        sampled_model = ee.Classifier.smileRandomForest(
            numberOfTrees=parameters["number_of_trees"],
            variablesPerSplit=parameters["variables_per_split"],
            minLeafPopulation=parameters["min_leaf_population"],
            bagFraction=parameters["bag_fraction"],
            maxNodes=parameters["max_nodes"],
            seed=parameters["seed"],
        ).train(
            features=samples, classProperty=data["class_property"],
            inputProperties=SCHEMA, subsampling=1, subsamplingSeed=0,
        )

        def classify_targets(trained):
            return ee.ImageCollection(data["collection_id"]).filter(
                ee.Filter.eq("role", "target"),
            ).map(lambda image: ee.Image(image).select(SCHEMA).classify(
                trained, data["output_name"],
            ))

        expressions = {
            "static_map": classify_targets(static_model),
            "sampled_map": classify_targets(sampled_model),
            "sampled_table": samples,
        }
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
        validate(descriptor.get("process_graph", {}))
