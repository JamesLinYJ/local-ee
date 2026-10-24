// A zero-band Image is a schema seed; Image() itself has one masked band.

function buildWorkflow(ee, fixture) {
  var collection = ee.ImageCollection(fixture.source_id);
  var scenes = ee.List(collection.toList(2));
  var first = ee.Image(scenes.get(0));
  var second = ee.Image(scenes.get(1));
  var empty = ee.Image().select([]);
  var seed = empty.set('seed', 'wave68');
  var accumulated = ee.Image(scenes.iterate(function (scene, acc) {
    return ee.Image(acc).addBands(ee.Image(scene).select(['red', 'nir']));
  }, seed));
  var redTotal = accumulated.select('red').add(accumulated.select('red_1'))
    .rename('red_total');
  var nirTotal = accumulated.select('nir').add(accumulated.select('nir_1'))
    .rename('nir_total');
  var science = accumulated.addBands(redTotal).addBands(nirTotal);
  var region = ee.Geometry(fixture.region);

  return {
    empty: empty,
    empty_metadata: empty.copyProperties(first,
      ['system:index', 'system:time_start', 'scene_label'])
      .set('seed', 'wave68'),
    source_empty_metadata: first.select([]).rename([]).copyProperties(first,
      ['system:index', 'system:time_start', 'scene_label'])
      .set('seed', 'wave68'),
    empty_add_source: empty.addBands(first.select(['red', 'nir'])),
    source_add_empty: first.addBands(empty),
    empty_add_empty: empty.addBands(empty),
    ordered_add: empty.addBands(first.select(['nir', 'red'])),
    collision_default: first.select(['nir', 'red'])
      .addBands(second.select(['red', 'nir'])),
    collision_overwrite: first.select(['nir', 'red'])
      .addBands(second.select(['red', 'nir']), null, true),
    accumulated: accumulated,
    science: science,
    samples: science.sample({region: region, dropNulls: false, geometries: true}),
    // Captured as an official SDK wire; local execution uses List.iterate over
    // the bounded result of Collection.toList above.
    collection_iterate: ee.Image(ee.ImageCollection.fromImages([first, second]).iterate(
      function (scene, acc) {
        return ee.Image(acc).addBands(ee.Image(scene).select(['red', 'nir']));
      }, empty))
  };
}

exports.buildWorkflow = buildWorkflow;
