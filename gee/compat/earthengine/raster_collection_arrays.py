"""Bounded fixed-shape ImageCollection array construction."""
from __future__ import annotations

from .array_core import charge_array
from .ir import (
    Collection, Image, ImageSequence, Pixel, combine_clip_footprints,
    fail, integer,
)
from .raster_array_bands import wrap_array_bands
from .raster_array_core import (
    MAX_RASTER_ARRAY_CELLS,
    combined_mask,
    wrap_array_image,
)
from .raster_regression_frames import (
    collection_frame_count,
    collection_frames,
    scalar_collection_rows,
)


COLLECTION_ARRAY_FUNCTIONS = frozenset({"ImageCollection.toArrayPerBand"})
_NAME = "ImageCollection.toArrayPerBand"


def _required(arguments, parameter):
    if parameter not in arguments:
        fail(f"{_NAME} requires the {parameter} argument")
    return arguments[parameter]


def _schema_image(collection):
    if isinstance(collection, Collection):
        image = collection.image
    elif isinstance(collection, ImageSequence):
        image = collection.images[0]
    else:
        fail(f"{_NAME} requires an ImageCollection")
    if not isinstance(image, Image):
        fail(f"{_NAME} requires scalar Image frames")
    band_count = len(image.bands)
    if not 1 <= band_count <= 8:
        fail(f"{_NAME} supports 1..8 scalar bands per frame")
    return image, band_count


def _preflight(translator, frame_count, band_count):
    cells = frame_count * band_count
    if cells > MAX_RASTER_ARRAY_CELLS:
        fail(f"{_NAME} output exceeds the shared 64-cell limit")
    # Reserve ordered frame expansion, schema/cell scans, per-band validity
    # expressions, and output array construction before materializing frames.
    charge_array(translator, 32 + frame_count * band_count * 6
                 + frame_count * 4 + band_count * 8)


def invoke_collection_array(translator, name, arguments):
    """Stack finite scalar ImageCollection frames into one array per band."""
    if name not in COLLECTION_ARRAY_FUNCTIONS:
        fail(f"Unsupported raster collection array operation: {name}")
    translator.allowed(arguments, {"collection", "axis", "dropMasked"})
    collection = _required(arguments, "collection")

    axis = integer(arguments.get("axis", 0), f"{_NAME} axis")
    if axis != 0:
        fail(f"{_NAME} currently supports only integer axis=0")
    drop_masked = arguments.get("dropMasked", False)
    if type(drop_masked) is not bool:
        fail(f"{_NAME} dropMasked must be a boolean")
    if drop_masked:
        fail(f"{_NAME} dropMasked=true requires unsupported dynamic output shapes")

    frame_count = collection_frame_count(collection, _NAME)
    _, band_count = _schema_image(collection)
    _preflight(translator, frame_count, band_count)
    frames = collection_frames(translator, collection, _NAME)
    rows = scalar_collection_rows(frames, band_count, _NAME)
    names = tuple(name for name, _ in frames[0].bands)

    footprint = translator.footprint(ImageSequence(frames))
    # Array output is tied to every frame's pixels and the union footprint,
    # while image-level properties do not inherit one arbitrary frame's date.
    base_image = Image(
        [], {}, frames[0].source, inherit_props=False,
        footprint=footprint, footprint_is_absolute=True,
        clip_footprint=combine_clip_footprints(
            *(frame.clip_footprint for frame in frames)
        ),
    )

    arrays = []
    for band_index, band_name in enumerate(names):
        cells = tuple(row[band_index] for row in rows)
        valid = tuple(
            Pixel("not", (Pixel("is_nodata", (pixel,), True),), True)
            for pixel in cells
        )
        mask = combined_mask(*valid)
        arrays.append(wrap_array_image(
            base_image, (frame_count,), cells, mask, band_name,
        ))

    if len(arrays) == 1:
        return arrays[0]
    return wrap_array_bands(translator, base_image, tuple(arrays))
