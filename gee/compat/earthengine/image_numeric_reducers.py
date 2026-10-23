"""Bounded Image and ImageCollection lowering for scalar numeric reducers."""
from __future__ import annotations

import math
from dataclasses import replace

from .composed_reducer_spec import MAX_REDUCER_NAME_CHARS
from .ir import Collection, Image, ImageSequence, Pixel, Source, fail
from .numeric_reducer_plan import MAX_NUMERIC_REDUCER_WORK, numeric_outputs
from .numeric_reducer_grid import require_common_grid


MAX_RASTER_NUMERIC_FRAMES = 1_000
MAX_RASTER_NUMERIC_BANDS = 10_000


def _charge(translator, amount: int) -> None:
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or amount < 0 or amount > MAX_NUMERIC_REDUCER_WORK
            or steps + amount > MAX_NUMERIC_REDUCER_WORK):
        fail("Raster numeric reducer exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _measure_bands(translator, image: Image, label: str):
    if not isinstance(image, Image) or type(image.bands) is not list:
        fail(f"{label} requires an Image with scalar bands")
    if not image.bands or len(image.bands) > MAX_RASTER_NUMERIC_BANDS:
        fail(f"{label} requires 1..10000 scalar bands")
    names = []
    pixels = []
    seen = set()
    for band in image.bands:
        if type(band) is not tuple or len(band) != 2:
            fail(f"{label} contains an invalid band descriptor")
        band_name, pixel = band
        if (type(band_name) is not str or not band_name
                or len(band_name) > MAX_REDUCER_NAME_CHARS):
            fail(f"{label} requires bounded nonempty band names")
        _charge(translator, 1 + len(band_name))
        if band_name in seen:
            fail(f"{label} requires unique input band names")
        if not isinstance(pixel, Pixel):
            fail(f"{label} supports scalar raster bands only")
        seen.add(band_name)
        names.append(band_name)
        pixels.append(pixel)
    return tuple(names), tuple(pixels)


def _lineage(translator, pixel: Pixel, label: str, walker):
    from .pixel_math_graph import _PixelFactsWalker

    if walker is None:
        walker = _PixelFactsWalker(translator)
    facts = walker.inspect(pixel)
    if len(facts.sources) != 1:
        fail(f"{label} requires each numeric input to have one finite source lineage")
    cid, ids = facts.sources[0]
    if type(cid) is not str or not cid or type(ids) is not tuple or not ids:
        fail(f"{label} requires a nonempty finite source lineage")
    return cid, ids


def _same_image_lineage(translator, pixels, label, expected=None, *, walker=None):
    from .pixel_math_graph import _PixelFactsWalker

    walker = _PixelFactsWalker(translator) if walker is None else walker
    first = expected
    for pixel in pixels:
        lineage = _lineage(translator, pixel, label, walker)
        if first is None:
            first = lineage
        if lineage != first:
            fail(f"{label} cannot merge distinct source lineages implicitly")
    return first


def _double(pixel: Pixel) -> Pixel:
    return pixel if pixel.op == "to_double" and len(pixel.args) == 1 else Pixel("to_double", (pixel,))


def _output_names(translator, input_names, outputs, label):
    count = len(input_names) * len(outputs)
    if not 1 <= count <= MAX_RASTER_NUMERIC_BANDS:
        fail(f"{label} output exceeds 10000 bands")
    chars = 0
    for band_name in input_names:
        for output_name, _ in outputs:
            length = len(band_name) + 1 + len(output_name)
            if length > MAX_REDUCER_NAME_CHARS:
                fail(f"{label} output band name exceeds the bounded length")
            chars += length
    # Reserve every final name and every output Pixel before concatenating a
    # band name or allocating a Raster IR node.
    _charge(translator, count + chars)
    names = tuple(
        band_name + "_" + output_name
        for band_name in input_names
        for output_name, _ in outputs
    )
    if len(set(names)) != len(names):
        fail(f"{label} output band names must be unique")
    return names


def _collection_reduction(translator, collection, outputs, label):
    if not isinstance(collection, Collection):
        fail("ImageCollection.reduce requires a local ImageCollection")
    source = collection.source
    if (not isinstance(source, Source) or type(source.cid) is not str
            or not source.cid or type(source.ids) is not tuple
            or not 1 <= len(source.ids) <= MAX_RASTER_NUMERIC_FRAMES):
        fail("ImageCollection.reduce requires 1..1000 finite local observations")
    names, pixels = _measure_bands(translator, collection.image, label)
    _same_image_lineage(
        translator, pixels, label, expected=(source.cid, source.ids),
    )
    require_common_grid(translator, pixels, label=label)
    output_names = _output_names(translator, names, outputs, label)
    _charge(translator, len(pixels) * len(outputs))
    bands = []
    index = 0
    for band_name, pixel in zip(names, pixels):
        for output_name, operation in outputs:
            bands.append((output_names[index], Pixel("reduce_t", (_double(pixel), operation))))
            index += 1
    return Image(
        bands, {}, source, inherit_props=False,
        footprint=collection.image.footprint,
        footprint_is_absolute=collection.image.footprint_is_absolute,
    )


def _sequence_reduction(translator, sequence, outputs, label):
    if not isinstance(sequence, ImageSequence):
        fail("ImageCollection.reduce requires an ImageSequence or ImageCollection")
    images = sequence.images
    if not 1 <= len(images) <= MAX_RASTER_NUMERIC_FRAMES:
        fail("ImageCollection.reduce requires 1..1000 finite local observations")

    frame_names = []
    frame_pixels = []
    for image in images:
        names, pixels = _measure_bands(translator, image, label)
        frame_names.append(names)
        frame_pixels.append(dict(zip(names, pixels)))

    _charge(translator, sum(len(names) for names in frame_names))
    frame_name_sets = [set(names) for names in frame_names]
    common_set = frame_name_sets[0].copy()
    for names in frame_name_sets[1:]:
        common_set.intersection_update(names)
    common = tuple(name for name in frame_names[0] if name in common_set)
    if not common:
        fail("ImageCollection.reduce requires at least one common band across frames")

    sources = []
    from .pixel_math_graph import _PixelFactsWalker

    walker = _PixelFactsWalker(translator)
    for index, image in enumerate(images):
        selected_pixels = tuple(frame_pixels[index][name] for name in common)
        lineage = _same_image_lineage(translator, selected_pixels, label, walker=walker)
        if len(lineage[1]) != 1:
            fail(f"{label} requires each ImageSequence frame to represent one observation")
        sources.append(lineage)
    first_cid = sources[0][0]
    if any(cid != first_cid for cid, _ in sources[1:]):
        fail(f"{label} cannot align frames from distinct collection lineages")
    require_common_grid(
        translator,
        tuple(frame_pixels[index][name]
              for index in range(len(images)) for name in common),
        label=label,
    )

    output_names = _output_names(translator, common, outputs, label)
    tuple_work = len(common) * len(images)
    pixel_work = len(common) * len(outputs)
    _charge(translator, tuple_work + pixel_work)

    bands = []
    index = 0
    for band_name in common:
        per_frame = tuple(
            _double(frame_pixels[frame_index][band_name])
            for frame_index in range(len(images))
        )
        for _, operation in outputs:
            bands.append((output_names[index], Pixel("reduce_bands", (per_frame, operation))))
            index += 1

    footprint = translator.footprint(sequence)
    return Image(
        bands, {}, images[0].source, inherit_props=False,
        footprint=footprint, footprint_is_absolute=True,
    )


def invoke_raster_numeric_reducer(translator, name, args):
    """Lower supported numeric Image.reduce and ImageCollection.reduce calls."""
    if name == "Image.reduce":
        translator.allowed(args, {"image", "reducer"})
        outputs = numeric_outputs(translator, args.get("reducer"))
        image = args.get("image")
        if not isinstance(image, Image):
            fail("Image.reduce requires an Image")
        names, pixels = _measure_bands(translator, image, name)
        _same_image_lineage(translator, pixels, name)
        _charge(translator, len(pixels) + len(outputs) * 2)
        stack = tuple(_double(pixel) for pixel in pixels)
        return replace(image, bands=[
            (output_name, Pixel("reduce_bands", (stack, operation)))
            for output_name, operation in outputs
        ])

    if name != "ImageCollection.reduce":
        fail(f"Unsupported raster numeric reducer operation: {name}")
    translator.allowed(args, {"collection", "reducer", "parallelScale"})
    parallel_scale = args.get("parallelScale", 1)
    if (isinstance(parallel_scale, bool) or type(parallel_scale) not in (int, float)
            or type(parallel_scale) is float and not math.isfinite(parallel_scale)
            or parallel_scale < 1):
        fail("ImageCollection.reduce parallelScale must be finite and >= 1")
    if parallel_scale != 1:
        fail("ImageCollection.reduce currently supports only the default parallelScale of 1")
    outputs = numeric_outputs(translator, args.get("reducer"))
    collection = args.get("collection")
    if isinstance(collection, Collection):
        return _collection_reduction(translator, collection, outputs, name)
    if isinstance(collection, ImageSequence):
        return _sequence_reduction(translator, collection, outputs, name)
    fail("ImageCollection.reduce requires an ImageSequence or ImageCollection")
