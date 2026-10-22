"""Image.sample IR construction using the shared bounded v2 sample spec."""
from __future__ import annotations

import math

from .geometry_values import decode_geometry
from .ir import Image, Pixel, SampledFeatures, fail


MAX_TRANSLATOR_WORK = 50_000
IMAGE_SAMPLE_WARNING = (
    "Image.sample uses a deterministic local grid hash for subsampling; "
    "Google RNG and selected-row parity are unverified."
)
_ARGUMENTS = {
    "image", "region", "scale", "projection", "factor", "numPixels",
    "seed", "dropNulls", "tileScale", "geometries",
}


def _charge(translator, work):
    if work < 0 or translator.steps + work > MAX_TRANSLATOR_WORK:
        fail("Image.sample exceeds the 50000-step compilation work budget")
    translator.steps += work


def _coordinate_count(value):
    if type(value) is list:
        if len(value) == 2 and all(type(item) in (int, float) for item in value):
            return 1
        return sum(_coordinate_count(item) for item in value)
    return 0


def _band_names(image):
    if not isinstance(image, Image):
        fail("Image.sample image must be an Earth Engine Image")
    if type(image.bands) is not list or not 1 <= len(image.bands) <= 64:
        fail("Image.sample requires 1..64 named input bands")
    names = []
    for item in image.bands:
        if (type(item) is not tuple or len(item) != 2
                or type(item[0]) is not str or not isinstance(item[1], Pixel)):
            fail("Image.sample requires named scalar pixel bands")
        names.append(item[0])
    if len(set(names)) != len(names):
        fail("Image.sample input band names must be unique")
    return names


def invoke_image_sample(translator, arguments):
    """Create an opaque sample table; pixels and random choices stay native."""
    from ...image_sampling_spec import prepare_image_sample_spec

    translator.allowed(arguments, _ARGUMENTS)
    if "image" not in arguments:
        fail("Image.sample requires image")
    image = arguments["image"]
    bands = _band_names(image)
    if image.mapped:
        fail("Image.sample requires a fixed spatial image outside a mapped callback")

    region = arguments.get("region")
    try:
        if region is None:
            region = translator.footprint(image)
        region = decode_geometry(region)
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Image.sample requires a finite image footprint or supported region: {exc}")

    geometries = arguments.get("geometries", False)
    drop_nulls = arguments.get("dropNulls", True)
    if type(geometries) is not bool:
        fail("Image.sample geometries must be a boolean")
    if type(drop_nulls) is not bool:
        fail("Image.sample dropNulls must be a boolean")

    tile_scale = arguments.get("tileScale", 1.0)
    try:
        valid_tile_scale = (
            not isinstance(tile_scale, bool)
            and type(tile_scale) in (int, float)
            and math.isfinite(tile_scale)
            and tile_scale == 1
        )
    except OverflowError:
        valid_tile_scale = False
    if not valid_tile_scale:
        fail("Image.sample only supports tileScale=1")

    grid = {"scale": arguments.get("scale"), "crs": arguments.get("projection")}
    if grid == {"scale": None, "crs": None}:
        grid = None
    _charge(translator, 1 + len(bands) + sum(map(len, bands))
            + _coordinate_count(region.get("coordinates", [])))
    try:
        spec = prepare_image_sample_spec(
            region,
            bands,
            grid=grid,
            factor=arguments.get("factor"),
            num_pixels=arguments.get("numPixels"),
            seed=arguments.get("seed", 0),
            drop_nulls=drop_nulls,
            geometries=geometries,
        )
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Invalid Image.sample parameters: {exc}")
    _charge(translator, len(spec) + len(bands) + 1)
    translator.warn(IMAGE_SAMPLE_WARNING)
    return SampledFeatures(image=image, spec=spec)
