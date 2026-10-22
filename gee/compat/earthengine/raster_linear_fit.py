"""Bounded per-pixel linearFit over explicitly ordered raster frames."""
from __future__ import annotations

from .array_core import charge_array
from .ir import Image, ImageSequence, Pixel, const, fail
from .raster_regression_frames import regression_frames, scalar_regression_rows
from .table_reducers import TableReducer


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

    images = regression_frames(translator, arguments.get("collection"), "linearFit")
    rows = scalar_regression_rows(images, 2, "linearFit")
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
