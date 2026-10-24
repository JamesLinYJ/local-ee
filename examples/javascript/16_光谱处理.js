// 固定合成 STAC 场景的 RGB/HSV、波段校准和端元分解工作流；不请求 Google。

var SYNTHETIC_VERSION = 'local-ee-synthetic-spectral-preparation/v1';
var COPY_PROPERTIES = ['system:index', 'system:time_start', 'workflow'];

function sceneImage(ee, fixture, itemId) {
  return ee.ImageCollection(fixture.stac.collection.id)
    .filter(ee.Filter.eq('system:index', itemId))
    .first();
}

function buildWorkflow(ee, image, fixture) {
  var source = ee.Image(image)
    .select(fixture.source_band_order, fixture.prepared_band_order)
    .toDouble()
    .set('workflow', SYNTHETIC_VERSION);

  // RGB order is explicit; the local source stores blue, green, red.
  var rgb = source.select(['red', 'green', 'blue']);
  var hsv = ee.Image(ee.Image(rgb.rgbToHsv())
    .copyProperties(source, COPY_PROPERTIES));
  var roundTrip = ee.Image(ee.Image(hsv.hsvToRgb())
    .copyProperties(source, COPY_PROPERTIES));

  var calibration = fixture.calibration;
  var redLut = ee.Image(ee.Image(source.select('red')
    .interpolate(calibration.lut_input, calibration.lut_output,
      calibration.interpolation_behavior))
    .rename('red_lut')
    .copyProperties(source, COPY_PROPERTIES));
  var greenPolynomial = ee.Image(ee.Image(source.select('green')
    .polynomial(calibration.polynomial_coefficients_ascending))
    .rename('green_polynomial')
    .copyProperties(source, COPY_PROPERTIES));

  var unmix = fixture.unmix;
  var orderedSpectra = source.select(unmix.input_band_order);
  var fractions = ee.Image(ee.Image(orderedSpectra.unmix(unmix.endmembers,
    unmix.flags.sumToOne, unmix.flags.nonNegative))
    .copyProperties(source, COPY_PROPERTIES));
  return {
    rgb_to_hsv: hsv,
    rgb_roundtrip: roundTrip,
    red_lut: redLut,
    green_polynomial: greenPolynomial,
    unmixed_fractions: fractions
  };
}

if (typeof module !== 'undefined') {
  module.exports = {sceneImage: sceneImage, buildWorkflow: buildWorkflow};
}
