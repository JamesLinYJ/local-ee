// 循环日期 -> 跳过空月份 -> fromImages -> map 元数据 -> 合成/导出。
// 只有 2024 年 1 月的已有本地样本；2、3 月会被跳过，不会自动下载。
var roi = ee.Geometry.Rectangle([113.55, 22.30, 113.57, 22.32]);
var scenes = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(roi);
var start = ee.Date.fromYMD(2024, 1, 1);
var images = ee.List.sequence(0, 2).map(function(month) {
  var begin = start.advance(month, 'month');
  var period = scenes.filterDate(begin, begin.advance(1, 'month'));
  return ee.Algorithms.If(period.size().gt(0), period.map(function(image) {
    return image.normalizedDifference(['B8', 'B4']).rename('NDVI');
  }).median().clip(roi)
    .set('system:time_start', begin.millis())
    .set('system:index', begin.format('yyyyMM')), null);
}, true);
var monthly = ee.ImageCollection.fromImages(images).map(function(image) {
  return image.set('year', image.date().get('year'));
});
print('有数据的月份', monthly.aggregate_array('system:index'));
print('年份', monthly.aggregate_array('year'));
Map.centerObject(monthly, 13);
Map.addLayer(monthly.mean(), {min: 0, max: 1, palette: ['f4e5b9','155b3b']}, '月合成 NDVI');
Export.image.toDrive({
  image: monthly.toBands(), description: '按月 NDVI', fileNamePrefix: 'monthly_ndvi',
  region: roi, scale: 10, crs: 'EPSG:32649', maxPixels: 1e13
});
