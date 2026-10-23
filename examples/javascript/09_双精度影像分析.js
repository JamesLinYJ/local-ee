// 固定官方 JavaScript 客户端语法；只使用离线合成元数据，不读取栅格文件。
// synthetic_temperature_millikelvin 是测试夹具声明的合成波段，不是 ERA5 或 Sentinel-2 产品。
var collectionId = 'sentinel-2-l2a';
var temperatureBand = 'synthetic_temperature_millikelvin';
var temperatureScale = 0.001;
var temperatureOffsetKelvin = 0.0;
var pixelSizeMetres = 10;
var cloudBits = (1 << 0) | (1 << 1) | (1 << 2);
var exportRegion = [[[100.2, 30.2], [100.8, 30.2], [100.8, 30.8],
  [100.2, 30.8], [100.2, 30.2]]];

function buildFloat64Analysis(ee, collection) {
  var scene = collection.first();
  var scl = scene.select('SCL');

  // Integer QA values keep their Double precision marker for ordinary math.
  var qaPacked = scl.eq(8).toUint8().leftShift(0)
    .bitwiseOr(scl.eq(9).toUint8().leftShift(1))
    .bitwiseOr(scl.eq(10).toUint8().leftShift(2))
    .rename('synthetic_cloud_qa');
  var qaNumeric = qaPacked.toUint8().multiply(2).add(1).rename('qa_numeric');
  var qaClear = qaPacked.bitwiseAnd(cloudBits).eq(0).rename('qa_clear');

  // normalizedDifference preserves its negative-input mask. The expression
  // and explicit formula retain signed normalized values for negative inputs.
  var optical = scene.select(['nir', 'red']).toDouble();
  var nir = optical.select('nir');
  var red = optical.select('red');
  var normalizedNdvi = optical.normalizedDifference(['nir', 'red'])
    .rename('normalized_ndvi');
  var signedNdvi = scene.expression('(nir - red) / (nir + red)', {
    nir: nir,
    red: red
  }).rename('signed_ndvi');
  var signedNdviCore = nir.subtract(red).divide(nir.add(red))
    .rename('signed_ndvi_core');

  // Fixture-only millikelvin band; this does not represent ERA5 or S2 data.
  var syntheticTemperatureCelsius = scene.select(temperatureBand).toDouble()
    .multiply(temperatureScale).add(temperatureOffsetKelvin)
    .subtract(273.15).rename('synthetic_temperature_celsius');

  // fastDistanceTransform returns squared pixel units; sqrt then uses the
  // Double core, and 10 m is the pixel size declared by this fixture grid.
  var waterDistancePixels = scl.eq(6).fastDistanceTransform(8)
    .toDouble().sqrt().rename('water_distance_pixels');
  var waterDistanceMetres = waterDistancePixels.multiply(pixelSizeMetres)
    .rename('water_distance_metres');

  // Explicit Float32 operands retain the existing Float32 graph.
  var float32Difference = scene.select('nir').toFloat()
    .subtract(scene.select('red').toFloat()).rename('float32_difference');

  var analysis = signedNdvi.addBands(normalizedNdvi)
    .addBands(qaNumeric).addBands(qaClear)
    .addBands(syntheticTemperatureCelsius).addBands(waterDistanceMetres);
  return {
    qa_packed: qaPacked,
    qa_numeric: qaNumeric,
    qa_clear: qaClear,
    normalized_ndvi: normalizedNdvi,
    signed_ndvi: signedNdvi,
    signed_ndvi_core: signedNdviCore,
    synthetic_temperature_celsius: syntheticTemperatureCelsius,
    water_distance_pixels: waterDistancePixels,
    water_distance_metres: waterDistanceMetres,
    float32_difference: float32Difference,
    analysis: analysis
  };
}

var outputs = buildFloat64Analysis(ee, ee.ImageCollection(collectionId));
Map.addLayer(outputs.signed_ndvi, {min: -1, max: 1},
  'Signed Double NDVI (synthetic fixture)');
var task = Export.image.toDrive({
  image: outputs.analysis,
  description: 'synthetic_float64_analysis',
  folder: 'float64-analysis',
  fileNamePrefix: 'synthetic_float64_analysis',
  region: exportRegion,
  scale: pixelSizeMetres,
  crs: 'EPSG:32649',
  maxPixels: 100000
});
