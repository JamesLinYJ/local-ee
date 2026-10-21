var roi = ee.Geometry.Rectangle([113.55, 22.30, 113.57, 22.32]);
var image = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterDate('2024-01-19', '2024-01-20').filterBounds(roi).median();
var ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI');
var stats = ndvi.reduceRegion({reducer: ee.Reducer.mean(), geometry: roi, scale: 10, crs: 'EPSG:32649'});
print('区域均值', stats);
Export.table.toDrive({collection: ee.FeatureCollection([ee.Feature(null, stats)]), description: 'NDVI_区域均值', fileFormat: 'CSV'});
