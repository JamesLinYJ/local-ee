"""Bounded source-frame and ordered scalar-schema checks for raster regressions."""
from __future__ import annotations

from .ir import Collection, Image, ImageSequence, Pixel, fail, rebind


MAX_REGRESSION_FRAMES = 8


def collection_frame_count(value, label):
    if isinstance(value, ImageSequence):
        count = len(value.images)
        if not count:
            fail(label + " requires at least one frame")
        if count > MAX_REGRESSION_FRAMES:
            fail(label + " supports at most 8 frames")
        return count
    if isinstance(value, Collection):
        count = len(value.source.ids)
        if not count:
            fail(label + " requires at least one frame")
        if count > MAX_REGRESSION_FRAMES:
            fail(label + " supports at most 8 frames")
        return count
    fail(label + " requires an ImageCollection")


def collection_frames(translator, value, label):
    """Materialize a bounded ordered ImageCollection as individual frames."""
    collection_frame_count(value, label)
    if isinstance(value, ImageSequence):
        return list(value.images)
    return [translator.first(rebind(value, (item_id,))) for item_id in value.source.ids]


def regression_frames(translator, value, operation):
    label = "ImageCollection.reduce " + operation
    return collection_frames(translator, value, label)


def scalar_collection_rows(images, inputs, label):
    count_name = "two" if inputs == 2 else str(inputs)
    expected_names = None
    rows = []
    for image in images:
        if not isinstance(image, Image) or len(image.bands) != inputs:
            fail(label + f" requires exactly {count_name} scalar bands per frame")
        names = tuple(name for name, _ in image.bands)
        if (any(not isinstance(name, str) or not name for name in names)
                or len(set(names)) != inputs):
            fail(label + f" requires {count_name} distinct named bands")
        if expected_names is None:
            expected_names = names
        elif names != expected_names:
            fail(label + " requires the same band names and order in every frame")
        row = tuple(pixel for _, pixel in image.bands)
        if any(not isinstance(pixel, Pixel) for pixel in row):
            fail(label + " supports scalar bands only")
        rows.append(row)
    return rows


def scalar_regression_rows(images, inputs, operation):
    label = "ImageCollection.reduce " + operation
    return scalar_collection_rows(images, inputs, label)
