"""Compile bounded Earth Engine Image.convolve calls to local pixel IR."""
from __future__ import annotations

from dataclasses import replace

from .ir import Image, Pixel, fail


CONVOLVE_FUNCTIONS = frozenset({"Image.convolve"})
_MAX_KERNEL_CELLS = 1_089
_MAX_OFFSET = 32
_MAX_WORK = 50_000


def _charge(translator, amount: int, label: str) -> None:
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or type(amount) is not int or amount < 0
            or steps + amount > _MAX_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _kernel_coefficients(translator, value):
    from .kernel_values import KernelSpec, validate_kernel

    if type(value) is not KernelSpec:
        fail("Image.convolve requires a bounded fixed pixel Kernel")
    kernel = validate_kernel(translator, value)
    cells = kernel.width * kernel.height
    _charge(translator, 2 + cells, "Convolution kernel scan")
    coefficients = []
    for row, weights in enumerate(kernel.weights):
        for column, weight in enumerate(weights):
            dx = column - kernel.x
            dy = row - kernel.y
            if abs(dx) > _MAX_OFFSET or abs(dy) > _MAX_OFFSET:
                fail("Convolution kernel offsets must be within 32 pixels")
            if weight != 0.0:
                coefficients.append((dx, dy, weight))
    if not coefficients:
        # Keep a zero kernel as an explicit operation. The native process emits
        # zero on valid centers and NoData on masked centers; no neighbors are needed.
        coefficients = [(0, 0, 0.0)]
    if len(coefficients) > _MAX_KERNEL_CELLS:
        fail("Convolution kernel must contain at most 1089 coefficients")
    return coefficients


def _make_spec(translator, coefficients):
    from ...convolve_spec import prepare_convolve_spec

    # Precharge the bounded wire estimate before the shared encoder allocates
    # its coefficient copy and JSON text. The actual byte limit is rechecked by
    # the canonical encoder.
    wire_work = 32 + sum(len(str(dx)) + len(str(dy)) + 23
                         for dx, dy, _ in coefficients)
    _charge(translator, wire_work, "Convolution specification encoding")
    try:
        return prepare_convolve_spec(coefficients)
    except ValueError as error:
        fail(f"Image.convolve has an invalid kernel specification: {error}")


def invoke_image_convolve(translator, arguments):
    translator.allowed(arguments, {"image", "kernel"})
    for required in ("image", "kernel"):
        if required not in arguments:
            fail(f"Image.convolve requires {required}")
    image = arguments["image"]
    if type(image) is not Image or not image.bands:
        fail("Image.convolve requires a nonempty scalar Image")
    for name, pixel in image.bands:
        if type(name) is not str or not name or type(pixel) is not Pixel:
            fail("Image.convolve requires named scalar pixel bands")
    coefficients = _kernel_coefficients(translator, arguments["kernel"])
    spec = _make_spec(translator, coefficients)
    return replace(
        image,
        bands=[(name, Pixel("convolve", (pixel, spec)))
               for name, pixel in image.bands],
    )
