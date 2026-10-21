// 本地 Sentinel-2 子集，已去云；GEE 别名按 DN（反射率 × 10000）提供。
// 范围和日期须在本地目录覆盖内，缺少波段会明确报错。
var roi = ee.Geometry.Rectangle([113.55, 22.30, 113.57, 22.32]);
var scenes = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterDate('2024-01-19', '2024-01-20')
    .filterBounds(roi);
print('影像数量', scenes.size());
var ndvi = scenes.map(function(image) {
    return image.normalizedDifference(['B8', 'B4']).rename('NDVI');
}).median().clip(roi);
Map.centerObject(roi, 13);
Map.addLayer(ndvi, {min: 0, max: 1, palette: ['f5e7bc', 'a7c982', '17663f']}, 'NDVI');
Export.image.toDrive({
    image: ndvi, description: 'Sentinel2_NDVI', fileFormat: 'GeoTIFF',
    region: roi, scale: 10, crs: 'EPSG:32649'
});
