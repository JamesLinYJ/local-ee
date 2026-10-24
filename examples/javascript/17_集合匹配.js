// Local QA linking example. All assets must already exist in the local catalog.
// The versioned synthetic fixture is shared with the Python example.
function buildCollectionLinkWorkflow(ee, fixture) {
  const base = ee.ImageCollection(fixture.catalog[0].id);
  const primary = base.filter(ee.Filter.eq('side', 'primary')).select(['red', 'nir']);
  const quality = base.filter(ee.Filter.eq('side', 'qa'));
  const linked = primary.map(image => ee.Image(image).linkCollection(
    quality, ['qa'], ['qa_version']));
  const first = ee.Image(linked.filter(ee.Filter.eq('system:index', 'a')).first());
  const missing = ee.Image(linked.filter(ee.Filter.eq('system:index', 'b')).first());
  const last = ee.Image(linked.filter(ee.Filter.eq('system:index', 'c')).first());
  const extra = quality.select(['nir', 'qa']);
  const keep = primary.combine(extra, false);
  const overwrite = primary.combine(extra, true);
  return {
    linked_collection: linked,
    linked_a: first,
    linked_b: missing,
    linked_c: last,
    custom_key_a: ee.Image(primary.first()).linkCollection(
      quality, ['qa'], ['qa_version'], 'scene'),
    clear_a: first.select(['red', 'nir']).updateMask(first.select('qa').lt(50)),
    keep_collection: keep,
    keep_a: ee.Image(keep.first()),
    overwrite_a: ee.Image(overwrite.first()),
    version_a: first.get('qa_version'),
    version_b: missing.get('qa_version'),
    primary_index_after_link: first.get('system:index'),
    primary_actual_id_after_link: first.id()
  };
}
