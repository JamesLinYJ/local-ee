"""Bounded per-pixel linearFit over explicitly ordered raster frames."""
from __future__ import annotations

from .array_core import charge_array
from .ir import Collection, Image, ImageSequence, Pixel, const, fail, rebind
from .table_reducers import TableReducer


MAX_LINEAR_FIT_FRAMES = 8


def _frames(translator, value):
    """Normalize a small collection without losing each source item's identity."""
    if isinstance(value, ImageSequence):
        count = len(value.images)
        if count == 0:
            fail("ImageCollection.reduce linearFit requires at least one frame")
        if count > MAX_LINEAR_FIT_FRAMES:
            fail("ImageCollection.reduce linearFit supports at most 8 frames")
        return list(value.images)
    if isinstance(value, Collection):
        count = len(value.source.ids)
        if count == 0:
            fail("ImageCollection.reduce linearFit requires at least one frame")
        if count > MAX_LINEAR_FIT_FRAMES:
            fail("ImageCollection.reduce linearFit supports at most 8 frames")
        return [translator.first(rebind(value, (item_id,))) for item_id in value.source.ids]
    fail("ImageCollection.reduce linearFit requires an ImageCollection")


def _validate_frames(images):
    expected_names = None
    rows = []
    for image in images:
        if not isinstance(image, Image) or len(image.bands) != 2:
            fail("ImageCollection.reduce linearFit requires exactly two scalar bands per frame")
        names = tuple(name for name, _ in image.bands)
        if (any(not isinstance(name, str) or not name for name in names)
                or len(set(names)) != 2):
            fail("ImageCollection.reduce linearFit requires two distinct named bands")
        if expected_names is None:
            expected_names = names
        elif names != expected_names:
            fail("ImageCollection.reduce linearFit requires the same band names and order in every frame")
        x, y = (pixel for _, pixel in image.bands)
        if not isinstance(x, Pixel) or not isinstance(y, Pixel):
            fail("ImageCollection.reduce linearFit supports scalar bands only")
        rows.append((x, y))
    return rows


def invoke_raster_linear_fit(translator, name, arguments):
    """Lower the supported two-input image linearFit reducer to scalar pixel IR."""
    if name != "ImageCollection.reduce":
        fail(f"Unsupported raster regression operation: {name}")
    translator.allowed(arguments, {"collection", "reducer", "parallelScale"})

    reducer = arguments.get("reducer")
    if (not isinstance(reducer, TableReducer) or reducer.name != "linearFit"
            or reducer.num_x != 1 or reducer.num_y != 1):
        fail("ImageCollection.reduce requires a two-input linearFit Reducer")
    if "parallelScale" in arguments:
        parallel_scale = arguments["parallelScale"]
        if (isinstance(parallel_scale, bool)
                or not isinstance(parallel_scale, (int, float))
                or parallel_scale != 1):
            fail("ImageCollection.reduce linearFit supports only the default parallelScale of 1")

    images = _frames(translator, arguments.get("collection"))
    rows = _validate_frames(images)
    footprint = translator.footprint(ImageSequence(images))

    # Reserve the bounded per-frame normalization, two centered passes, and
    # final validity expressions before constructing any Pixel IR.
    charge_array(translator, len(rows) * 16 + 32)

    xs = []
    ys = []
    valid_rows = []
    for x, y in rows:
        valid_x = Pixel("not", (Pixel("is_nodata", (x,), True),), True)
        valid_y = Pixel("not", (Pixel("is_nodata", (y,), True),), True)
        valid = Pixel("and", (valid_x, valid_y), True)
        xs.append(Pixel("if", (valid, x, const(None))))
        ys.append(Pixel("if", (valid, y, const(None))))
        valid_rows.append(Pixel("if", (valid, const(1), const(None))))

    mean_x = Pixel("reduce_bands", (tuple(xs), "mean"))
    mean_y = Pixel("reduce_bands", (tuple(ys), "mean"))
    deviations_x = [Pixel("subtract", (x, mean_x)) for x in xs]
    deviations_y = [Pixel("subtract", (y, mean_y)) for y in ys]
    sxx = Pixel("reduce_bands", (
        tuple(Pixel("multiply", (dx, dx)) for dx in deviations_x), "sum",
    ))
    sxy = Pixel("reduce_bands", (
        tuple(Pixel("multiply", (dx, dy)) for dx, dy in zip(deviations_x, deviations_y)),
        "sum",
    ))
    count = Pixel("reduce_bands", (tuple(valid_rows), "count"))

    enough_rows = Pixel("gte", (count, const(2)), True)
    varying_x = Pixel("gt", (sxx, const(0)), True)
    fit_is_valid = Pixel("and", (enough_rows, varying_x), True)
    scale = Pixel("divide", (sxy, sxx))
    offset = Pixel("subtract", (mean_y, Pixel("multiply", (scale, mean_x))))
    masked_scale = Pixel("if", (fit_is_valid, scale, const(None)))
    masked_offset = Pixel("if", (fit_is_valid, offset, const(None)))

    return Image(
        [("scale", masked_scale), ("offset", masked_offset)],
        {},
        images[0].source,
        inherit_props=False,
        footprint=footprint,
        footprint_is_absolute=True,
    )
