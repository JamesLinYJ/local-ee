/* Generate pinned EE unmask invocation fixtures without contacting a server.
 * Run: node scripts/ee_mask_fixtures.cjs > tests/fixtures/ee-mask-1.7.49.json
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
ee.data.computeValue = () => { throw Error('Mask fixture generation must never call a server'); };

const image = ee.Image.constant([11, 22]).rename(['red', 'nir']);
const values = {
  defaultValue: image.unmask(),
  numericValue: image.unmask(16777219),
  oneBandBroadcast: image.unmask(ee.Image.constant(9).rename('unused')),
  twoBandOrder: image.unmask(ee.Image.constant([101, 202]).rename(['nir', 'red'])),
  maskedReplacement: image.unmask(ee.Image.constant(9).updateMask(ee.Image.constant(0))),
  sameFootprintFalse: image.unmask(ee.Image.constant(0), false),
  sameFootprintFalseDefaultValue: image.unmask({ sameFootprint: false }),
};
const rasterCollection = ee.ImageCollection('sentinel-2-l2a')
  .filterDate(ee.Date(1000), ee.Date(1001));
const rasterImage = ee.Image(rasterCollection.first());
const nir = rasterImage.select('nir');
const red = rasterImage.select('red');
const sampleLeftHalf = ee.Geometry.Rectangle(
  [113.55299439326834, 22.314269909925745, 113.5537966618118, 22.315726168412937],
  null, false,
);
const rasterValues = {
  unmaskZero: nir.unmask(),
  unmaskLarge: nir.unmask(16777219),
  unmaskRaster: nir.unmask(red),
  unmaskClipped: nir.clip(sampleLeftHalf).unmask(16777219),
  unmaskDouble: nir.toDouble().unmask(1700000000001),
  unmaskMappedMean: ee.ImageCollection('sentinel-2-l2a').map(function(im) {
    return im.select('nir').unmask(0).toFloat();
  }).mean(),
};
const expressions = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, ee.Serializer.encode(value)]));
const rasterExpressions = Object.fromEntries(Object.entries(rasterValues).map(([key, value]) => [key, ee.Serializer.encode(value)]));
process.stdout.write(JSON.stringify({
  sdk: '1.7.49',
  source_commit: 'e189e4b89e785019ea5642ea8e80cb644749cd4a',
  source: 'https://github.com/google/earthengine-api',
  expressions,
  raster_expressions: rasterExpressions,
}, null, 2) + '\n');
