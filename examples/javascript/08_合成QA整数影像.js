// 使用本地准入 ID 对应的合成元数据和 SCL/NIR/red 波段标签；不读取栅格或访问 Google 目录/资产。
// 这些位是本例定义的合成字段，不等同 QA60、Landsat QA_PIXEL 或原始数据集 QA。
var roi = ee.Geometry.Rectangle([100.2, 30.2, 100.8, 30.8], 'EPSG:4326', false);
var cloudBits = (1 << 0) | (1 << 1) | (1 << 2);
var invalidBits = (1 << 7) - 1;
var float32IntegerLimit = 2 ** 24;
var exactFloat64IntegerLimit = 2 ** 53;

function flag(scl, category, bit) {
  return scl.eq(category).toUint8().leftShift(bit);
}

function buildIntegerImageWorkflow(ee, collection) {
  var scene = collection.first();
  var scl = scene.select('SCL').toUint8();
  var cloudQa = flag(scl, 8, 0)
    .bitwiseOr(flag(scl, 9, 1))
    .bitwiseOr(flag(scl, 10, 2));
  var shadowQa = flag(scl, 3, 3);
  var snowQa = flag(scl, 11, 4);
  var invalidQa = flag(scl, 0, 5).bitwiseOr(flag(scl, 1, 6));
  var packedQa = cloudQa.bitwiseOr(shadowQa).bitwiseOr(snowQa)
    .bitwiseOr(invalidQa).toUint8().rename('synthetic_qa');
  var cloudClear = packedQa.bitwiseAnd(cloudBits).eq(0).rename('cloud_clear');
  var surfaceClear = packedQa.bitwiseAnd(invalidBits).eq(0).rename('surface_clear');
  var maskedNdvi = scene.select(['nir', 'red']).toFloat()
    .updateMask(surfaceClear).normalizedDifference(['nir', 'red'])
    .rename('masked_ndvi');

  // SCL is at most 11, so this raster-backed 40-bit shift stays exact in Double.
  var dynamicHighBit = scl.leftShift(40).bitwiseAnd(2 ** 40)
    .eq(2 ** 40).rename('category_bit_40');

  // Integer shifts/OR make high-magnitude values from actual SCL pixels. No
  // Float32 conversion or generic arithmetic happens before these comparisons.
  var comparisonMask = scl.gte(0);
  var widerThanFloat32 = scl.toInt32().leftShift(24).bitwiseOr(1)
    .updateMask(comparisonMask);
  var wideComparisons = {
    wide_eq: widerThanFloat32.eq(float32IntegerLimit + 1),
    wide_neq: widerThanFloat32.neq(float32IntegerLimit),
    wide_lt: widerThanFloat32.lt(float32IntegerLimit + 2),
    wide_lte: widerThanFloat32.lte(float32IntegerLimit + 1),
    wide_gt: widerThanFloat32.gt(float32IntegerLimit),
    wide_gte: widerThanFloat32.gte(float32IntegerLimit + 1)
  };
  // The raster source is a 0/1 predicate, so its 53-bit shift remains exact.
  var int64Upper = scl.eq(1).toInt64().leftShift(53)
    .updateMask(comparisonMask);
  var exactBoundary = {
    int64_at_upper_bound: int64Upper.eq(exactFloat64IntegerLimit),
    int64_above_previous: int64Upper.gt(exactFloat64IntegerLimit - 1),
    int64_not_above_bound: int64Upper.lte(exactFloat64IntegerLimit)
  };
  return Object.assign({
    packed_qa: packedQa,
    cloud_clear: cloudClear,
    surface_clear: surfaceClear,
    masked_ndvi: maskedNdvi,
    dynamic_high_bit: dynamicHighBit,
    negative_bit_count: ee.Image.constant(-1).updateMask(comparisonMask).bitCount(),
    signed_shift_63: ee.Image.constant(-1).updateMask(comparisonMask).rightShift(63)
  }, wideComparisons, exactBoundary);
}

var outputs = buildIntegerImageWorkflow(ee, ee.ImageCollection('sentinel-2-l2a'));
Map.addLayer(outputs.cloud_clear,
  {min: 0, max: 1, palette: ['000000', '00aaff']},
  'Synthetic cloud-clear mask');
var task = Export.image.toDrive({
  image: outputs.masked_ndvi,
  description: 'synthetic_integer_qa_masked_ndvi',
  folder: 'integer-images',
  fileNamePrefix: 'synthetic_integer_qa_masked_ndvi',
  region: [[[100.2, 30.2], [100.8, 30.2], [100.8, 30.8],
    [100.2, 30.8], [100.2, 30.2]]],
  scale: 10,
  crs: 'EPSG:32649',
  maxPixels: 100000
});
