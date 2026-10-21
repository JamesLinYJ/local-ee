/* Generate map-metadata expressions with the unmodified pinned EE JS SDK.
 * node scripts/ee_metadata_fixtures.cjs > tests/fixtures/ee-metadata-1.7.49.json
 * The expressions are syntax contracts only; no network-backed compute runs.
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
  args: (a.arguments || []).map(x => ({ name: x.argumentName, type: x.type, optional: !!x.optional,
    description: x.description, ...('defaultValue' in x ? {default: x.defaultValue} : {}) }))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
ee.data.computeValue = () => { throw Error('Fixture generator must never call a server'); };

const collection = ee.ImageCollection('sentinel-2-l2a');
const values = {
  mappedIndex: collection.map(image => image.set('mapped:index', image.get('system:index')))
    .aggregate_array('mapped:index'),
  mappedMissingProperty: collection.map(image => image.set('mapped:missing', image.get('local:missing')))
    .aggregate_array('mapped:missing'),
  mappedDateMillis: collection.map(image => image.set('mapped:time', image.date().millis()))
    .aggregate_array('mapped:time'),
  mappedDateYear: collection.map(image => image.set('mapped:year', image.date().get('year')))
    .aggregate_array('mapped:year'),
  mappedGeometry: collection.map(image => image.set('mapped:geometry', image.geometry()))
    .aggregate_array('mapped:geometry'),
  mappedPropertyNames: collection.map(image => image.set('mapped:properties', image.propertyNames()))
    .aggregate_array('mapped:properties'),
  mappedPixelAndProperties: collection.map(image => image.normalizedDifference(['nir', 'red'])
    .rename('nd').copyProperties(image, ['system:time_start', 'system:index'])
    .set('mapped:time', image.date().millis())
    .set('mapped:index', image.get('system:index')))
    .mean(),
  mappedDropNulls: collection.map(image => ee.Algorithms.If(
    image.date().millis().lt(1500), null, image), true).aggregate_array('system:index'),
  nestedListMapShadow: collection.map(image => image.set('nested:static', ee.List([
    ee.Image(collection.first())
  ]).map(image => ee.Image(image).get('system:index')))).aggregate_array('nested:static'),
  capturedStaticMetadata: collection.map(image => image.set('captured', ee.Image(collection.first()).get('system:index')))
    .aggregate_array('captured'),
};

const serialized = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, ee.Serializer.encode(value)]));
process.stdout.write(JSON.stringify({sdk: '1.7.49', source_commit: 'e189e4b89e785019ea5642ea8e80cb644749cd4a', expressions: serialized}, null, 2) + '\n');
