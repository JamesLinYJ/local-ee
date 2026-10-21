/* Generate serialized contracts with the unmodified, pinned official SDK.
 * Only checked-in fixture expressions execute here; no user script or I/O bridge.
 * node scripts/ee_sdk_fixtures.cjs > tests/fixtures/ee-sdk-1.7.49.json
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
const c = ee.ImageCollection('sentinel-2-l2a');
const im = ee.Image(c.first());
const n = im.select('nir');
const r = im.select('red');
const roi = ee.Geometry.Rectangle([0, 0, 2, 2], null, false);
const explicit = ee.ImageCollection.fromImages(c.toList(3));
const periods = ee.ImageCollection.fromImages(ee.List.sequence(0,2).map(i => {
  var begin = ee.Number(i).add(1000);
  var subset = c.filterDate(begin,begin.add(1));
  return ee.Algorithms.If(subset.size().gt(0),subset.select('nir').median()
    .set('system:time_start',begin).set('system:index',ee.Date(begin).format('SSS')),null);
},true));
const values = {
  dates: ee.List.sequence(0, 2).map(m => ee.Date.fromYMD(2024, 1, 31).advance(m, 'month').format('yyyy-MM-dd')),
  dateYear: ee.Date('2024-02-29T12:34:56.789Z').advance(1, 'year').format("yyyy-MM-dd'T'HH:mm:ss.SSSZZ"),
  dateUnits: ee.List(['year','month','day','hour','minute','second']).map(u => ee.Date('2024-02-29T12:34:56Z').get(u)),
  iterate: ee.List.sequence(1, 4).iterate((x, sum) => ee.Number(sum).add(x), 0),
  dropNulls: ee.List.sequence(0, 3).map(x => ee.Algorithms.If(ee.Number(x).gt(1), x, null), true),
  listHelpers: ee.List([3, 1, 3, 2]).distinct().sort().slice(1),
  listKeys: ee.List(['a', 'b', 'c']).sort([2, 1, 3]),
  properties: c.sort('system:time_start', false).aggregate_array('system:index'),
  toList: c.toList(2, 1).map(x => ee.Image(x).date().millis()),
  toListImage: ee.Image(c.toList(2).get(1)).select('nir'),
  inList: c.filter(ee.Filter.inList('system:index', ['a', 'c'])).aggregate_array('system:index'),
  calendar: c.filter(ee.Filter.calendarRange(12, 2, 'month')).size(),
  staticMapMetadata: c.map(x => x.set('label', 'accepted')).aggregate_array('label'),
  copiedMapDate: c.map(x => x.normalizedDifference(['nir', 'red']).copyProperties(x, ['system:time_start'])).filterDate(1000, 1002).size(),
  where: n.where(r.gt(2), im.select('blue')),
  whereConstant: n.where(r.gt(2), 0),
  constantMath: n.multiply(ee.Image(4).sqrt()),
  whereMasked: n.where(im.select('green'), im.select('blue')),
  clamp: n.clamp(2, 6),
  unitScale: n.unitScale(1, 5),
  reduceBands: im.select(['nir', 'red']).reduce(ee.Reducer.mean()),
  reduceCollection: c.select('nir').reduce(ee.Reducer.mean()),
  toBands: c.limit(2).select('nir').toBands(),
  imageGeometry: im.clip(roi).geometry(),
  collectionGeometry: c.geometry(),
  median: c.limit(2).select('nir').median(),
  sum: c.limit(2).select('nir').sum(),
  count: c.limit(2).select('nir').count(),
  mosaic: c.limit(2).select('nir').mosaic(),
  reverseMosaic: c.limit(2).sort('system:time_start', false).select('nir').mosaic(),
  cloudMask: c.limit(2).map(x => x.updateMask(x.select('SCL').eq(4)).select('nir')).median(),
  nd: im.normalizedDifference(['nir','red']),
  expression: im.expression('out = (n - r) / (n + r)', {n:n, r:r}),
  selectRename: im.select(['nir','red'], ['N','R']).addBands(n.rename('N')),
  missingBand: im.select('QA60'),
  invalidPattern: ee.Date('2024-01-01').format('YYYY-QQ'),
  fromImagesMean: explicit.limit(2).select('nir').mean(),
  fromImagesDuplicateSum: ee.ImageCollection.fromImages([im.select('nir'),im.select('nir')]).sum(),
  fromImagesDuplicateCount: ee.ImageCollection.fromImages([im.select('nir'),im.select('nir')]).count(),
  fromImagesMetadata: explicit.map(x => x.set('year',x.date().get('year'))).aggregate_array('year'),
  fromImagesSortedMosaic: explicit.sort('CLOUDY_PIXEL_PERCENTAGE',false).select('nir').mosaic(),
  fromImagesSize: explicit.size(),
  fromImagesEmptySize: ee.ImageCollection.fromImages([]).size(),
  fromImagesPeriodDates: periods.aggregate_array('system:time_start'),
  fromImagesPeriods: periods.mean(),
  mergedMean: c.limit(1).merge(ee.ImageCollection.fromImages([ee.Image(c.toList(2).get(1))])).select('nir').mean(),
  qualityMosaic: c.limit(2).select(['nir','blue']).qualityMosaic('nir'),
  qualityMosaicReverse: c.limit(2).sort('system:time_start',false).select(['nir','blue']).qualityMosaic('nir'),
  qualityMosaicExplicit: ee.ImageCollection.fromImages(c.toList(3)).select(['nir','blue']).qualityMosaic('nir'),
  toDouble: n.toDouble(),
  doubleToFloat: n.toDouble().toFloat(),
  perImageDateMean: c.map(x => x.select('nir').multiply(x.date().difference(ee.Date(0),'second'))).mean(),
};
const serialized = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, ee.Serializer.encode(value)]));
process.stdout.write(JSON.stringify({sdk: '1.7.49', source_commit: 'e189e4b89e785019ea5642ea8e80cb644749cd4a', expressions: serialized}, null, 2) + '\n');
