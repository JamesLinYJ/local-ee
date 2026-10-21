/* Generate pinned EE constant-band expressions with the official SDK offline.
 * Run: node scripts/ee_constant_fixtures.cjs > tests/fixtures/ee-constant-1.7.49.json
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
  description: a.description,
  returns: a.returnType,
  args: (a.arguments || []).map(x => ({ name: x.argumentName, type: x.type,
    optional: !!x.optional, ...('defaultValue' in x ? { default: x.defaultValue } : {}) }))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
ee.data.computeValue = () => { throw Error('Constant fixture generation must never call a server'); };

const collection = ee.ImageCollection('sentinel-2-l2a')
  .filterDate(ee.Date(1000), ee.Date(2000));
const first = ee.Image(collection.first());
const masked = first.updateMask(first.select('SCL').neq(9));
const expressions = {
  firstAddScalar: first.addBands(ee.Image.constant(1).rename('one')).select('one'),
  firstAddMultiband: first.addBands(
    ee.Image.constant([1, 16777219]).rename(['one', 'large'])
  ).select(['one', 'large']),
  firstAddDateMillis: first.addBands(
    ee.Image.constant(first.date().millis()).rename('millis')
  ).select('millis'),
  firstAddConstantArithmetic: first.addBands(
    ee.Image.constant(2).multiply(3).add(1).rename('calculated')
  ).select('calculated'),
  overwriteAndNames: first.select(['red', 'nir']).addBands(
    ee.Image.constant([101, 202]).rename(['red', 'nir']), ['red', 'nir'], true
  ).select(['red', 'nir']),
  maskedRasterAddConstant: masked.addBands(
    ee.Image.constant(7).rename('valid_constant')
  ).select('valid_constant'),
  rasterAddClippedConstant: first.addBands(
    ee.Image.constant(1).clip(ee.Geometry.Rectangle([0, 0, 1, 1], null, false))
      .rename('clipped')
  ).select('clipped'),
  mapStaticConstantMean: collection.map(image => image.addBands(
    ee.Image.constant(7).rename('static')
  ).select('static')).mean(),
  mapDateToBands: collection.map(image => image.addBands(
    ee.Image.constant(image.date().millis()).rename('millis')
  ).select('millis')).toBands(),
  standaloneConstant: ee.Image.constant(1).add(2),
  unboundClippedConstant: ee.Image.constant(1).clip(
    ee.Geometry.Rectangle([0, 0, 1, 1], null, false)
  ),
  unsupportedProjectionQuery: ee.Image.constant(1).projection().crs(),
};
const localCollection = ee.ImageCollection('sentinel-2-l2a');
const localFirst = ee.Image(localCollection.first());
const nir = localFirst.select('nir');
const staticCollection = localCollection.map(image => image.addBands(
  ee.Image.constant(7).rename('static')
).select('static'));
const dateCollection = localCollection.map(image => image.addBands(
  ee.Image.constant(image.date().millis()).rename('millis')
).select('millis'));
const rasterExpressions = {
  boundScalar: localFirst.addBands(ee.Image.constant(1).rename('one')).select('one'),
  boundLarge: localFirst.addBands(ee.Image.constant(16777219).rename('large')).select('large'),
  boundDate: localFirst.addBands(ee.Image.constant(localFirst.date().millis()).rename('date'))
    .select('date'),
  boundArithmetic: localFirst.addBands(
    ee.Image.constant(2).multiply(3).add(1).rename('arithmetic')
  ).select('arithmetic'),
  maskedConstant: localFirst.select('nir').updateMask(nir.gt(0)).addBands(
    ee.Image.constant(7).rename('valid_constant')
  ).select(['nir', 'valid_constant']),
  allMaskedConstant: localFirst.select('nir').updateMask(ee.Image.constant(0)).addBands(
    ee.Image.constant(7).rename('valid_constant')
  ).select('valid_constant'),
  emptySourceConstant: localFirst.select('blue').addBands(
    ee.Image.constant(7).rename('valid_constant')
  ).select('valid_constant'),
  staticMean: staticCollection.mean(),
  dateMean: dateCollection.mean(),
  dateCount: dateCollection.count(),
  dateSd: dateCollection.reduce(ee.Reducer.sampleStdDev()),
  dateToBands: dateCollection.toBands(),
  boundFloat: localFirst.addBands(
    ee.Image.constant(16777219).rename('value').toFloat()
  ).select('value'),
  boundOverwrite: localFirst.select(['red', 'nir']).addBands(
    ee.Image.constant([101, 202]).rename(['red', 'nir']), ['red', 'nir'], true
  ).select(['red', 'nir']),
};

process.stdout.write(JSON.stringify({
  sdk: '1.7.49',
  source_commit: 'e189e4b89e785019ea5642ea8e80cb644749cd4a',
  source: 'https://github.com/google/earthengine-api',
  expressions: Object.fromEntries(Object.entries(expressions).map(
    ([name, value]) => [name, ee.Serializer.encode(value)]
  )),
  raster_expressions: Object.fromEntries(Object.entries(rasterExpressions).map(
    ([name, value]) => [name, ee.Serializer.encode(value)]
  )),
}, null, 2) + '\n');
