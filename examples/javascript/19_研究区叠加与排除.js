// Explicit planar WGS84 overlays for two synthetic Sentinel-2 scenes.
const OPERATIONS = [
  'contains', 'containedIn', 'disjoint', 'intersects',
  'intersection', 'union', 'difference', 'symmetricDifference'
];
const OVERLAYS = ['intersection', 'union', 'difference', 'symmetricDifference'];

function geometry(ee, value, projection) {
  if (value.type === 'Point')
    return ee.Geometry.Point(value.coordinates, projection);
  const ring = value.coordinates[0];
  const xs = ring.map(point => point[0]);
  const ys = ring.map(point => point[1]);
  return ee.Geometry.Rectangle([
    Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)
  ], projection, false);
}

function buildGeometryWorkflow(ee, fixture) {
  const projection = 'EPSG:4326';
  const study = geometry(ee, fixture.regions.study, projection);
  const exclusion = geometry(ee, fixture.regions.exclusion, projection);
  const boundary = geometry(ee, fixture.regions.intersection_boundary_point, projection);
  const geometryOperations = Object.fromEntries(OPERATIONS.map(name => [
    name, study[name]({right: exclusion, proj: projection})
  ]));

  const leftProperties = {roi: 'study', priority: 7};
  const rightProperties = {roi: 'exclusion', priority: 99, 'system:index': 'roi-right'};
  const left = ee.Feature(study, {...leftProperties, 'system:index': 'roi-left-base'});
  const right = ee.Feature(exclusion, rightProperties);
  const featureOperations = Object.fromEntries(OPERATIONS.map(name => [
    name, left[name]({right: right, proj: projection})
  ]));
  const overlayFeatures = OVERLAYS.map(name => {
    const identifiedLeft = ee.Feature(study, {
      ...leftProperties, 'system:index': `roi-left-${name}`
    });
    return identifiedLeft[name]({right: right, proj: projection});
  });

  return {
    geometry: geometryOperations,
    feature: featureOperations,
    boundary: {
      study_contains_corner: study.contains({right: boundary, proj: projection}),
      exclusion_contains_corner: exclusion.contains({right: boundary, proj: projection}),
      exclusion_intersects_corner: exclusion.intersects({right: boundary, proj: projection})
    },
    feature_overlays: ee.FeatureCollection(overlayFeatures),
    regions: {
      study: study,
      intersection: geometryOperations.intersection,
      difference: geometryOperations.difference,
      union: geometryOperations.union,
      symmetricDifference: geometryOperations.symmetricDifference
    }
  };
}

function sceneImage(ee, fixture, roi, itemId) {
  return ee.ImageCollection(fixture.stac.collection.id)
    .filterBounds(roi)
    .filter(ee.Filter.eq('system:index', itemId))
    .first();
}

function buildImageWorkflow(ee, image, regions) {
  const source = ee.Image(image).select(['B04', 'B08']).toDouble();
  const red = source.select('B04');
  const nir = source.select('B08');
  const ndvi = ee.Image(nir.subtract(red).divide(nir.add(red)).rename('NDVI'));
  return Object.fromEntries(Object.entries(regions).map(([name, region]) => [
    name, ndvi.clip(region)
  ]));
}

function buildWorkflow(ee, fixture) {
  const overlay = buildGeometryWorkflow(ee, fixture);
  const images = {};
  for (const scene of fixture.scenes) {
    const image = sceneImage(ee, fixture, overlay.regions.study, scene.id);
    images[scene.id] = buildImageWorkflow(ee, image, overlay.regions);
  }
  return {
    geometry: overlay.geometry,
    feature: overlay.feature,
    boundary: overlay.boundary,
    feature_overlays: overlay.feature_overlays,
    images: images
  };
}

if (typeof module !== 'undefined') {
  module.exports = {
    buildWorkflow: buildWorkflow,
    buildGeometryWorkflow: buildGeometryWorkflow,
    buildImageWorkflow: buildImageWorkflow,
    sceneImage: sceneImage
  };
}
