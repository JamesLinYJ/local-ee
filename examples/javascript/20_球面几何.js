// Ordinary official-SDK WGS84 coordinates with spherical defaults.
const OPERATIONS = [
  'contains', 'containedIn', 'disjoint', 'intersects',
  'intersection', 'union', 'difference', 'symmetricDifference'
];
const OVERLAYS = ['intersection', 'union', 'difference', 'symmetricDifference'];

function geometry(ee, value) {
  if (value.type === 'Polygon') {
    if (Object.prototype.hasOwnProperty.call(value, 'evenOdd'))
      return ee.Geometry.Polygon(value.coordinates, null, null, null, value.evenOdd);
    return ee.Geometry.Polygon(value.coordinates);
  }
  if (value.type === 'LineString') return ee.Geometry.LineString(value.coordinates);
  if (value.type === 'Point') return ee.Geometry.Point(value.coordinates);
  throw new Error(`Unsupported fixture geometry: ${value.type}`);
}

function feature(ee, geometryValue, identity, properties) {
  return ee.Feature({
    type: 'Feature', id: identity, geometry: geometryValue,
    properties: {...properties}
  });
}

function binary(left, name, right, explicitNullProjection) {
  const args = {right: right};
  if (explicitNullProjection) args.proj = null;
  return left[name](args);
}

function buildWorkflow(ee, fixture, options = {}) {
  const explicitNullProjection = options.explicitNullProjection === true;
  const regions = Object.fromEntries(Object.entries(fixture.regions).map(
    ([name, value]) => [name, geometry(ee, value)]
  ));
  const left = regions.dateline_left;
  const right = regions.dateline_right;
  const featureConfig = fixture.features;
  const leftFeature = feature(
    ee, left, featureConfig.left_id, featureConfig.left_properties
  );
  const rightFeature = feature(
    ee, right, featureConfig.right_id, featureConfig.right_properties
  );
  const geometryBinary = Object.fromEntries(OPERATIONS.map(name => [
    name, binary(left, name, right, explicitNullProjection)
  ]));
  const featureBinary = Object.fromEntries(OPERATIONS.map(name => [
    name, binary(leftFeature, name, rightFeature, explicitNullProjection)
  ]));

  const probeRegions = {
    dateline_inside: 'dateline_left', dateline_other_side: 'dateline_left',
    polar_cap_inside: 'polar_cap', polar_cap_outside: 'polar_cap',
    hole_shell_inside: 'with_hole', hole_center_outside: 'with_hole',
    oriented_left_inside: 'oriented_left',
    oriented_reversed_outside: 'oriented_reversed',
    oriented_reversed_complement: 'oriented_reversed'
  };
  const probes = Object.fromEntries(Object.entries(fixture.probes).map(([name, probe]) => [
    name, binary(regions[probeRegions[name]], 'contains',
      ee.Geometry.Point(probe.point), explicitNullProjection)
  ]));

  const touchPolygon = regions.touch_polygon;
  const touchLine = regions.touch_line;
  const boundaryPoint = regions.boundary_point;
  const boundary = {
    point_intersects: binary(touchPolygon, 'intersects', boundaryPoint, explicitNullProjection),
    line_intersects: binary(touchPolygon, 'intersects', touchLine, explicitNullProjection),
    intersection_line: binary(touchPolygon, 'intersection', touchLine, explicitNullProjection),
    intersection_point: binary(touchPolygon, 'intersection', boundaryPoint, explicitNullProjection),
    point_contains: binary(touchPolygon, 'contains', boundaryPoint, explicitNullProjection),
    empty_intersection: binary(regions.dateline_left, 'intersection',
      regions.empty_other, explicitNullProjection)
  };
  const featureOverlays = OVERLAYS.map(name => {
    const identifiedLeft = feature(
      ee, left, `${featureConfig.left_id}-${name}`, featureConfig.left_properties
    );
    return binary(identifiedLeft, name, rightFeature, explicitNullProjection);
  });

  return {
    geometry: geometryBinary,
    feature: featureBinary,
    probes: probes,
    boundary: boundary,
    feature_overlays: ee.FeatureCollection(featureOverlays)
  };
}

function encodeWorkflow(ee, values) {
  const encode = value => ee.Serializer.encode(value);
  function encodeMap(source) {
    return Object.fromEntries(Object.entries(source).map(([name, value]) => [name, encode(value)]));
  }
  return {
    geometry: encodeMap(values.geometry),
    feature: encodeMap(values.feature),
    probes: encodeMap(values.probes),
    boundary: encodeMap(values.boundary),
    feature_overlays: encode(values.feature_overlays)
  };
}

if (typeof module !== 'undefined') {
  module.exports = {
    buildWorkflow: buildWorkflow,
    encodeWorkflow: encodeWorkflow,
    geometry: geometry
  };
}
