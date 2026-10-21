// 使用已有本地样本。填充值只是输出约定，不代表恢复了缺失观测。
var roi = ee.Geometry.Rectangle([113.55, 22.30, 113.57, 22.32], null, false);
var image = ee.ImageCollection('sentinel-2-l2a')
  .filterBounds(roi).filterDate('2024-01-19', '2024-01-20').first();
var nir = image.select('nir').clip(roi);
// 为演示填补分支，主动掩膜低于 0.2 的近红外像素；这不是云检测。
var masked = nir.updateMask(nir.gt(0.2));
// 原值有效（包括 0）时保留；clip 外仍无效。
// 该数值可用于检查导出是否误降到 Float32。
var filled = masked.unmask(16777219);
print('输出波段', filled.bandNames());
Map.centerObject(roi, 13);
Map.addLayer(filled, {min: 0, max: 0.6, palette: ['183e63', 'a9d3ce', 'f3f7f4']}, '近红外 · 缺测填充');
var task = Export.image.toDrive({
  image: filled, description: '缺测填充_Float64', fileNamePrefix: 'unmask_float64',
  region: roi, scale: 10, crs: 'EPSG:32649', fileFormat: 'GeoTIFF'
});
// task.start(); 或从任务面板开始导出。
// 当前 unmask 输出为 Float64；后续算术需显式 toFloat()，注意精度损失。
