// Compose color transforms and staged calibration on the Wave57 synthetic grid.
function sceneImage(ee, fixture, itemId) {
  return ee.ImageCollection(fixture.stac.collection.id)
    .filter(ee.Filter.eq('system:index', itemId))
    .first();
}

function buildWorkflow(ee, image, fixture) {
  var source = ee.Image(image)
    .select(fixture.source_band_order, fixture.prepared_band_order)
    .toDouble();
  var rgb = source.select(['red', 'green', 'blue']);
  var hsv = ee.Image(rgb.rgbToHsv());

  var halfValue = ee.Image(hsv.select('value').multiply(0.5).rename('value'));
  var halfHsv = ee.Image(hsv.select('hue')
    .addBands(hsv.select('saturation'))
    .addBands(halfValue));
  var valueHalfRgb = ee.Image(halfHsv.hsvToRgb());

  var rgbRoundtrip = ee.Image(ee.Image(rgb.rgbToHsv()).hsvToRgb());
  var calibrated = ee.Image(rgbRoundtrip.add(0.05)
    .toFloat()
    .toDouble()
    .max(0)
    .min(0.65));
  return {
    hsv_value_half_then_rgb: valueHalfRgb,
    rgb_roundtrip_offset_float_stage_clamp: calibrated
  };
}

if (typeof module !== 'undefined') {
  module.exports = {sceneImage: sceneImage, buildWorkflow: buildWorkflow};
}
