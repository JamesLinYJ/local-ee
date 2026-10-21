/* Generate pinned EE integer/bitwise invocation fixtures offline.
 * Run: node scripts/ee_integer_fixtures.cjs > tests/fixtures/ee-integer-1.7.49.json
 * No user scripts, credentials, compute calls, or network access are used.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
global.window = globalThis;
const ee = require(path.join(root, 'vendor/earthengine-js/earthengine.cjs'));
global.ee = ee;
const raw = JSON.parse(fs.readFileSync(path.join(root, 'vendor/earthengine-js/algorithms.json'))).algorithms;
const signatures = Object.fromEntries(raw.map(a => [a.name.replace(/^algorithms\//, ''), {
  description: a.description, returns: a.returnType,
  args: (a.arguments || []).map(x => ({ name: x.argumentName, type: x.type,
    optional: !!x.optional, ...('defaultValue' in x ? { default: x.defaultValue } : {}) }))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
ee.data.computeValue = () => { throw Error('Integer fixture generation must never call a server'); };

const image = ee.Image.constant(25);
const values = {
  numberAnd: ee.Number(25).bitwiseAnd(21),
  numberOr: ee.Number(25).bitwiseOr(21),
  numberXor: ee.Number(25).bitwiseXor(21),
  numberLeftShift: ee.Number(20).leftShift(2),
  numberRightShift: ee.Number(20).rightShift(2),
  numberSignedRightShift: ee.Number(-8).rightShift(2),
  numberNotSmallestSigned: ee.Number(25).bitwiseNot(),
  numberBitCountNegative: ee.Number(-2).bitCount(),
  imageAnd: image.bitwiseAnd(ee.Image.constant(21)),
  imageOr: image.bitwiseOr(ee.Image.constant(21)),
  imageXor: image.bitwiseXor(ee.Image.constant(21)),
  imageLeftShift: image.leftShift(ee.Image.constant(2)),
  imageRightShift: image.rightShift(ee.Image.constant(2)),
  imageNot: image.bitwiseNot(),
  imageToDouble: image.toDouble(),
  imageToFloat: image.toFloat(),
  imageToInt16: image.toInt16(),
  imageToUint16: image.toUint16(),
  imageToInt32: image.toInt32(),
};
const expressions = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, ee.Serializer.encode(value)]));
process.stdout.write(JSON.stringify({
  sdk: '1.7.49',
  source_commit: 'e189e4b89e785019ea5642ea8e80cb644749cd4a',
  source: 'https://github.com/google/earthengine-api',
  expressions,
}, null, 2) + '\n');
