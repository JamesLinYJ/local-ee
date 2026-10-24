// The source dataset must already exist locally. No Google authentication.
function buildWorkflow(ee, fixture) {
  const parameters = fixture.workflow;
  const image = ee.ImageCollection(parameters.collection_alias).first()
    .select(parameters.real_band);
  const roi = ee.Geometry.Polygon(parameters.roi.coordinates);
  const scan = ee.Geometry.Rectangle([100, 30, 101, 31], null, false);
  const clipped = image.clip(roi);
  return {
    weights: clipped.mask(),
    default_science_sample: clipped.sample({geometries: true}),
    calibrated_science_sample: clipped.multiply(2).sample({geometries: true}),
    explicit_weight_sample: clipped.mask().sample({
      region: scan, dropNulls: false, geometries: true
    })
  };
}

if (typeof module !== 'undefined') module.exports = {buildWorkflow};
