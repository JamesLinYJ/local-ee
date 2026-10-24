"""Mask adapters for Earth Engine image operations.

Image.unmask keeps pixel validity and image footprint as separate properties.
The returned Pixel operations are IR contracts; raster materialization is owned
by the graph/native backend and must use a real finite-grid constant process.
"""
from __future__ import annotations

from dataclasses import replace
import math
from typing import Any


SUPPORTED_MASK_FUNCTIONS = frozenset({"Image.unmask"})

_WORLD = {
    "type": "Polygon",
    "coordinates": [[[-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]]],
}
_MAX_EXACT_FLOAT64_INT = 2**53


def _footprint(translator: Any, image: Any) -> dict:
    """Return the image's logical finite footprint, or the EE global footprint."""
    if image.footprint is not None and image.footprint_is_absolute:
        return image.footprint
    if image.source is None:
        return image.footprint if image.footprint is not None else _WORLD
    return translator.footprint(image)


def _is_global_constant(image: Any) -> bool:
    return image.source is None and image.footprint is None


def _finite_region(translator: Any):
    region = getattr(translator, "options", {}).get("region")
    if not isinstance(region, dict):
        return None
    try:
        from shapely.geometry import shape
        geometry = shape(region)
        bounds = geometry.bounds
        finite = not geometry.is_empty and len(bounds) == 4 and all(
            isinstance(value, (int, float)) and math.isfinite(value) for value in bounds
        )
        return region if finite else None
    except Exception:
        return None


def _union(left: dict, right: dict) -> dict:
    try:
        from shapely.geometry import mapping, shape
        return mapping(shape(left).union(shape(right)))
    except Exception as exc:
        from .compat.earthengine.ir import fail
        fail(f"Image.unmask cannot form a local footprint union: {exc}")


def _intersection(left: dict, right: dict) -> dict:
    try:
        from shapely.geometry import mapping, shape
        return mapping(shape(left).intersection(shape(right)))
    except Exception as exc:
        from .compat.earthengine.ir import fail
        fail(f"Image.unmask cannot form the finite output footprint: {exc}")


def _constant_value(pixel: Any):
    if getattr(pixel, "op", None) != "constant" or len(pixel.args) != 1:
        return None, False
    value = pixel.args[0]
    if isinstance(value, bool):
        value = int(value)
    if not isinstance(value, (int, float)):
        return None, False
    return value, True


def _validate_float64_literals(value: Any, Pixel: Any, fail: Any, seen=None) -> None:
    """Reject replacement literals that would change when materialized as Float64."""
    seen = set() if seen is None else seen
    if isinstance(value, (Pixel, list, tuple)) or hasattr(value, "bands"):
        if id(value) in seen: return
        seen.add(id(value))
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > _MAX_EXACT_FLOAT64_INT:
            fail("Image.unmask value integer exceeds exact Float64 precision")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            fail("Image.unmask value must be finite")
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_float64_literals(item, Pixel, fail, seen)
        return
    if isinstance(value, Pixel):
        if value.op == "constant" and len(value.args) == 1:
            _validate_float64_literals(value.args[0], Pixel, fail, seen)
        else:
            for item in value.args:
                _validate_float64_literals(item, Pixel, fail, seen)
        return
    for _, pixel in getattr(value, "bands", ()):
        _validate_float64_literals(pixel, Pixel, fail, seen)


def invoke_mask(translator: Any, name: str, args: dict[str, Any]):
    """Adapt one supported mask invocation into the EE image IR.

    ``Pixel('unmask_constant', (input_pixel, value))`` asks the graph compiler
    to materialize a valid constant tile on the input's finite grid. It must
    not be lowered to ``input_pixel * 0`` because that retains input NoData.
    ``Pixel('unmask', (input_pixel, replacement_pixel, same_footprint))``
    represents a raster replacement including its mask and footprint policy.
    """
    from .compat.earthengine.ir import Pixel, as_image, fail

    if name not in SUPPORTED_MASK_FUNCTIONS:
        fail(f"Unsupported Earth Engine mask algorithm: {name}")
    if not isinstance(args, dict):
        fail("Image.unmask arguments must be an object")
    translator.allowed(args, {"input", "value", "sameFootprint"})
    if "input" not in args:
        fail("Image.unmask requires input")

    image = as_image(args["input"])
    if not image.bands:
        fail("Image.unmask input must have at least one band")
    if image.source is None:
        fail("Image.unmask needs an input backed by a local raster grid")
    same_footprint = args.get("sameFootprint", True)
    if same_footprint is None:
        same_footprint = True
    if not isinstance(same_footprint, bool):
        fail("Image.unmask sameFootprint must be a boolean")

    raw_value = 0 if args.get("value") is None else args["value"]
    _validate_float64_literals(raw_value, Pixel, fail)
    replacement = as_image(raw_value)
    if not replacement.bands:
        fail("Image.unmask value must have at least one band")
    if replacement.source is None and replacement.footprint is not None:
        fail("Image.unmask cannot materialize an unbound replacement with a finite footprint")
    if len(replacement.bands) not in {1, len(image.bands)}:
        fail("Image.unmask value needs one broadcast band or the same band count as the input")

    input_footprint = _footprint(translator, image)
    value_footprint = _footprint(translator, replacement)
    values = [replacement.bands[0][1]] * len(image.bands) if len(replacement.bands) == 1 else [
        pixel for _, pixel in replacement.bands
    ]
    global_extent = _is_global_constant(image) or _is_global_constant(replacement)
    if not same_footprint and global_extent:
        fail("Image.unmask sameFootprint=false with a global footprint is not supported")
    logical_footprint = input_footprint
    if not same_footprint:
        logical_footprint = _union(input_footprint, value_footprint)
    finite_region = _finite_region(translator)
    output_footprint = logical_footprint
    if finite_region is not None:
        output_footprint = _intersection(output_footprint, finite_region)

    output_bands = []
    for (band_name, input_pixel), replacement_pixel in zip(image.bands, values):
        # Apply source footprints as pixel masks before selecting a replacement,
        # then clip the result to the output footprint. This prevents unmask
        # from reviving pixels outside an image's own geometry.
        input_pixel = Pixel("clip", (input_pixel, input_footprint))
        if replacement.source is not None or replacement.footprint is not None:
            replacement_pixel = Pixel("clip", (replacement_pixel, value_footprint))
        constant, is_constant = _constant_value(replacement_pixel)
        pixel = Pixel("unmask_constant", (input_pixel, constant)) if is_constant else Pixel(
            "unmask", (input_pixel, replacement_pixel, same_footprint)
        )
        output_bands.append((band_name, Pixel("clip", (pixel, output_footprint))))

    changes = {"bands": output_bands}
    if not same_footprint:
        from .compat.earthengine.array_core import charge_array
        from .compat.earthengine.ir import combine_clip_footprints

        charge_array(translator, 3)
        changes.update(
            footprint=logical_footprint,
            footprint_is_absolute=True,
            clip_footprint=combine_clip_footprints(
                image.clip_footprint, replacement.clip_footprint,
            ),
        )
    return replace(image, **changes)


__all__ = ["SUPPORTED_MASK_FUNCTIONS", "invoke_mask"]
