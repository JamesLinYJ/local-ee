// 用固定合成站点与影像目录整理要素元数据；全部在离线编译器中运行。

function stationFeature(ee, row) {
  var geometry = row.geometry === null ? null : ee.Geometry(row.geometry);
  var properties = Object.assign({}, row.properties);
  properties.samples = ee.Array(properties.samples);
  properties['system:index'] = row.id;
  return ee.Feature(geometry, properties);
}

function prepareStation(ee, feature, fixture) {
  var limits = fixture.filter;
  var sourceGeometry = feature.geometry();
  var renamed = ee.Feature(
    feature.select(limits.selectors, limits.renamed_fields, true));
  var reading = feature.getNumber('reading');
  var heightM = feature.getNumber('height_m');
  var stationName = feature.getString('station_name');
  var quality = feature.getString('quality');
  var longitude = feature.getNumber('longitude');
  var latitude = feature.getNumber('latitude');
  var samples = feature.getArray('samples');
  var additions = {
    source_id: feature.id(),
    station_name: stationName,
    reading: reading,
    height_m: heightM,
    quality_flag: quality,
    longitude: longitude,
    latitude: latitude,
    samples: samples,
    typed_reading: reading,
    typed_samples: samples,
    reading_vector: feature.toArray(['reading', 'height_m']),
    source_fields: feature.toDictionary(['station_code', 'reading']),
    score: reading.add(heightM.divide(8)),
    source_geometry_type: sourceGeometry.type(),
    source_geometry_coordinates: sourceGeometry.coordinates()
  };
  var declaredPoint = ee.Geometry.Point(
    [longitude, latitude], 'EPSG:4326');
  return renamed.setGeometry(declaredPoint).set(additions);
}

function buildStationWorkflow(ee, fixture) {
  var limits = fixture.filter;
  var source = ee.FeatureCollection(fixture.rows.map(function (row) {
    return stationFeature(ee, row);
  }));
  var predicate = ee.Filter.and(
    ee.Filter.stringStartsWith('station_code', limits.station_prefix),
    ee.Filter.stringEndsWith('station_code', limits.station_suffix),
    ee.Filter.gte('reading', limits.reading_min_inclusive),
    ee.Filter.lte('reading', limits.reading_max_inclusive),
    ee.Filter.calendarRange(
      limits.day_of_year_min_inclusive,
      limits.day_of_year_max_inclusive,
      'day_of_year'));
  var metadataSelected = source.filter(predicate);
  var region = ee.Geometry.Rectangle(limits.bounds, 'EPSG:4326', false);
  var spatiallySelected = metadataSelected.filterBounds(region);
  var prepared = spatiallySelected.map(function (feature) {
    return prepareStation(ee, feature, fixture);
  });
  var nullGeometryControl = ee.Feature(null, {
    'system:index': 'null-geometry-control', kind: 'control'
  }).setGeometry(null);
  return {
    metadata_ids: metadataSelected.aggregate_array('system:index'),
    metadata_count: metadataSelected.size(),
    station_ids: prepared.aggregate_array('source_id'),
    station_count: prepared.size(),
    stations: prepared,
    null_geometry_control: nullGeometryControl
  };
}

function buildCatalogWorkflow(ee, fixture) {
  var limits = fixture.catalog;
  var collection = ee.ImageCollection(limits.collection_id);
  var predicate = ee.Filter.and(
    ee.Filter.stringStartsWith('system:index', limits.id_prefix),
    ee.Filter.stringEndsWith('system:index', limits.id_suffix),
    ee.Filter.gte('cloud', limits.cloud_min_inclusive),
    ee.Filter.lte('cloud', limits.cloud_max_inclusive),
    ee.Filter.calendarRange(
      limits.day_of_year_min_inclusive,
      limits.day_of_year_max_inclusive,
      'day_of_year'));
  var region = ee.Geometry.Rectangle(
    fixture.filter.bounds, 'EPSG:4326', false);
  var selected = collection.filter(predicate).filterBounds(region);
  var tagged = selected.map(function (image) {
    return image.set({
      cloud_typed: image.getNumber('cloud'),
      scene_id_typed: image.getString('system:index')
    });
  });
  var first = selected.first();
  return {
    image_ids: selected.aggregate_array('system:index'),
    cloud_values: selected.aggregate_array('cloud'),
    typed_cloud: first.getNumber('cloud'),
    typed_scene_id: first.getString('system:index'),
    mapped_typed_clouds: tagged.aggregate_array('cloud_typed')
  };
}

if (typeof module !== 'undefined') {
  module.exports = { buildStationWorkflow, buildCatalogWorkflow };
}
