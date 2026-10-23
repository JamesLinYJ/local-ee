"""Bounded Earth Engine Image.fastDistanceTransform compiler inputs."""
from __future__ import annotations

import math
from dataclasses import replace

from .ir import Image, Pixel, fail


FAST_DISTANCE_FUNCTIONS = frozenset({"Image.fastDistanceTransform"})
_ARGUMENTS = {"image", "neighborhood", "units", "metric"}
_MAX_BANDS = 10_000
_MAX_NAME_CHARS = 10_000
_MAX_WORK = 50_000
_MAX_NEIGHBORHOOD = 4096
_METRICS = frozenset({"squared_euclidean", "manhattan", "chebyshev"})


def _charge(translator, amount: int, label: str) -> None:
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or type(amount) is not int or amount < 0
            or steps + amount > _MAX_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _neighborhood(value) -> int:
    if type(value) is int:
        if 1 <= value <= _MAX_NEIGHBORHOOD:
            return value
        fail("Image.fastDistanceTransform neighborhood must be an integer in 1..4096 pixels")
    if (type(value) is not float or not math.isfinite(value)
            or int(value) != value or not 1 <= value <= _MAX_NEIGHBORHOOD):
        fail("Image.fastDistanceTransform neighborhood must be an integer in 1..4096 pixels")
    return int(value)


def _parameters(translator, arguments):
    translator.allowed(arguments, _ARGUMENTS)
    if "image" not in arguments:
        fail("Image.fastDistanceTransform requires image")

    neighborhood_value = arguments.get("neighborhood")
    if neighborhood_value is None:
        neighborhood_value = 256
    neighborhood = _neighborhood(neighborhood_value)

    units = arguments.get("units")
    if units is None:
        units = "pixels"
    if type(units) is not str or units != "pixels":
        fail("Image.fastDistanceTransform supports pixel units only")

    metric = arguments.get("metric")
    if metric is None:
        metric = "squared_euclidean"
    if type(metric) is not str or metric not in _METRICS:
        fail("Image.fastDistanceTransform metric must be squared_euclidean, manhattan or chebyshev")

    # The wire is a short fixed-size JSON object. Charge before its encoder
    # constructs the owned canonical string.
    _charge(translator, 128, "Image.fastDistanceTransform specification")
    from ...fast_distance_spec import prepare_fast_distance_spec

    try:
        spec = prepare_fast_distance_spec(
            metric=metric, neighborhood=neighborhood,
        )
    except (TypeError, ValueError, OverflowError) as error:
        fail(f"Image.fastDistanceTransform specification is invalid: {error}")
    return arguments["image"], neighborhood, metric, spec


def invoke_image_fast_distance(translator, arguments):
    """Lower the local fast-distance policy independently for each band."""
    image, _neighborhood_value, _metric_value, spec = _parameters(
        translator, arguments,
    )
    if type(image) is not Image or type(image.bands) is not list or not image.bands:
        fail("Image.fastDistanceTransform requires a nonempty scalar Image")
    if len(image.bands) > _MAX_BANDS:
        fail("Image.fastDistanceTransform input exceeds 10000 bands")

    names = []
    pixels = []
    for band in image.bands:
        if type(band) is not tuple or len(band) != 2:
            fail("Image.fastDistanceTransform input contains an invalid scalar band descriptor")
        name, pixel = band
        if (type(name) is not str or not name or len(name) > _MAX_NAME_CHARS
                or type(pixel) is not Pixel):
            fail("Image.fastDistanceTransform requires named scalar image bands")
        _charge(translator, 1 + len(name), "Image.fastDistanceTransform band scan")
        names.append(name)
        pixels.append(pixel)
    _charge(
        translator, len(names) + sum(map(len, names)),
        "Image.fastDistanceTransform band validation",
    )
    if len(set(names)) != len(names):
        fail("Image.fastDistanceTransform requires unique input band names")

    _charge(translator, len(names), "Image.fastDistanceTransform output planning")
    return replace(
        image,
        bands=[(name, Pixel("fast_distance", (pixel, spec)))
               for name, pixel in zip(names, pixels)],
    )
