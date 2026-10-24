/* Generate pinned, offline EE mask-weight calls and numeric fixtures.
 * Run: node scripts/ee_mask_weights_fixtures.cjs > tests/fixtures/ee-mask-weights-wave64-v1.json
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const https = require('node:https');
const net = require('node:net');
const tls = require('node:tls');

const attempts = [];
const deny = name => (..._args) => {
  attempts.push(name);
  throw Error(`Mask-weight fixture attempted network operation: ${name}`);
};
for (const [owner, method, name] of [
  [http, 'request', 'http.request'], [http, 'get', 'http.get'],
  [https, 'request', 'https.request'], [https, 'get', 'https.get'],
  [net, 'connect', 'net.connect'], [tls, 'connect', 'tls.connect'],
]) owner[method] = deny(name);
net.Socket.prototype.connect = deny('net.Socket.connect');
globalThis.fetch = deny('fetch');

const root = path.resolve(__dirname, '..');
global.window = globalThis;
const ee = require(path.join(root, 'vendor/earthengine-js/earthengine.cjs'));
global.ee = ee;
const raw = JSON.parse(fs.readFileSync(
  path.join(root, 'vendor/earthengine-js/algorithms.json'), 'utf8',
)).algorithms;
const signatures = Object.fromEntries(raw.map(algorithm => [
  algorithm.name.replace(/^algorithms\//, ''), {
    description: algorithm.description,
    returns: algorithm.returnType,
    args: (algorithm.arguments || []).map(argument => ({
      name: argument.argumentName,
      type: argument.type,
      optional: !!argument.optional,
      ...('defaultValue' in argument ? { default: argument.defaultValue } : {}),
    })),
  },
]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
ee.data.computeValue = deny('ee.data.computeValue');
ee.data.send_ = deny('ee.data.send_');

function spec(operation) {
  return JSON.stringify({ op: operation, v: 1 });
}

const maskData = {
  schema: 'local-ee-mask-weights-wave64/v1',
  sdk: '1.7.49',
  source_commit: 'e189e4b89e785019ea5642ea8e80cb644749cd4a',
  operations: ['validity', 'update', 'apply'],
  cases: [
    {
      name: 'validity-finite-values-and-no-data',
      spec: spec('validity'),
      bands: [[-1.25, 0, '-0.0', 1e300, 1.7976931348623157e308, 5e-324, 'NaN']],
      expected: [1, 1, 1, 1, 1, 1, 0],
    },
    {
      name: 'update-replaces-and-no-data-clears-weight',
      spec: spec('update'),
      bands: [[0, 0.25, 1, 0.5, 0.75, 1, 1, 1],
        ['NaN', 0.75, 0.25, 'NaN', 0, 0.5, 0.9999999990686774, 5e-324]],
      expected: [0, 0.75, 0.25, 0, 0, 0.5, 0.9999999990686774, 5e-324],
    },
    {
      name: 'apply-preserves-raw-values-without-weight-multiplication',
      spec: spec('apply'),
      bands: [[1e300, -7.5, 'NaN', 3.141592653589793, '-0.0', 5e-324,
        1.7976931348623157e308, 1.7976931348623157e308],
        [0.25, 1, 0.5, 0, 0.75, 5e-324, 5e-324, 0]],
      expected: [1e300, -7.5, 'NaN', 'NaN', '-0.0', 5e-324,
        1.7976931348623157e308, 'NaN'],
    },
  ],
  composite: {
    name: 'two-replacement-updates-then-raw-value-apply',
    initial_weights: [1, 0.5, 0, 0.25, 1, 0.75],
    new_masks: [
      [0.25, 0.75, 1, 'NaN', 0, 0.5],
      [0.9999999990686774, 0.125, 0.4, 0.6, 1, 'NaN'],
    ],
    raw_values: [100, -32, 9, 1e300, '-0.0', 5e-324],
    expected_weights: [0.9999999990686774, 0.125, 0, 0, 0, 0],
    expected_values: [100, -32, 'NaN', 'NaN', 'NaN', 'NaN'],
  },
  invalid_specs: [
    '',
    '{"op":"validity","op":"apply","v":1}',
    '{"op":"validity","v":1 }',
    '{"op":"validity","v":1,"extra":0}',
    '{"op":"unknown","v":1}',
    '{"op":"validity","v":2}',
    '{"op":1,"v":1}',
    '{"v":1,"op":"validity"}',
  ],
  invalid_tile_cases: [
    { name: 'validity-positive-infinity', spec: spec('validity'), bands: [['Infinity']] },
    { name: 'validity-negative-infinity', spec: spec('validity'), bands: [['-Infinity']] },
    { name: 'update-old-weight-no-data', spec: spec('update'), bands: [['NaN'], [0.5]] },
    { name: 'update-old-weight-negative', spec: spec('update'), bands: [[-0.0001], [0.5]] },
    { name: 'update-old-weight-above-one', spec: spec('update'), bands: [[1.0001], [0.5]] },
    { name: 'update-mask-negative', spec: spec('update'), bands: [[0.5], [-0.0001]] },
    { name: 'update-mask-above-one', spec: spec('update'), bands: [[0.5], [1.0001]] },
    { name: 'update-mask-infinity', spec: spec('update'), bands: [[0], ['Infinity']] },
    { name: 'update-zero-old-weight-negative-infinity', spec: spec('update'), bands: [[0], ['-Infinity']] },
    { name: 'update-wrong-band-count', spec: spec('update'), bands: [[1]] },
    { name: 'apply-weight-no-data', spec: spec('apply'), bands: [[7], ['NaN']] },
    { name: 'apply-weight-negative', spec: spec('apply'), bands: [[7], [-0.0001]] },
    { name: 'apply-weight-above-one', spec: spec('apply'), bands: [[7], [1.0001]] },
    { name: 'apply-weight-infinity', spec: spec('apply'), bands: [[7], ['Infinity']] },
    { name: 'apply-hidden-raw-infinity-at-zero-weight', spec: spec('apply'), bands: [['Infinity'], [0]] },
    { name: 'apply-hidden-raw-negative-infinity-at-zero-weight', spec: spec('apply'), bands: [['-Infinity'], [0]] },
    { name: 'apply-wrong-band-count', spec: spec('apply'), bands: [[7]] },
    { name: 'empty-input', spec: spec('validity'), bands: [] },
    { name: 'mismatched-band-width', spec: spec('update'), bands: [[1, 1], [0.5]] },
  ],
};
maskData.case_count = maskData.cases.length + 1;
maskData.pixel_count = maskData.cases.reduce((sum, row) => sum + row.expected.length, 0)
  + maskData.composite.expected_values.length;

const collection = ee.ImageCollection('sentinel-2-l2a');
const scene = ee.Image(collection.first());
const source = scene.select(['red', 'nir']).toDouble();
const singleWeight = ee.Image.constant(0.25).rename('weight');
const reversedWeights = ee.Image.constant([0.25, 0.75]).rename(['nir', 'red']);
const weighted = source.updateMask(singleWeight);
const stacked = weighted.updateMask(ee.Image.constant([0.75, 0.5]).rename(['red', 'nir']));
const weightedInputMask = scene.select('SCL').eq(4).updateMask(singleWeight);
const mappedMaskGetter = collection.map(image => image.select('nir')
  .updateMask(ee.Image.constant(0.25)).mask());
const expressions = {
  updateFractionalBroadcast: weighted,
  updateFractionalByOrder: source.updateMask(reversedWeights),
  stackedReplacementUpdate: stacked,
  maskGetter: weighted.mask(),
  maskGetterNullDefault: weighted.mask(null),
  weightedMaskInput: source.select('red').updateMask(weightedInputMask).mask(),
  maskGetterByOrder: source.updateMask(reversedWeights).mask(),
  stackedMaskGetter: stacked.mask(),
  selectCarriesWeights: weighted.select('nir'),
  selectMaskGetter: weighted.select('nir').mask(),
  renameCarriesWeights: weighted.rename(['R', 'N']),
  renameMaskGetter: weighted.rename(['R', 'N']).mask(),
  addBandsCarriesWeights: scene.select('blue').addBands(weighted.rename(['R', 'N'])),
  addBandsMaskGetter: scene.select('blue').addBands(weighted.rename(['R', 'N'])).mask(),
  binaryUpdateCompatibility: scene.select('nir').updateMask(scene.select('SCL').neq(9)),
  weightedArithmetic: weighted.select('red').multiply(2),
  weightedUnmask: weighted.unmask(0),
  weightedMapMaskGetter: mappedMaskGetter,
  mappedMaskGetterMean: mappedMaskGetter.mean(),
  mappedMaskGetterToBands: mappedMaskGetter.toBands(),
  weightedCollectionMean: collection.map(image => image.select('nir')
    .updateMask(ee.Image.constant(0.25))).mean(),
};
maskData.sdk_expressions = Object.fromEntries(Object.entries(expressions).map(
  ([name, value]) => [name, ee.Serializer.encode(value)],
));
maskData.tripwire_attempts = attempts.length;
if (attempts.length !== 0) throw Error(`network tripwire recorded ${attempts.length} attempt(s)`);
process.stdout.write(`${JSON.stringify(maskData, null, 2)}\n`);
