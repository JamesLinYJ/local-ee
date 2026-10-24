"""Shared bounded scalar helpers for local Image color and curve formulas."""
from __future__ import annotations

from dataclasses import replace

from .image_integer import _float64_pixel, _literal_value, _pixel
from .ir import Image, Pixel, const, fail


MAX_TRANSLATOR_WORK = 50_000
MAX_IMAGE_BANDS = 10_000
MAX_BAND_NAME_CHARS = 10_000
MAX_SCALAR_INTERNED = 1_024
MAX_COLOR_DOMAIN_PROOFS = 64


def reserve_work(translator, amount: int, name: str) -> None:
    steps = getattr(translator, "steps", None)
    if type(steps) is not int or steps < 0 or amount < 0 or steps + amount > MAX_TRANSLATOR_WORK:
        fail(f"{name} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def preflight_work(translator, amount: int, name: str) -> None:
    steps = getattr(translator, "steps", None)
    if type(steps) is not int or steps < 0 or amount < 0 or steps + amount > MAX_TRANSLATOR_WORK:
        fail(f"{name} exceeds the shared 50000-step compilation work budget")


def require_image(translator, name: str, arguments: dict, required: set[str],
                  optional: set[str], *, min_bands: int = 1,
                  max_bands: int = MAX_IMAGE_BANDS) -> Image:
    if type(arguments) is not dict:
        fail(f"{name} requires an argument object")
    translator.allowed(arguments, required | optional)
    missing = sorted(required - arguments.keys())
    if missing:
        fail(f"{name} requires {', '.join(missing)}")
    image = arguments.get("image")
    if not isinstance(image, Image) or type(image.bands) is not list:
        fail(f"{name} requires a named scalar Image")
    count = len(image.bands)
    if not min_bands <= count <= max_bands:
        if min_bands == max_bands:
            fail(f"{name} requires exactly {min_bands} input bands")
        fail(f"{name} requires between {min_bands} and {max_bands} input bands")
    if type(image.props) is not dict:
        fail(f"{name} requires finite Image metadata")
    # Reserve the input band/metadata walk and output band-list copy first.
    reserve_work(translator, 2 * count + len(image.props) + 1, name)
    for item in image.bands:
        if (type(item) is not tuple or len(item) != 2
                or type(item[0]) is not str or not item[0]
                or len(item[0]) > MAX_BAND_NAME_CHARS
                or not isinstance(item[1], Pixel)):
            fail(f"{name} requires named scalar Image bands")
    return image


def finite_number(value, label: str) -> float:
    import math

    if type(value) not in (int, float) or type(value) is bool:
        fail(f"{label} must contain finite non-boolean numbers")
    if type(value) is int and abs(value) > 2**53:
        fail(f"{label} integers must be within +/-2^53")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        fail(f"{label} must contain finite numbers")
    return float(value)


def finite_number_list(translator, value, label: str, *, minimum: int,
                       maximum: int) -> tuple[float, ...]:
    if type(value) is not list or not minimum <= len(value) <= maximum:
        fail(f"{label} must be a literal list with {minimum} to {maximum} values")
    reserve_work(translator, 2 * len(value) + 1, label)
    return tuple(finite_number(item, label) for item in value)


def scalar(value) -> Pixel:
    return value if isinstance(value, Pixel) else const(value)


def _interned(translator, operation: str, operands: tuple[Pixel, ...], *, boolean: bool,
              predicate_operation: bool) -> Pixel:
    """Intern repeated scalar nodes within one translator's bounded IR build.

    The Float64 wire is closed and immutable. Reusing identical child objects
    avoids expanding the same RGB/HSV subexpression once for every output
    channel during the later lineage and work-budget scans.
    """
    reserve_work(translator, 1 + len(operands), "Image scalar expression cache")
    descriptors = []
    dynamic = []
    for operand in operands:
        literal, value = _literal_value(operand, allow_boolean=True)
        if literal:
            if type(value) is float:
                encoded = ("float", value.hex())
            elif type(value) is int:
                encoded = ("int", value)
            elif type(value) is bool:
                encoded = ("bool", value)
            else:
                fail("Image scalar expression has an invalid literal")
            descriptors.append(("constant", encoded))
        else:
            descriptors.append(("pixel", id(operand)))
            dynamic.append(operand)
    key = (operation, boolean, predicate_operation, tuple(descriptors))
    cache = getattr(translator, "_image_color_scalar_cache", None)
    if cache is None:
        cache = {}
        setattr(translator, "_image_color_scalar_cache", cache)
    elif type(cache) is not dict:
        fail("Image scalar expression cache is invalid")
    entry = cache.get(key)
    if entry is not None:
        prior_dynamic, prior_pixel = entry
        if (len(prior_dynamic) == len(dynamic)
                and all(left is right for left, right in zip(prior_dynamic, dynamic))):
            return prior_pixel
    pixel = (
        _pixel(
            translator, "Image scalar " + operation, operation, operands,
            known_boolean_literals=True,
        )
        if predicate_operation else
        _float64_pixel(translator, "Image scalar " + operation, operation, operands)
    )
    if len(cache) < MAX_SCALAR_INTERNED:
        cache[key] = (tuple(dynamic), pixel)
    return pixel


def number(translator, operation: str, *operands: Pixel) -> Pixel:
    return _interned(
        translator, operation, tuple(scalar(value) for value in operands),
        boolean=False, predicate_operation=False,
    )


def predicate(translator, operation: str, left: Pixel, right: Pixel) -> Pixel:
    return _interned(
        translator, operation, (scalar(left), scalar(right)),
        boolean=True, predicate_operation=True,
    )


def choose(translator, condition: Pixel, accept: Pixel, reject: Pixel) -> Pixel:
    return number(translator, "select", condition, accept, reject)


def logical(translator, operation: str, left: Pixel, right: Pixel) -> Pixel:
    return number(translator, operation, left, right)


def mask_invalid(condition: Pixel, value: Pixel) -> Pixel:
    """Return value only where condition is true, preserving NoData masks."""
    return Pixel("if", (condition, value, Pixel("constant", (None,))))


def replace_bands(image: Image, bands: list[tuple[str, Pixel]]) -> Image:
    """Keep the image's lineage, projection-facing metadata, and properties."""
    return replace(image, bands=bands, props=dict(image.props))


def remember_rgb_to_hsv_domain(translator, outputs, condition: Pixel) -> None:
    """Keep a bounded proof for this exact ordered HSV output tuple only."""
    reserve_work(translator, 1 + len(outputs), "Image color domain proof")
    records = getattr(translator, "_image_color_domain_proofs", None)
    if records is None:
        records = []
        setattr(translator, "_image_color_domain_proofs", records)
    elif type(records) is not list:
        fail("Image color domain proof cache is invalid")
    for previous, _previous_condition in records:
        if len(previous) == len(outputs) and all(
            left is right for left, right in zip(previous, outputs)
        ):
            return
    if len(records) < MAX_COLOR_DOMAIN_PROOFS:
        # The tuple strongly retains the exact Pixels; IDs are never used as
        # proof keys, so object ID reuse cannot bless a different expression.
        records.append((tuple(outputs), condition))


def lookup_rgb_to_hsv_domain(translator, inputs) -> Pixel | None:
    """Find a proof only for the exact ordered, unchanged HSV Pixels."""
    reserve_work(translator, 1 + len(inputs), "Image color domain proof")
    records = getattr(translator, "_image_color_domain_proofs", None)
    if records is None:
        return None
    if type(records) is not list or len(records) > MAX_COLOR_DOMAIN_PROOFS:
        fail("Image color domain proof cache is invalid")
    for outputs, condition in records:
        if len(outputs) == len(inputs) and all(
            output is input_pixel for output, input_pixel in zip(outputs, inputs)
        ):
            return condition
    return None
