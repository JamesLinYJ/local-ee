"""Offline parity harness for the pinned Python and JavaScript EE clients."""
import json
import shutil
import subprocess


def semantic_wire(value, key=None):
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
function deny() { attempts++; throw Error('Random-split parity attempted networking'); }
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
const config = JSON.parse(fs.readFileSync('tests/fixtures/ee-random-split-v1.json'));
const source = JSON.parse(fs.readFileSync('tests/fixtures/' + config.source_fixture));
function regions() {
  const [rows, columns] = source.grid.shape_rows_columns;
  const [west, south, east, north] = source.extent;
  const features = [];
  for (let row = 0; row < rows; row++) for (let column = 0; column < columns; column++) {
    const x = west + (column + 0.5) * (east - west) / columns;
    const y = north - (row + 0.5) * (north - south) / rows;
    const cellId = `f0_r${row}_c${column}`;
    if (config.sample_regions_cells.includes(cellId))
      features.push(ee.Feature(ee.Geometry.Point([x, y]), {cell_id: cellId}));
  }
  return ee.FeatureCollection(features);
}
function matrixValues(matrix) { return {
  array: matrix.array(), order: matrix.order(), accuracy: matrix.accuracy(),
  kappa: matrix.kappa(), consumers_accuracy: matrix.consumersAccuracy(),
  producers_accuracy: matrix.producersAccuracy(), fscore_beta_2: matrix.fscore(2)
}; }
function workflow(mode) {
  const image = ee.Image(source.scene_id).select(source.sample_bands);
  let candidates, rowKeys = null;
  if (mode === 'image_sample_v2') {
    candidates = image.sample({seed: source.sample_seed, dropNulls: false, geometries: true});
  } else {
    candidates = image.sampleRegions({collection: regions(), properties: ['cell_id'], geometries: true});
    rowKeys = ['cell_id'];
  }
  const args = {columnName: config.random_column, seed: config.seed,
    distribution: config.distribution};
  if (rowKeys !== null) args.rowKeys = rowKeys;
  const randomized = candidates.randomColumn(args);
  const complete = randomized.filter(ee.Filter.notNull([
    config.class_property, ...config.input_properties, config.random_column]));
  const training = complete.filter(ee.Filter.lt(config.random_column, config.threshold));
  const validation = complete.filter(ee.Filter.gte(config.random_column, config.threshold));
  const p = source.rf_parameters;
  const classifier = ee.Classifier.smileRandomForest(
    p.number_of_trees, p.variables_per_split, p.min_leaf_population,
    p.bag_fraction, p.max_nodes, p.seed
  ).train(training, config.class_property, config.input_properties, 1, 0);
  const predictions = validation.classify(classifier, config.output_name);
  const matrix = predictions.errorMatrix(
    config.class_property, config.output_name, config.class_order);
  const metrics = matrixValues(matrix);
  const classified = ee.Image(source.scene_id).select(config.input_properties)
    .classify(classifier, config.output_name);
  return {
    candidates, randomized, complete, training, validation, predictions, classified,
    band_order: mode === 'image_sample_v2' ? candidates.get('band_order') : null,
    property_names: mode === 'image_sample_v2' ? candidates.propertyNames() : null,
    training_matrix_array: classifier.confusionMatrix().array(),
    validation_array: metrics.array, validation_order: metrics.order,
    validation_accuracy: metrics.accuracy, validation_kappa: metrics.kappa,
    validation_consumers_accuracy: metrics.consumers_accuracy,
    validation_producers_accuracy: metrics.producers_accuracy,
    validation_fscore_beta_2: metrics.fscore_beta_2
  };
}
const outputs = {};
for (const mode of ['image_sample_v2', 'sample_regions_v1']) {
  const values = workflow(mode);
  outputs[mode] = Object.fromEntries(Object.entries(values).map(([name, value]) =>
    [name, value === null ? null : ee.Serializer.encode(value)]));
}
if (attempts !== 0) throw Error(`SDK swallowed ${attempts} network attempt(s)`);
console.log(JSON.stringify({outputs, attempts}));
"""


def javascript_expressions(root):
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node is required for official JavaScript serializer parity")
    result = subprocess.run(
        [node, "-e", JAVASCRIPT], cwd=root, capture_output=True, text=True, timeout=20,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    document = json.loads(result.stdout)
    if document["attempts"] != 0:
        raise AssertionError("JavaScript SDK attempted network access")
    return document["outputs"]
