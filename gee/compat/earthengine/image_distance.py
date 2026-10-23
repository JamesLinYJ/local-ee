"""Compile bounded Earth Engine Image.distance calls to pixel IR."""
from __future__ import annotations

from dataclasses import replace

from .ir import Image, Pixel, fail


DISTANCE_FUNCTIONS = frozenset({"Image.distance"})
_MAX_BANDS = 10_000
_MAX_NAME_CHARS = 10_000
_MAX_WORK = 50_000


def _charge(translator, amount: int, label: str) -> None:
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or type(amount) is not int or amount < 0
            or steps + amount > _MAX_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _distance_kernel(translator, value):
    from .kernel_values import KernelSpec, validate_kernel

    if type(value) is not KernelSpec:
        fail("Image.distance requires an explicit eligible distance Kernel")
    kernel = validate_kernel(translator, value)
    if kernel.distance_metric is None or kernel.distance_radius is None:
        fail(
            "Image.distance requires a raw Euclidean, Manhattan or Chebyshev "
            "Kernel with unnormalized unit-magnitude weights"
        )
    return kernel.distance_metric, kernel.distance_radius


def _spec(translator, metric, radius, skip_masked):
    from ...distance_spec import prepare_distance_spec

    # This canonical representation has a small fixed-size upper bound. Reserve
    # its encoding work before letting the shared encoder allocate JSON text.
    _charge(translator, 192, "Image.distance specification encoding")
    try:
        return prepare_distance_spec(metric, radius, skip_masked=skip_masked)
    except (TypeError, ValueError, OverflowError) as error:
        fail(f"Image.distance has an invalid distance specification: {error}")


def invoke_image_distance(translator, arguments):
    """Lower a true metric-distance kernel independently for each input band."""
    translator.allowed(arguments, {"image", "kernel", "skipMasked"})
    if "image" not in arguments:
        fail("Image.distance requires image")
    if "kernel" not in arguments or arguments["kernel"] is None:
        fail("Image.distance requires an explicit kernel; a missing or null default is ambiguous")

    skip_masked = arguments.get("skipMasked", True)
    if type(skip_masked) is not bool:
        fail("Image.distance skipMasked must be a boolean")

    metric, radius = _distance_kernel(translator, arguments["kernel"])
    image = arguments["image"]
    if type(image) is not Image or type(image.bands) is not list or not image.bands:
        fail("Image.distance requires a nonempty scalar Image")
    if len(image.bands) > _MAX_BANDS:
        fail("Image.distance input exceeds 10000 bands")

    names = []
    pixels = []
    name_chars = 0
    for band in image.bands:
        if type(band) is not tuple or len(band) != 2:
            fail("Image.distance input contains an invalid scalar band descriptor")
        name, pixel = band
        if (type(name) is not str or not name or len(name) > _MAX_NAME_CHARS
                or type(pixel) is not Pixel):
            fail("Image.distance requires named scalar image bands")
        _charge(translator, 1 + len(name), "Image.distance input band scan")
        names.append(name)
        pixels.append(pixel)
        name_chars += len(name)
    _charge(translator, len(names) + name_chars, "Image.distance input band validation")
    if len(set(names)) != len(names):
        fail("Image.distance requires unique input band names")

    spec = _spec(translator, metric, radius, skip_masked)
    _charge(translator, len(names), "Image.distance output planning")
    return replace(
        image,
        bands=[(name, Pixel("distance", (pixel, spec)))
               for name, pixel in zip(names, pixels)],
    )
