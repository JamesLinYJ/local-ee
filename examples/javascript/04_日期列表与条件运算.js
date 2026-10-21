// 使用已有本地样本。官方 EE 客户端 + 本地 openEO/GeoTrellis。
var roi = ee.Geometry.Rectangle([113.55, 22.30, 113.57, 22.32]);
var scenes = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(roi).filterDate('2024-01-19', '2024-01-20');

var dates = ee.List.sequence(0, 2).map(function(month) {
  return ee.Date.fromYMD(2024, 1, 31).advance(month, 'month').format('yyyy-MM-dd');
});
print('日期循环', dates);
print('影像 ID', scenes.aggregate_array('system:index'));

var image = ee.Image(scenes.toList(1).get(0));
var ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI');
ndvi = ndvi.where(ndvi.lt(0), 0).clamp(0, 1).clip(roi);
Map.centerObject(image, 13);
Map.addLayer(ndvi, {min: 0, max: 1, palette: ['f4e5b9', '9cc475', '155b3b']}, 'NDVI · 条件运算');

Export.image.toDrive({
  image: ndvi, description: '兼容验收 NDVI', fileNamePrefix: 'compat_ndvi',
  region: roi, scale: 10, crs: 'EPSG:32649', maxPixels: 1e13,
  fileFormat: 'GeoTIFF'
});
var stats = ndvi.reduceRegion({
  reducer: ee.Reducer.mean(), geometry: roi, scale: 10,
  crs: 'EPSG:32649', maxPixels: 1e13
});
Export.table.toDrive({
  collection: ee.FeatureCollection([ee.Feature(null, stats)]),
  description: '兼容验收区域均值', fileNamePrefix: 'ndvi_stats',
  fileFormat: 'CSV', selectors: ['NDVI']
});
// 导出在任务面板点击“开始导出”。数据、结果均保留在本机。
