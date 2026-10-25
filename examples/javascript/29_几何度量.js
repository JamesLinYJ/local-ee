// Finite local geometry only; default scalars use metres/metres squared.
function buildWorkflow(ee) {
  const polygon = ee.Geometry.Polygon([[[0, 0], [90, 0], [0, 90], [0, 0]]]);
  const line = ee.Geometry.LineString([[0, 0], [90, 0]]);
  const projection = ee.Projection('EPSG:4326');
  const planar = ee.Geometry.Polygon(
    [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]], projection, false
  );
  const features = ee.FeatureCollection([
    ee.Feature(polygon, {name: 'octant'}),
    ee.Feature(line, {name: 'equator'})
  ]);
  const measured = features.map(function (feature) {
    return feature.set({
      area_m2: feature.area(),
      length_m: feature.length(),
      perimeter_m: feature.perimeter()
    });
  });
  return {
    area_m2: polygon.area(),
    length_m: line.length(),
    perimeter_m: polygon.perimeter(),
    centroid: polygon.centroid(),
    planar_area_deg2: planar.area(null, projection),
    measured_features: measured
  };
}

if (typeof module !== 'undefined') module.exports = {buildWorkflow};
