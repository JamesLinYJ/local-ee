// Offline default and explicit-projection Geometry.bounds workflow.
function buildWorkflow(ee, fixture) {
  const projection = ee.Projection('EPSG:4326');
  const image = ee.Image(fixture.image.id);
  const collection = ee.ImageCollection(fixture.catalog.id);
  const sourceFeature = ee.Feature(
    ee.Geometry.Polygon(
      fixture.feature.geometry.coordinates, projection, false),
    {...fixture.feature.properties}
  );

  const imageBounds = image.geometry().bounds();
  const featureBounds = sourceFeature.bounds();
  const projectedImageBounds = image.geometry().bounds({proj: projection});
  const projectedFeatureBounds = sourceFeature.bounds({proj: projection});
  const sampleRegions = ee.FeatureCollection([projectedFeatureBounds]);
  const rows = ee.FeatureCollection([
    ee.Feature(imageBounds, {name: 'image-geometry-bounds', rank: 8}),
    featureBounds
  ]);

  return {
    image_bounds_default: imageBounds,
    feature_bounds_default: featureBounds,
    image_bounds_projected: projectedImageBounds,
    feature_bounds_projected: projectedFeatureBounds,
    filter_bounds: collection.filterBounds(projectedImageBounds),
    clipped_image: image.clip(projectedImageBounds),
    sample_regions: image.sampleRegions({
      collection: sampleRegions,
      properties: ['name', 'rank'],
      geometries: true
    }),
    bounds_table: rows,
    explicit_null_controls: {
      geometry: ee.Geometry.Polygon(
        fixture.feature.geometry.coordinates, projection, false
      ).bounds({maxError: null, proj: null}),
      feature: sourceFeature.bounds({maxError: null, proj: null}),
      image: image.geometry({maxError: null, proj: null, geodesics: null})
        .bounds({maxError: null, proj: null})
    }
  };
}

function buildNumericReferences(ee, fixture) {
  const refs = fixture.numeric_references;
  const projection = ee.Projection('EPSG:4326');
  return {
    planar_rectangle: ee.Geometry.Polygon(
      refs.planar_rectangle.coordinates, projection, false).bounds(),
    high_latitude_line: ee.Geometry.LineString(
      refs.high_latitude_line.coordinates).bounds(),
    high_latitude_polygon: ee.Geometry.Polygon(
      refs.high_latitude_polygon.coordinates).bounds()
  };
}

if (typeof module !== 'undefined') {
  module.exports = {buildWorkflow, buildNumericReferences};
}
