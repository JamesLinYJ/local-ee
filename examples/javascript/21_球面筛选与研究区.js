// Ordinary official-SDK WGS84 coordinates with default spherical edges.
const REGIONS = {
  dateline: [[170,-5],[-170,-5],[-170,5],[170,5],[170,-5]],
  polar: [[-135,78],[-45,78],[45,78],[135,78],[-135,78]],
  high_left: [[0,65],[60,65],[30,82],[0,65]],
  high_right: [[30,65],[90,65],[60,82],[30,65]]
};

const POINTS = [
  ['dateline_inside',[180,0]], ['dateline_outside',[0,0]],
  ['polar_inside',[0,89]], ['polar_outside',[0,50]],
  ['high_left_only',[15,75]], ['high_overlap',[45,75]],
  ['high_right_only',[75,75]], ['curved_inside',[25,70]],
  ['curved_planar_only',[25,66]], ['high_below',[45,60]]
];

function buildWorkflow(ee) {
  const geometries = Object.fromEntries(Object.entries(REGIONS).map(([name, ring]) =>
    [name, ee.Geometry.Polygon([ring])]
  ));
  const allPoints = ee.FeatureCollection(POINTS.map(([name, coordinates]) =>
    ee.Feature(ee.Geometry.Point(coordinates), {point_id: name})
  ));
  const highPoints = ee.FeatureCollection(POINTS
    .filter(([name]) => name.startsWith('high_') || name.startsWith('curved_'))
    .map(([name, coordinates]) =>
      ee.Feature(ee.Geometry.Point(coordinates), {point_id: name})
    ));
  const queryPoints = ee.FeatureCollection(POINTS
    .filter(([name]) => ['high_overlap', 'curved_inside', 'curved_planar_only'].includes(name))
    .map(([name, coordinates]) =>
      ee.Feature(ee.Geometry.Point(coordinates), {point_id: name})
    ));
  const highRegions = ee.FeatureCollection(['high_left', 'high_right'].map(name =>
    ee.Feature(geometries[name], {region_id: name})
  ));
  const merged = highRegions.geometry();
  const mergedNull = highRegions.geometry({maxError: null});
  const mergedTyped = highRegions.geometry({maxError: ee.ErrorMargin(0)});
  const filters = {
    field_value_numeric: ee.Filter.intersects({
      leftField: '.geo', rightValue: geometries.high_left, maxError: 5
    }),
    value_field_typed: ee.Filter.intersects({
      leftValue: geometries.high_left, rightField: '.geo',
      maxError: ee.ErrorMargin(5, 'projected')
    }),
    field_field_typed: ee.Filter.intersects({
      leftField: '.geo', rightField: '.geo', maxError: ee.ErrorMargin(5)
    }),
    value_value_numeric: ee.Filter.intersects({
      leftValue: geometries.high_left, rightValue: geometries.high_right, maxError: 5
    })
  };
  const selected = queryPoints.filterBounds(merged);
  const filterResults = Object.fromEntries(Object.entries(filters).map(
    ([name, spatialFilter]) => [name, highPoints.filter(spatialFilter)]
  ));

  const firstMatch = ee.Feature(selected.first()).set('row_kind', 'filter_result');
  const regionRow = ee.Feature(merged, {row_kind: 'regionGeometry'});
  const table = ee.FeatureCollection([firstMatch, regionRow]);
  return {
    dateline_selected: allPoints.filterBounds(geometries.dateline),
    polar_selected: allPoints.filterBounds(geometries.polar),
    merge_omitted: merged, merge_null: mergedNull, merge_typed: mergedTyped,
    filters: filters, filter_results: filterResults,
    selected: selected, table: table
  };
}

function encodeWorkflow(ee, values) {
  const encode = value => ee.Serializer.encode(value);
  return {
    dateline_selected: encode(values.dateline_selected),
    polar_selected: encode(values.polar_selected),
    merge_omitted: encode(values.merge_omitted),
    merge_null: encode(values.merge_null),
    merge_typed: encode(values.merge_typed),
    filters: Object.fromEntries(Object.entries(values.filters).map(
      ([name, value]) => [name, encode(value)]
    )),
    filter_results: Object.fromEntries(Object.entries(values.filter_results).map(
      ([name, value]) => [name, encode(value)]
    )),
    selected: encode(values.selected), table: encode(values.table)
  };
}

if (typeof module !== 'undefined') {
  module.exports = {REGIONS, POINTS, buildWorkflow, encodeWorkflow};
}
