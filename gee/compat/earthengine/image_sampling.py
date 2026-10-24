"""Image.sample IR construction using the shared bounded v2 sample spec."""
from __future__ import annotations

import math

from .geometry_values import decode_geometry
from .ir import ClipFootprintIdentity, Image, Pixel, SampledFeatures, fail


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


def _charge_clip_gate(translator, amount):
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or amount < 0
            or steps + amount > MAX_TRANSLATOR_WORK):
        fail("Image.sample clip-region validation exceeds the 50000-step compilation work budget")
    translator.steps = steps + amount


def _direct_clip_coverage_carrier(translator, image, expected_spec):
    """Prove zero support for this exact ROI through zero-preserving updates."""
    if (len(image.bands) != 1 or image.bands[0][1].op != "with_mask"
            or type(image.bands[0][1].args) is not tuple
            or len(image.bands[0][1].args) != 2
            or any(not isinstance(value, Pixel)
                   for value in image.bands[0][1].args)):
        return False
    if type(expected_spec) is not str or not expected_spec:
        return False
    weight = image.bands[0][1].args[1]
    seen, active = {}, set()

    def visit(value, depth):
        if not isinstance(value, (Pixel, tuple, list)):
            return 0, False
        identity = id(value)
        if depth > 96:
            fail("Image.sample clip mask graph exceeds depth96")
        if identity in active:
            fail("Image.sample clip mask graph has invalid depth or a cycle")
        cached = seen.get(identity)
        if cached is not None:
            _charge_clip_gate(translator, 1)
            if depth + cached[0] - 1 > 96:
                fail("Image.sample clip mask graph exceeds depth96")
            return cached
        proves_zero = False
        if isinstance(value, Pixel):
            if type(value.op) is not str or type(value.args) is not tuple:
                fail("Image.sample clip mask graph is malformed")
            _charge_clip_gate(translator, 1 + len(value.op) + len(value.args))
            children = value.args
            proves_zero = False
            if value.op == "clip_coverage":
                if len(value.args) != 2 or type(value.args[1]) is not str:
                    fail("Image.sample clip coverage specification is malformed")
                _charge_clip_gate(translator, len(value.args[1]))
                proves_zero = value.args[1] == expected_spec
        else:
            _charge_clip_gate(translator, 1 + len(value))
            children = value
        active.add(identity)
        child_results = [visit(child, depth + 1) for child in children]
        active.remove(identity)
        child_height = max((result[0] for result in child_results), default=0)
        height = 1 + child_height
        if depth + height - 1 > 96:
            fail("Image.sample clip mask graph exceeds depth96")
        # A nonzero update replaces an old weight, so either zero operand keeps
        # the result zero. Other operations, including mask_validity and
        # mask_set_value, are barriers even though their complete subgraphs are
        # still scanned for cycles, depth and shared request work.
        if isinstance(value, Pixel) and value.op == "mask_update" and len(children) == 2:
            proves_zero = child_results[0][1] or child_results[1][1]
        seen[identity] = (height, proves_zero)
        return seen[identity]

    return visit(weight, 1)[1]


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

    geometries = arguments.get("geometries", False)
    drop_nulls = arguments.get("dropNulls", True)
    if type(geometries) is not bool:
        fail("Image.sample geometries must be a boolean")
    if type(drop_nulls) is not bool:
        fail("Image.sample dropNulls must be a boolean")

    region = arguments.get("region")
    try:
        if region is None:
            if image.clip_footprint is not None:
                if (not drop_nulls
                        or not isinstance(image.clip_footprint, ClipFootprintIdentity)
                        or image.clip_footprint.spec is None
                        or not _direct_clip_coverage_carrier(
                            translator, image, image.clip_footprint.spec,
                        )):
                    fail(
                        "A pending geodesic clip needs an explicit Image.sample region unless "
                        "one direct band proves zero support for its exact clip ROI and "
                        "dropNulls=true"
                    )
            region = translator.footprint(image)
        region = decode_geometry(region)
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Image.sample requires a finite image footprint or supported region: {exc}")

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
