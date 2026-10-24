// Wave66 local policy: one direct fractional carrier and an unmasked constant
// preserve the carrier weight. Invalid math outputs become NoData. This is not
// a Google-parity claim, and this example does not combine two fractional masks.
function append(images, name, image) {
  images.push(image.rename(name));
}

function maskedSource(ee, source, band) {
  return source.select(band).toDouble().updateMask(source.select(band + '_weight'));
}

function resultNames(fixture) {
  var names = [];
  fixture.bands.forEach(function(band) {
    fixture.operations.unary.forEach(function(op) {
      names.push(band + '_' + op.toLowerCase());
    });
  });
  fixture.operations.binary.forEach(function(op) {
    names.push('wide_' + op.toLowerCase() + '_right');
    names.push('wide_' + op.toLowerCase() + '_left');
  });
  names.push('red_and_zero', 'red_zero_and', 'red_or_zero', 'red_zero_or',
    'red_clamp', 'red_unit_scale');
  fixture.operations.pixel_math_unary.forEach(function(op) {
    names.push('wide_pixel_' + op.toLowerCase());
  });
  fixture.operations.pixel_math_binary.forEach(function(op) {
    names.push('wide_pixel_' + op.toLowerCase() + '_right');
    names.push('wide_pixel_' + op.toLowerCase() + '_left');
  });
  names.push('wide_to_float', 'wide_float32_asin');
  return names;
}

function buildOperationImages(ee, image, fixture) {
  var source = ee.Image(image);
  var operations = fixture.operations;
  var masked = {};
  fixture.bands.forEach(function(band) {
    masked[band] = maskedSource(ee, source, band);
  });
  var results = [];
  fixture.bands.forEach(function(band) {
    operations.unary.forEach(function(name) {
      var method = name === 'Not' ? 'not' : name;
      append(results, band + '_' + name.toLowerCase(), masked[band][method]());
    });
  });

  var wide = masked.wide;
  var constant = ee.Image.constant(operations.binary_constant);
  operations.binary.forEach(function(name) {
    var method = name === 'And' ? 'and' : name === 'Or' ? 'or' : name;
    append(results, 'wide_' + name.toLowerCase() + '_right', wide[method](constant));
    append(results, 'wide_' + name.toLowerCase() + '_left', constant[method](wide));
  });

  var red = masked.red;
  var zero = ee.Image.constant(operations.logic_zero);
  append(results, 'red_and_zero', red.and(zero));
  append(results, 'red_zero_and', zero.and(red));
  append(results, 'red_or_zero', red.or(zero));
  append(results, 'red_zero_or', zero.or(red));
  append(results, 'red_clamp', red.clamp(operations.clamp[0], operations.clamp[1]));
  append(results, 'red_unit_scale', red.unitScale(
    operations.unit_scale[0], operations.unit_scale[1]));

  var wideFloat = wide.toFloat();
  operations.pixel_math_unary.forEach(function(name) {
    append(results, 'wide_pixel_' + name.toLowerCase(), wideFloat[name]());
  });
  var atan2Constant = ee.Image.constant(operations.atan2_constant).toFloat();
  operations.pixel_math_binary.forEach(function(name) {
    append(results, 'wide_pixel_' + name.toLowerCase() + '_right',
      wideFloat[name](atan2Constant));
    append(results, 'wide_pixel_' + name.toLowerCase() + '_left',
      atan2Constant[name](wideFloat));
  });

  append(results, 'wide_to_float', wideFloat);
  append(results, 'wide_float32_asin', wideFloat.asin());
  var allNames = resultNames(fixture);
  if (results.length !== allNames.length || new Set(allNames).size !== allNames.length) {
    throw Error('operation result names must match generated images exactly');
  }
  return Object.fromEntries(allNames.map(function(name, index) {
    return [name, results[index]];
  }));
}

function buildWorkflow(ee, image, fixture) {
  var resultMap = buildOperationImages(ee, image, fixture);
  var selected = fixture.sample_outputs;
  if (new Set(selected).size !== selected.length || selected.some(function(name) {
    return !Object.prototype.hasOwnProperty.call(resultMap, name);
  })) throw Error('sample_outputs must name distinct generated result bands');
  var sampleResults = selected.map(function(name) { return resultMap[name]; });
  var values = ee.Image.cat.apply(null, sampleResults);
  var weights = ee.Image.cat.apply(null, sampleResults.map(function(result, index) {
    return result.mask().rename('mask_' + selected[index]);
  }));
  var region = ee.Geometry(fixture.sample_region);
  return {
    values: values,
    weights: weights,
    values_sample: values.sample({region: region, dropNulls: false, geometries: true}),
    weights_sample: weights.sample({region: region, dropNulls: false, geometries: true})
  };
}

function syntheticMetadata(fixture) {
  var bands = fixture.bands.concat(fixture.weight_bands);
  var grid = fixture.grid;
  var ring = [[grid.xmin, grid.ymin], [grid.xmax, grid.ymin],
    [grid.xmax, grid.ymax], [grid.xmin, grid.ymax], [grid.xmin, grid.ymin]];
  var collection = {id: fixture.source_id, 'cube:dimensions': {
    bands: {values: bands}
  }};
  var item = {
    id: 'wave66-synthetic-source',
    bbox: [grid.xmin, grid.ymin, grid.xmax, grid.ymax],
    geometry: {type: 'Polygon', coordinates: [ring]},
    properties: {
      'system:index': 'wave66-synthetic-source', 'system:time_start': 1,
      'proj:code': 'EPSG:4326', 'proj:transform': [1, 0, 0, 0, -1, 2]
    },
    assets: {}
  };
  bands.forEach(function(band) {
    item.assets[band] = {
      'proj:shape': [2, 4], 'proj:epsg': 4326,
      'proj:transform': [1, 0, 0, 0, -1, 2]
    };
  });
  return [{id: collection.id, 'cube:dimensions': collection['cube:dimensions']}],
    {[collection.id]: [item]};
}

if (typeof module !== 'undefined') {
  module.exports = {
    buildOperationImages: buildOperationImages,
    buildWorkflow: buildWorkflow,
    syntheticMetadata: syntheticMetadata
  };
}
