"""Independent references and official JavaScript SDK workflow fixture."""
from __future__ import annotations

from collections import Counter
from fractions import Fraction


JAVASCRIPT = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('RF validation parity attempted networking'); }
for (const name of ['node:http', 'node:https']) {
  const api = require(name); api.request = deny; api.get = deny;
}
const net = require('node:net');
net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
global.fetch = deny; global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs'); global.ee = ee;
const fixture = JSON.parse(fs.readFileSync('tests/fixtures/ee-rf-validation-workflow-v1.json'));
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

function featureCollection(rows) {
  return ee.FeatureCollection(rows.map((row, index) => {
    const properties = Object.fromEntries(Object.entries(row).filter(([key]) => key !== 'id'));
    properties['system:index'] = row.id;
    return ee.Feature(ee.Geometry.Point([100 + index / 100, 30]), properties);
  }));
}
function regions() {
  return ee.FeatureCollection(fixture.training_regions.map((row, index) =>
    ee.Feature(ee.Geometry.Point(fixture.grid.pixel_centers[row.pixel]), {
      'system:index': `region-${String(index).padStart(2, '0')}`,
      site: row.site, keep: row.keep
    })));
}
function classifier() {
  const p = fixture.classifier_parameters;
  return ee.Classifier.smileRandomForest(p.number_of_trees, p.variables_per_split,
    p.min_leaf_population, p.bag_fraction, p.max_nodes, p.seed);
}
function train(mode) {
  let training;
  if (mode === 'inline') {
    training = featureCollection(fixture.static_training_rows);
  } else {
    const image = ee.Image(fixture.training_scene_id)
      .select([fixture.class_property, ...fixture.input_properties]);
    training = image.sampleRegions({collection: regions(), properties: fixture.region_properties,
      geometries: true, scale: fixture.training_scale})
      .filter(ee.Filter.notNull(fixture.sample_filter.not_null))
      .filter(ee.Filter.expression(fixture.sample_filter.expression))
      .limit(fixture.sample_filter.limit);
  }
  return {training, model: classifier().train({features: training,
    classProperty: fixture.class_property, inputProperties: fixture.input_properties,
    subsampling: 1, subsamplingSeed: 0})};
}
const outputs = {};
for (const mode of ['inline', 'sampled']) {
  const {training, model} = train(mode);
  const trainingMatrix = model.confusionMatrix();
  const validation = featureCollection(fixture.validation_rows)
    .classify(model, fixture.output_name);
  const validationMatrix = validation.errorMatrix(fixture.class_property,
    fixture.output_name, fixture.class_order);
  const accessors = matrix => ({array: matrix.array(), order: matrix.order(),
    accuracy: matrix.accuracy(), kappa: matrix.kappa(),
    consumers_accuracy: matrix.consumersAccuracy(),
    producers_accuracy: matrix.producersAccuracy(), fscore_beta_2: matrix.fscore(2)});
  outputs[mode] = {
    training_predictions: ee.Serializer.encode(training.classify(model, fixture.output_name)),
    validation_predictions: ee.Serializer.encode(validation),
    training_values: Object.fromEntries(Object.entries(accessors(trainingMatrix))
      .map(([key, value]) => [key, ee.Serializer.encode(value)])),
    validation_values: Object.fromEntries(Object.entries(accessors(validationMatrix))
      .map(([key, value]) => [key, ee.Serializer.encode(value)]))
  };
}
if (attempts) throw Error('Networking attempts: ' + attempts);
console.log(JSON.stringify({outputs, attempts}));
"""


def expanded_matrix_rows(spec: dict) -> list[dict]:
    rows = []
    for row in spec["rows"]:
        repeat = row.get("repeat", 1)
        rows.extend({key: value for key, value in row.items() if key != "repeat"}
                    for _ in range(repeat))
    return rows


def _fraction(value: int, denominator: int):
    return None if denominator == 0 else Fraction(value, denominator)


def confusion_from_raw_rows(rows: list[dict], order: list[int]):
    """Count valid, in-order labels without using the runtime matrix code."""
    positions = {label: index for index, label in enumerate(order)}
    counts = Counter()
    complete = 0
    evaluated = 0
    for row in rows:
        if ("actual" not in row or "predicted" not in row
                or row["actual"] is None or row["predicted"] is None):
            continue
        actual, predicted = row["actual"], row["predicted"]
        if (type(actual) is not int or type(predicted) is not int
                or abs(actual) > 2**53 or abs(predicted) > 2**53):
            raise ValueError("Reference labels must be exact integers")
        complete += 1
        if actual in positions and predicted in positions:
            counts[(actual, predicted)] += 1
            evaluated += 1
    matrix = [[counts[(actual, predicted)] for predicted in order]
              for actual in order]
    return complete, evaluated, matrix


def exact_metrics(matrix: list[list[int]], beta: Fraction = Fraction(2, 1)):
    """Return rational matrix metrics with undefined denominators as None."""
    if any(len(row) != len(matrix) for row in matrix):
        raise ValueError("Confusion matrix must be square")
    classes = len(matrix)
    total = sum(map(sum, matrix))
    trace = sum(matrix[index][index] for index in range(classes))
    actual = [sum(row) for row in matrix]
    predicted = [sum(matrix[row][column] for row in range(classes))
                 for column in range(classes)]
    chance_numerator = sum(left * right for left, right in zip(actual, predicted))
    kappa_denominator = total * total - chance_numerator
    beta_squared = beta * beta
    return {
        "accuracy": _fraction(trace, total),
        "kappa": (None if kappa_denominator == 0 else
                  Fraction(total * trace - chance_numerator, kappa_denominator)),
        "consumers_accuracy": [
            _fraction(matrix[index][index], actual[index])
            for index in range(classes)
        ],
        "producers_accuracy": [
            _fraction(matrix[index][index], predicted[index])
            for index in range(classes)
        ],
        "fscore_beta_2": [
            (None if beta_squared * actual[index] + predicted[index] == 0 else
             Fraction((1 + beta_squared) * matrix[index][index],
                      beta_squared * actual[index] + predicted[index]))
            for index in range(classes)
        ],
    }
