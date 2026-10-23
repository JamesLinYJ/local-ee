"""Bounded Earth Engine focal and neighborhood image operations."""
from __future__ import annotations

import math
from dataclasses import replace

from .ir import Image, Pixel, fail


_FOCAL_METHODS = {
    "focalMin": "min",
    "focalMax": "max",
    "focalMean": "mean",
    "focalMedian": "median",
    "focalMode": "mode",
}
_FOCAL_SNAKE_METHODS = {
    f"focal_{method[5:].lower()}": operation
    for method, operation in _FOCAL_METHODS.items()
}
FOCAL_FUNCTIONS = frozenset(
    {f"Image.{method}" for method in _FOCAL_METHODS}
    | {f"Image.{method}" for method in _FOCAL_SNAKE_METHODS}
    | {"Image.reduceNeighborhood"}
)
_SHAPES = frozenset({"circle", "square", "cross", "plus", "octagon", "diamond"})
_REDUCERS = frozenset({"mean", "min", "max", "median", "mode"})
_MAX_OFFSETS = 1089
_MAX_OFFSET = 32
_MAX_WORK = 50_000


def _charge(translator, amount: int, label: str) -> None:
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or type(amount) is not int or amount < 0
            or steps + amount > _MAX_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _radius(value) -> float:
    if (isinstance(value, bool) or type(value) not in (int, float)
            or not math.isfinite(value) or value < 0 or value > 16):
        fail("Named focal radius must be finite, nonnegative and at most 16 pixels")
    return float(value)


def _named_offsets(translator, shape, radius):
    if type(shape) is not str or shape not in _SHAPES:
        fail("Focal kernelType must be circle, square, cross, plus, octagon or diamond")
    radius = _radius(radius)
    from .kernel_values import invoke_kernel

    # Keep focal named masks identical to their fixed-Kernel constructor
    # counterpart, including cross/plus and fractional octagon boundaries.
    kernel = invoke_kernel(translator, f"Kernel.{shape}", {
        "radius": radius, "units": "pixels", "normalize": False,
    })
    return _custom_offsets(translator, kernel, "support")


def _custom_offsets(translator, kernel, input_weight):
    from .kernel_values import KernelSpec, validate_kernel

    if type(kernel) is not KernelSpec:
        fail("Focal operations require a validated fixed pixel Kernel")
    kernel = validate_kernel(translator, kernel)
    weights = kernel.weights
    cells = sum(len(row) for row in weights)
    _charge(translator, 2 + cells, "Focal kernel scan")
    positive = []
    offsets = []
    for row_index, row in enumerate(weights):
        for column_index, weight in enumerate(row):
            if weight < 0:
                fail("Focal kernel weights must be nonnegative")
            if weight == 0:
                continue
            dy, dx = row_index - kernel.y, column_index - kernel.x
            if abs(dx) > _MAX_OFFSET or abs(dy) > _MAX_OFFSET:
                fail("Focal kernel offsets must be within 32 pixels")
            positive.append(weight)
            offsets.append((dx, dy))
    if not offsets or len(offsets) > _MAX_OFFSETS:
        fail("Focal kernel must contain 1 to 1089 supported pixels")
    if input_weight in {"kernel", "min"} and any(
            value != positive[0] for value in positive[1:]):
        fail("Nonuniform kernel weights require reduceNeighborhood inputWeight='mask'")
    return tuple(sorted(offsets, key=lambda offset: (offset[1], offset[0])))


def _iterations(value):
    if (isinstance(value, bool) or type(value) not in (int, float)
            or not math.isfinite(value) or int(value) != value
            or not 1 <= value <= 8):
        fail("Focal iterations must be an integer from 1 to 8")
    return int(value)


def _make_spec(translator, operation, offsets, iterations=1, skip_masked=True):
    from ...focal_spec import prepare_focal_spec

    # The caller already bounded the offset list. Reserve conservative JSON
    # work and wire bytes before the shared encoder allocates its copy.
    _charge(translator, 128 + 12 * len(offsets) + iterations,
            "Focal specification encoding")
    return prepare_focal_spec(
        operation, offsets, iterations=iterations, skip_masked=skip_masked,
    )


def _focal(translator, name, arguments):
    method = name.split(".", 1)[1]
    operation = _FOCAL_METHODS.get(method, _FOCAL_SNAKE_METHODS.get(method))
    if operation not in _REDUCERS:
        fail(f"Unsupported focal operation: {name}")
    translator.allowed(arguments, {"image", "radius", "kernelType", "units", "iterations", "kernel"})
    if "image" not in arguments:
        fail(f"{name} requires an image")
    units = arguments.get("units", "pixels")
    if units != "pixels":
        fail("Focal kernels support pixel units only; meter kernels are unsupported")
    iterations = _iterations(arguments.get("iterations", 1))
    kernel = arguments.get("kernel")
    if kernel is not None:
        # Earth Engine documents radius and kernelType as ignored with a custom
        # Kernel. The fixed-kernel validator also rejects meter-sized kernels.
        # Focal methods consume the positive support of the kernel. The
        # weights themselves do not participate in the local reducer.
        offsets = _custom_offsets(translator, kernel, "support")
    else:
        offsets = _named_offsets(
            translator, arguments.get("kernelType", "circle"),
            arguments.get("radius", 1.5),
        )
    spec = _make_spec(translator, operation, offsets, iterations, True)
    image = arguments["image"]
    if not isinstance(image, Image) or not image.bands:
        fail("Focal operations require a nonempty Image")
    return replace(
        image, bands=[(band, Pixel("focal", (pixel, spec)))
                      for band, pixel in image.bands],
    )


def _reduce_neighborhood(translator, arguments):
    from .image_neighborhood import invoke_image_neighborhood

    return invoke_image_neighborhood(translator, arguments)


def invoke_image_focal(translator, name, arguments):
    if name == "Image.reduceNeighborhood":
        return _reduce_neighborhood(translator, arguments)
    if name in FOCAL_FUNCTIONS:
        return _focal(translator, name, arguments)
    fail(f"Unsupported Earth Engine focal algorithm: {name}")
