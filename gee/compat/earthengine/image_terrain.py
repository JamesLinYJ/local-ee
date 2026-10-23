"""Compile the bounded Earth Engine Terrain image family to pixel IR."""
from __future__ import annotations

import math
from dataclasses import replace

from .ir import Image, Pixel, fail


TERRAIN_FUNCTIONS = frozenset({
    "Terrain", "Terrain.products", "Terrain.slope", "Terrain.aspect",
    "Terrain.hillshade",
})
_MAX_BANDS = 10_000
_MAX_NAME_CHARS = 10_000
_MAX_WORK = 50_000
_PRODUCTS = ("slope", "aspect", "hillshade")


def _charge(translator, amount: int, label: str) -> None:
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or type(amount) is not int or amount < 0
            or steps + amount > _MAX_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _image_bands(translator, image):
    if type(image) is not Image or type(image.bands) is not list or not image.bands:
        fail("Terrain requires a nonempty scalar Image")
    if len(image.bands) > _MAX_BANDS:
        fail("Terrain input exceeds 10000 bands")
    names = []
    pixels = []
    name_chars = 0
    for band in image.bands:
        if type(band) is not tuple or len(band) != 2:
            fail("Terrain input contains an invalid scalar band descriptor")
        name, pixel = band
        if (type(name) is not str or not name or len(name) > _MAX_NAME_CHARS
                or type(pixel) is not Pixel):
            fail("Terrain requires named scalar image bands")
        _charge(translator, 1 + len(name), "Terrain input band scan")
        names.append(name)
        pixels.append(pixel)
        name_chars += len(name)
    _charge(translator, len(names) + name_chars, "Terrain input band validation")
    if len(set(names)) != len(names):
        fail("Terrain requires unique input band names")
    return tuple(names), tuple(pixels)


def _static_angle(translator, value, default, label):
    if value is None:
        return default
    if type(value) not in (int, float):
        fail(f"Terrain.hillshade {label} must be a finite static number")
    if type(value) is int and abs(value) > 2**53:
        fail(f"Terrain.hillshade {label} integer exceeds the exact Float64 domain")
    try:
        number = float(value)
    except OverflowError:
        fail(f"Terrain.hillshade {label} must be a finite static number")
    if not math.isfinite(number):
        fail(f"Terrain.hillshade {label} must be a finite static number")
    return value if type(value) is int else number


def _spec(translator, operation, azimuth, elevation):
    from ...terrain_spec import prepare_terrain_spec

    # The canonical encoder has a small fixed-size wire form. Charge the bound
    # before asking it to allocate and serialize the specification.
    _charge(translator, 160, "Terrain specification encoding")
    try:
        return prepare_terrain_spec(
            operation, azimuth=azimuth, elevation=elevation,
        )
    except (TypeError, ValueError, OverflowError) as error:
        fail(f"Terrain has an invalid {operation} specification: {error}")


def invoke_terrain(translator, name, arguments):
    """Lower products, individual derivatives, and the legacy Terrain alias."""
    if name not in TERRAIN_FUNCTIONS:
        fail(f"Unsupported Terrain algorithm: {name}")
    if name == "Terrain.hillshade":
        translator.allowed(arguments, {"input", "azimuth", "elevation"})
    else:
        translator.allowed(arguments, {"input"})
    if "input" not in arguments:
        fail(f"{name} requires input")

    if name == "Terrain":
        translator.warn("Terrain is a deprecated alias; use Terrain.products.")
        requested = "products"
    else:
        requested = name.removeprefix("Terrain.")

    image = arguments["input"]
    names, pixels = _image_bands(translator, image)
    if len(names) == 1:
        elevation_pixel = pixels[0]
    else:
        try:
            elevation_pixel = pixels[names.index("elevation")]
        except ValueError:
            fail("Terrain requires one input band or a band named 'elevation'")

    azimuth = 270.0
    elevation = 45.0
    if requested == "hillshade":
        azimuth = _static_angle(translator, arguments.get("azimuth"), 270.0, "azimuth")
        elevation = _static_angle(translator, arguments.get("elevation"), 45.0, "elevation")

    operations = _PRODUCTS if requested == "products" else (requested,)
    if requested not in {"products", *_PRODUCTS}:
        fail(f"Unsupported Terrain operation: {requested}")
    if requested == "products":
        collisions = set(names).intersection(_PRODUCTS)
        if collisions:
            fail("Terrain.products output band names collide with input bands: "
                 + ", ".join(sorted(collisions)))
        if len(names) + len(operations) > _MAX_BANDS:
            fail("Terrain.products output exceeds 10000 bands")

    _charge(translator, len(operations), "Terrain output plan")
    outputs = [
        (operation, Pixel(
            "terrain", (elevation_pixel, _spec(translator, operation, azimuth, elevation)),
        ))
        for operation in operations
    ]
    bands = list(image.bands) + outputs if requested == "products" else outputs
    return replace(image, bands=bands)
