// The numeric mask views can use ordinary local map/export paths.
// Weighted scientific values still need their dedicated consumers.
function buildWorkflow(ee, image) {
  var source = ee.Image(image).select(['red', 'nir']).toDouble();
  var weighted = source.updateMask(ee.Image.constant([0.25, 0.75]));
  return {
    weights_by_band: weighted.mask(),
    weights_after_update: weighted.updateMask(0.5).mask(),
    selected_weight: weighted.select('nir').mask().rename('nir_weight'),
    source_validity: source.mask()
  };
}

if (typeof module !== 'undefined') {
  module.exports = {buildWorkflow: buildWorkflow};
}
