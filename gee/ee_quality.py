"""Quality composites keep every output band tied to the same winning scene."""
from .ee_collections import _sequence_clip_footprint, frames
from .compat.earthengine.ir import Image, ImageSequence, Pixel, const, fail


def quality_mosaic(translator, collection, quality_band):
    if not isinstance(quality_band, str) or not quality_band:
        fail('qualityMosaic requires a nonempty quality band name')
    images = frames(translator, collection)
    if not images:
        fail('qualityMosaic cannot reduce an empty local ImageCollection')
    names = [name for name, _ in images[0].bands]
    if quality_band not in names:
        fail('qualityMosaic quality band is unavailable: ' + quality_band)
    if any([name for name, _ in image.bands] != names for image in images):
        fail('qualityMosaic currently requires identical band names and order in every image')
    first = dict(images[0].bands)
    best = first[quality_band]
    # A valid payload under an invalid quality pixel is not a candidate.
    output = {name: Pixel('preserve_mask', (value, best)) for name, value in first.items()}
    for image in images[1:]:
        bands = dict(image.bands)
        candidate = bands[quality_band]
        # Resolve missing values explicitly before comparing quality. A masked
        # payload in the winning scene stays masked; it must not fall back to a
        # lower-quality scene as an ordinary per-band mosaic would.
        better = Pixel('if', (
            Pixel('is_nodata', (best,), True), const(1),
            Pixel('gte', (candidate, best), True)), True)
        take = Pixel('if', (
            Pixel('is_nodata', (candidate,), True), const(0), better), True)
        output = {name: Pixel('if', (take, bands[name], value)) for name, value in output.items()}
        best = Pixel('if', (take, candidate, best))
    translator.warn('qualityMosaic uses the last image in collection order for equal quality; this tie policy has not been compared against the Google service.')
    return Image(list(output.items()), {}, images[0].source, inherit_props=False,
                 footprint=translator.footprint(ImageSequence(images)),
                 footprint_is_absolute=True,
                 clip_footprint=_sequence_clip_footprint(translator, images))
