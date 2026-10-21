var roi = ee.Geometry.Rectangle([113.55, 22.30, 113.57, 22.32]);
var image = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterDate('2024-01-19', '2024-01-20')
    .filterBounds(roi).median().clip(roi);
Map.centerObject(roi, 13);
Map.addLayer(image, {bands: ['B4', 'B3', 'B2'], min: 0, max: 3000, gamma: 1.2}, '真彩色');
