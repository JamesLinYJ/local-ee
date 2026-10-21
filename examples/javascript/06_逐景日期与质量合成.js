// 使用已有本地 Sentinel-2 影像；不会连接 Google 或下载外部数据。
var roi = ee.Geometry.Rectangle([113.55, 22.30, 113.57, 22.32]);
var scenes = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(roi).filterDate('2024-01-19', '2024-01-20');
var scored = scenes.map(function(image) {
  var date = image.date();
  var ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI');
  return image.addBands(ndvi)
    .set('day_of_year', date.getRelative('day', 'year'))
    .set('elapsed_days', date.difference(ee.Date('2024-01-01'), 'day'));
});
print('逐景日期（年内从 0 计数）', scored.aggregate_array('day_of_year'));
print('逐景距年初天数', scored.aggregate_array('elapsed_days'));
print('标量位计数', ee.Number(65535).bitCount());
// 质量相同时本地取集合中的后景；这个平分规则尚无 Google 对照。
var greenest = scored.qualityMosaic('NDVI').select('NDVI').clip(roi).toDouble();
Map.centerObject(roi, 13);
Map.addLayer(greenest, {min: 0, max: 1, palette: ['f5e7bc', 'a7c982', '17663f']}, '质量合成 NDVI');
Export.image.toDrive({
  image: greenest, description: '质量合成_Float64', fileNamePrefix: 'quality_ndvi_float64',
  region: roi, scale: 10, crs: 'EPSG:32649', fileFormat: 'GeoTIFF'
});
