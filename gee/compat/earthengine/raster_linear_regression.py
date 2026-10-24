"""Bounded per-pixel multi-response linearRegression over raster frames."""
from __future__ import annotations

import math

from .array_core import charge_array
from .ir import (
    Collection, Image, ImageSequence, Pixel, combine_clip_footprints, const, fail,
)
from .raster_array_bands import wrap_array_bands
from .raster_array_core import wrap_array_image
from .raster_regression_frames import regression_frames, scalar_regression_rows
from .table_reducers import TableReducer


def _literal_one(pixel):
    """Prove a predictor is a numeric literal one without dropping masks."""
    if not isinstance(pixel, Pixel):
        return False
    if pixel.op in {"to_float", "to_double"} and len(pixel.args) == 1:
        return _literal_one(pixel.args[0])
    if pixel.op == "reduce_t" and len(pixel.args) == 2 and pixel.args[1] == "first":
        return _literal_one(pixel.args[0])
    if pixel.op == "constant" and len(pixel.args) == 1:
        value = pixel.args[0]
        if type(value) is int:
            return value == 1
        return type(value) is float and math.isfinite(value) and value == 1
    if pixel.op == "on_grid" and len(pixel.args) == 5:
        return _literal_one(pixel.args[0])
    return False


def _not_nodata(pixel):
    return Pixel("not", (Pixel("is_nodata", (pixel,), True),), True)


def _and(left, right):
    return Pixel("and", (left, right), True)


def _sum(pixels):
    return Pixel("reduce_bands", (tuple(pixels), "sum"))


def _regression_rows(rows):
    values = []
    valid = []
    for row in rows:
        mask = _not_nodata(row[0])
        for pixel in row[1:]:
            mask = _and(mask, _not_nodata(pixel))
        valid.append(Pixel("if", (mask, const(1), const(None))))
        values.append(tuple(Pixel("if", (mask, pixel, const(None))) for pixel in row))
    count = Pixel("reduce_bands", (tuple(valid), "count"))
    return values, count


def _through_origin(values, count, num_y):
    predictors = [row[0] for row in values]
    sum_x2 = _sum([Pixel("multiply", (x, x)) for x in predictors])
    fit_mask = _and(
        Pixel("gte", (count, const(2)), True),
        Pixel("gt", (sum_x2, const(0)), True),
    )
    coefficients = []
    residuals = []
    for response_index in range(num_y):
        response = [row[1 + response_index] for row in values]
        beta = Pixel("divide", (
            _sum([Pixel("multiply", (x, y)) for x, y in zip(predictors, response)]),
            sum_x2,
        ))
        coefficients.append(beta)
        errors = [Pixel("subtract", (y, Pixel("multiply", (x, beta))))
                  for x, y in zip(predictors, response)]
        residuals.append(Pixel("sqrt", (Pixel("divide", (
            _sum([Pixel("multiply", (error, error)) for error in errors]), count,
        )),)))
    return tuple(coefficients), tuple(residuals), fit_mask


def _with_intercept(values, count, num_y):
    predictors = [row[1] for row in values]
    mean_x = Pixel("reduce_bands", (tuple(predictors), "mean"))
    deviations_x = [Pixel("subtract", (x, mean_x)) for x in predictors]
    sum_xx = _sum([Pixel("multiply", (dx, dx)) for dx in deviations_x])
    fit_mask = _and(
        Pixel("gte", (count, const(3)), True),
        Pixel("gt", (sum_xx, const(0)), True),
    )
    intercepts = []
    slopes = []
    residuals = []
    for response_index in range(num_y):
        response = [row[2 + response_index] for row in values]
        mean_y = Pixel("reduce_bands", (tuple(response), "mean"))
        deviations_y = [Pixel("subtract", (y, mean_y)) for y in response]
        sum_xy = _sum([
            Pixel("multiply", (dx, dy))
            for dx, dy in zip(deviations_x, deviations_y)
        ])
        slope = Pixel("divide", (sum_xy, sum_xx))
        intercept = Pixel("subtract", (mean_y, Pixel("multiply", (slope, mean_x))))
        intercepts.append(intercept)
        slopes.append(slope)
        errors = [Pixel("subtract", (y, Pixel("add", (
            intercept, Pixel("multiply", (slope, x)),
        )))) for x, y in zip(predictors, response)]
        residuals.append(Pixel("sqrt", (Pixel("divide", (
            _sum([Pixel("multiply", (error, error)) for error in errors]), count,
        )),)))
    return tuple(intercepts + slopes), tuple(residuals), fit_mask


def invoke_raster_linear_regression(translator, name, arguments):
    """Evaluate only finite scalar ImageCollection linearRegression reducers."""
    if name != "ImageCollection.reduce":
        fail(f"Unsupported raster regression operation: {name}")
    translator.allowed(arguments, {"collection", "reducer", "parallelScale"})
    for required in ("collection", "reducer"):
        if required not in arguments:
            fail(f"ImageCollection.reduce linearRegression requires {required}")
    reducer = arguments["reducer"]
    if (not isinstance(reducer, TableReducer) or reducer.name != "linearRegression"
            or type(reducer.num_x) is not int or not 1 <= reducer.num_x <= 2
            or type(reducer.num_y) is not int or not 1 <= reducer.num_y <= 4):
        fail("ImageCollection.reduce requires linearRegression with numX=1..2 and numY=1..4")
    if "parallelScale" in arguments:
        scale = arguments["parallelScale"]
        if (isinstance(scale, bool) or type(scale) not in (int, float)
                or (type(scale) is float and not math.isfinite(scale)) or scale != 1):
            fail("ImageCollection.reduce linearRegression supports only parallelScale=1")

    collection = arguments["collection"]
    if isinstance(collection, ImageSequence):
        frame_count = len(collection.images)
    elif isinstance(collection, Collection):
        frame_count = len(collection.source.ids)
    else:
        fail("ImageCollection.reduce linearRegression requires an ImageCollection")
    if not 1 <= frame_count <= 8:
        fail("ImageCollection.reduce linearRegression requires 1..8 frames")
    inputs = reducer.num_x + reducer.num_y
    charge_array(translator, frame_count * (inputs + 3) + 16 * reducer.num_y + 32)
    images = regression_frames(translator, collection, "linearRegression")
    rows = scalar_regression_rows(images, inputs, "linearRegression")
    if reducer.num_x == 2 and any(not _literal_one(row[0]) for row in rows):
        fail("linearRegression numX=2 currently requires literal-one first predictors")
    footprint = translator.footprint(ImageSequence(images))
    base_image = Image(
        [], {}, images[0].source, inherit_props=False,
        footprint=footprint, footprint_is_absolute=True,
        clip_footprint=combine_clip_footprints(
            *(image.clip_footprint for image in images)
        ),
    )

    # Bound the complete-case expressions, both centered passes and outputs
    # before materializing any pixel-expression tuples.
    charge_array(translator, frame_count * (inputs * 5 + 12) + reducer.num_y * 32 + 64)
    values, count = _regression_rows(rows)
    if reducer.num_x == 1:
        coefficients, residuals, fit_mask = _through_origin(values, count, reducer.num_y)
    else:
        coefficients, residuals, fit_mask = _with_intercept(values, count, reducer.num_y)
    coefficient_array = wrap_array_image(
        base_image, (reducer.num_x, reducer.num_y), coefficients, fit_mask,
        "coefficients",
    )
    residual_array = wrap_array_image(
        base_image, (reducer.num_y,), residuals, fit_mask, "residuals",
    )
    return wrap_array_bands(
        translator, base_image, (coefficient_array, residual_array),
    )
