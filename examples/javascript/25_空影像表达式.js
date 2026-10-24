// Official JavaScript SDK expressions with the transparent one-band receiver.
// This workflow is synthetic and local; it makes no Earth Engine requests.

function buildExpressionImages(ee, image) {
  var source = ee.Image(image);
  var receiver = ee.Image();
  var red = source.select('red');
  var nir = source.select('nir');
  var spectrum = source.select(['red', 'nir']);

  return {
    named_sum: receiver.expression('nir + red', {nir: nir, red: red})
      .rename('named_sum'),
    dot_red: receiver.expression('spectrum.red', {spectrum: spectrum})
      .rename('dot_red'),
    index_red: receiver.expression('spectrum[0]', {spectrum: spectrum})
      .rename('index_red'),
    index_nir: receiver.expression('spectrum[1]', {spectrum: spectrum})
      .rename('index_nir'),
    assigned: receiver.expression('assigned = red + 2', {red: red}),
    default_call: receiver.expression('b()'),
    default_index: receiver.expression('b(0)'),
    default_name: receiver.expression("b('constant')"),
    default_index_plus_red: receiver.expression('b(0) + red', {red: red})
      .rename('default_index_plus_red'),
    unweighted_nd: receiver.expression('(nir - red) / (nir + red)', {
      nir: nir, red: red
    }).rename('unweighted_nd'),
    normalized_difference: source.normalizedDifference(['nir', 'red'])
      .rename('normalized_difference')
  };
}

function buildWorkflow(ee, image, fixture) {
  var source = ee.Image(image);
  var expressions = buildExpressionImages(ee, source);
  var mapNames = [
    'named_sum', 'dot_red', 'index_red', 'index_nir', 'assigned',
    'unweighted_nd', 'normalized_difference'
  ];
  var defaultNames = [
    'default_call', 'default_index', 'default_name', 'default_index_plus_red'
  ];
  var mapValues = ee.Image.cat(mapNames.map(function (name) {
    return expressions[name];
  }));
  var defaultValues = ee.Image.cat(defaultNames.map(function (name) {
    return expressions[name];
  }));
  var region = ee.Geometry(fixture.region);

  var science = source.select('mask_science').toDouble();
  var oldWeight = source.select('old_weight');
  var newWeight = source.select('new_weight');
  var previouslyMasked = science.updateMask(oldWeight);
  var replaced = previouslyMasked.mask(newWeight);
  var updated = previouslyMasked.updateMask(newWeight);
  // updateMask(0) hides the old fractional value; mask(1) is the replacement
  // setter and locally recovers it through the zero-fill rule.
  var fractionalHiddenRecovery = source.select('red').toDouble()
    .updateMask(0.25).updateMask(0).mask(1)
    .rename('fractional_hidden_recovery');

  function sample(value) {
    return value.sample({region: region, dropNulls: false, geometries: true});
  }

  return {
    map_values: mapValues,
    default_values: defaultValues,
    default_weights: defaultValues.mask(),
    setter_values: replaced,
    setter_weights: replaced.mask(),
    update_mask_values: updated,
    update_mask_weights: updated.mask(),
    fractional_hidden_recovery: fractionalHiddenRecovery,
    map_sample: sample(mapValues),
    default_value_sample: sample(defaultValues),
    default_weight_sample: sample(defaultValues.mask()),
    setter_value_sample: sample(replaced),
    setter_weight_sample: sample(replaced.mask()),
    update_mask_value_sample: sample(updated),
    update_mask_weight_sample: sample(updated.mask()),
    fractional_hidden_recovery_value_sample: sample(fractionalHiddenRecovery),
    fractional_hidden_recovery_weight_sample: sample(fractionalHiddenRecovery.mask())
  };
}

exports.buildExpressionImages = buildExpressionImages;
exports.buildWorkflow = buildWorkflow;
