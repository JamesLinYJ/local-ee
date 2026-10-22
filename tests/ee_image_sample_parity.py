"""Offline official-SDK semantic parity for Image.sample and sampled RF graphs."""
import json
import shutil
import subprocess


def semantic_wire(value, key=None):
    """Normalize SDK JSON strings and numeric lexemes for graph parity."""
    if key in {"spec", "rows"} and type(value) is str:
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass
    if type(value) is dict:
        return {name: semantic_wire(item, name) for name, item in value.items()}
    if type(value) is list:
        return [semantic_wire(item) for item in value]
    if type(value) in (int, float):
        return ("number", float(value).hex())
    return value


JAVASCRIPT = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('Image.sample parity attempted networking'); }
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
const fixture = JSON.parse(fs.readFileSync('tests/fixtures/ee-image-sample-rf-v1.json'));
const image = ee.Image(fixture.scene_id).select(fixture.sample_bands);
const candidates = image.sample({
  region: ee.Geometry(fixture.explicit_region), factor: 0.5,
  seed: fixture.sample_seed, dropNulls: false, tileScale: 1, geometries: true
});
const complete = candidates.filter(ee.Filter.notNull(
  [fixture.class_property, ...fixture.input_properties]));
const training = complete.filter(ee.Filter.gt('nir', -1)).limit(fixture.training_limit);
const p = fixture.rf_parameters;
const classifier = ee.Classifier.smileRandomForest(
  p.number_of_trees, p.variables_per_split, p.min_leaf_population,
  p.bag_fraction, p.max_nodes, p.seed
).train(training, fixture.class_property, fixture.input_properties, 1, 0);
const validation = ee.FeatureCollection(fixture.validation_features.map(feature =>
  ee.Feature(feature.geometry, feature.properties)));
const predictions = validation
  .classify(classifier, fixture.output_name);
const matrix = predictions.errorMatrix(
  fixture.class_property, fixture.output_name, fixture.class_order);
const classified = ee.Image(fixture.scene_id).select(['red', 'nir'])
  .classify(classifier, fixture.output_name);
const values = {
  candidates, training, predictions, classified,
  bandOrder: candidates.get('band_order'),
  propertyNames: candidates.propertyNames(),
  matrixArray: matrix.array(), matrixOrder: matrix.order(),
  matrixAccuracy: matrix.accuracy(), matrixKappa: matrix.kappa(),
  matrixConsumers: matrix.consumersAccuracy(),
  matrixProducers: matrix.producersAccuracy(), matrixFscore: matrix.fscore(2)
};
if (attempts !== 0) throw Error('SDK swallowed a network attempt');
console.log(JSON.stringify(Object.fromEntries(
  Object.entries(values).map(([key, value]) => [key, ee.Serializer.encode(value)]))));
"""


def javascript_expressions(root):
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node is required for official JavaScript SDK parity")
    result = subprocess.run(
        [node, "-e", JAVASCRIPT], cwd=root, capture_output=True, text=True, timeout=20,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)
