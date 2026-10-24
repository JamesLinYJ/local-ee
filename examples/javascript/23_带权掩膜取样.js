// Fractional weights control validity; every positive weight keeps the raw value.
function buildWorkflow(ee, image, regions, fixture) {
  var sourceImage = ee.Image(image);
  var wideFloat = sourceImage.select('wide_float').toFloat().toDouble();
  var source = ee.Image.cat(
    sourceImage.select('class_id'),
    sourceImage.select('red'),
    wideFloat,
    sourceImage.select('nir')
  ).rename(['class_id', 'red', 'wide_float', 'nir']);
  var weighted = source.updateMask(sourceImage.select([
    'class_weight', 'red_weight', 'wide_float_weight', 'nir_weight'
  ]));
  var allPositive = source.updateMask(1);
  var region = ee.Geometry(fixture.sample_region);
  var sampleOptions = {
    region: region, factor: 0.5, seed: 77,
    dropNulls: false, geometries: true, tileScale: 1
  };
  var samples = weighted.sample({region: region, dropNulls: false, geometries: true});
  var complete = samples.filter(ee.Filter.notNull(['class_id', 'red', 'nir']));
  var randomized = complete.randomColumn('split', 77, 'uniform', ['system:index']);
  var training = randomized.filter(ee.Filter.lt('split', 1)).limit(8);
  var md = ee.Classifier.minimumDistance('euclidean', 1)
    .train(training, 'class_id', ['red', 'nir']);
  var rf = ee.Classifier.smileRandomForest(5, undefined, 1, 0.5, undefined, 77)
    .train(training, 'class_id', ['red', 'nir']);
  var target = ee.Image(image).select(['red', 'nir']);

  return {
    samples_nullable: samples,
    samples_drop_nulls: weighted.sample({region: region, dropNulls: true, geometries: true}),
    fractional_factor_control: weighted.sample(sampleOptions),
    all_positive_factor_control: allPositive.sample(sampleOptions),
    sample_regions_fractional: weighted.sampleRegions({
      collection: regions, properties: ['source_id', 'record_number', 'source_note'], geometries: true
    }),
    sample_regions_all_positive: allPositive.sampleRegions({
      collection: regions, properties: ['source_id', 'record_number', 'source_note'], geometries: true
    }),
    md_training: training,
    md_classification: target.classify(md, 'md_class'),
    rf_training: training,
    rf_classification: target.classify(rf, 'rf_class')
  };
}

if (typeof module !== 'undefined') {
  module.exports = {buildWorkflow: buildWorkflow};
}
