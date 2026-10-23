"""Compile bounded Image.neighborhoodToBands calls to focal pixel nodes."""
from __future__ import annotations

from dataclasses import replace

from .ir import Image, Pixel, fail


NEIGHBORHOOD_BANDS_FUNCTIONS = frozenset({"Image.neighborhoodToBands"})
_MAX_KERNEL_CELLS = 1_089
_MAX_OFFSET = 32
_MAX_IMAGE_BANDS = 10_000
_MAX_WORK = 50_000
_MAX_JSON_BYTES = 1_000_000


def _charge(translator, amount: int, label: str) -> None:
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or type(amount) is not int or amount < 0
            or steps + amount > _MAX_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _json_string_size(value: str) -> int:
    """Return public_result's escaped JSON size without allocating a copy."""
    size = len(value) + 2
    for character in value:
        code = ord(character)
        if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
            size += 1
        elif code < 32 or code >= 127:
            size += 5 if code <= 0xFFFF else 11
    return size


def _json_name_size(base_json_size: int, dx: int, dy: int) -> int:
    # The generated suffix is ASCII and needs no JSON escaping.
    return base_json_size + 2 + len(str(dx)) + len(str(dy))


def _focal_spec_size(dx: int, dy: int) -> int:
    # Exact canonical bytes for prepare_focal_spec("mean", [(dx, dy)],
    # iterations=1, skip_masked=False); this is used before allocating it.
    return (
        len('{"iterations":1,"offsets":[[')
        + len(str(dx)) + 1 + len(str(dy))
        + len(']],"operation":"mean","skip_masked":false,"v":1}')
    )


def _image_bands(translator, image):
    if type(image) is not Image or type(image.bands) is not list or not image.bands:
        fail("Image.neighborhoodToBands requires a nonempty scalar Image")
    if len(image.bands) > _MAX_IMAGE_BANDS:
        fail("Image.neighborhoodToBands input exceeds 10000 bands")

    # Pay for the bounded row walk before inspecting names or entries.
    _charge(translator, 1 + len(image.bands), "Neighborhood-to-bands input scan")
    name_chars = 0
    for entry in image.bands:
        if type(entry) is not tuple or len(entry) != 2:
            fail("Image.neighborhoodToBands requires named scalar pixel bands")
        name, pixel = entry
        if type(name) is not str or not name or type(pixel) is not Pixel:
            fail("Image.neighborhoodToBands requires named scalar pixel bands")
        name_chars += len(name)
    _charge(
        translator, name_chars + len(image.bands),
        "Neighborhood-to-bands input names",
    )

    names = set()
    for entry in image.bands:
        name, _pixel = entry
        if name in names:
            fail("Image.neighborhoodToBands output band names would collide")
        names.add(name)
    return image.bands, name_chars


def _kernel_offsets(translator, value):
    from .kernel_values import KernelSpec, validate_kernel

    if type(value) is not KernelSpec:
        fail("Image.neighborhoodToBands requires a bounded fixed pixel Kernel")
    kernel = validate_kernel(translator, value)
    cells = kernel.width * kernel.height
    if cells > _MAX_KERNEL_CELLS:
        fail("Image.neighborhoodToBands kernel exceeds 1089 cells")
    _charge(translator, 2 + cells, "Neighborhood-to-bands kernel scan")

    offsets = []
    for row_index, row in enumerate(kernel.weights):
        for column_index, weight in enumerate(row):
            if weight == 0.0:
                continue
            dx = column_index - kernel.x
            dy = row_index - kernel.y
            if abs(dx) > _MAX_OFFSET or abs(dy) > _MAX_OFFSET:
                fail("Image.neighborhoodToBands offsets must be within 32 pixels")
            offsets.append((dx, dy))
    if not offsets:
        fail("Image.neighborhoodToBands kernel must have at least one nonzero cell")
    return tuple(offsets)


def invoke_image_neighborhood_bands(translator, arguments):
    """Expand each input band by every nonzero kernel cell, in row-major order."""
    translator.allowed(arguments, {"image", "kernel"})
    for required in ("image", "kernel"):
        if required not in arguments:
            fail(f"Image.neighborhoodToBands requires {required}")

    image = arguments["image"]
    bands, input_name_chars = _image_bands(translator, image)

    # Each output must ultimately read an actual finite raster source. Reject
    # source-free constants and malformed pixel trees before preparing specs.
    from .pixel_math_graph import _PixelFactsWalker

    walker = _PixelFactsWalker(translator)
    for _, pixel in bands:
        if not walker.inspect(pixel).sources:
            fail("Image.neighborhoodToBands requires finite bound raster sources")

    offsets = _kernel_offsets(translator, arguments["kernel"])
    output_count = len(bands) * len(offsets)
    _charge(translator, output_count, "Neighborhood-to-bands output count")

    # Charge the bounded character walk before measuring escaped names. Cache
    # one base-name size per input band so a large name is not rescanned once
    # for every support cell.
    _charge(
        translator, input_name_chars + len(bands),
        "Neighborhood-to-bands name JSON scan",
    )
    base_json_sizes = [_json_string_size(name) for name, _ in bands]

    # Estimate the final public graph/result size before building generated
    # names, focal specs, or Pixel nodes. Names occur in both the output band
    # list and each rename_labels target; each output also carries its focal
    # spec. The fixed allowance covers the process-graph structure around it.
    wire_bytes = 0
    name_work = 0
    spec_work = 0
    raw_name_work = 0
    for band_index, (name, _pixel) in enumerate(bands):
        base_json_size = base_json_sizes[band_index]
        for dx, dy in offsets:
            name_size = _json_name_size(base_json_size, dx, dy)
            spec_size = _focal_spec_size(dx, dy)
            wire_bytes += 2 * name_size + spec_size + 256
            name_work += 2 * name_size
            spec_work += spec_size
            raw_name_work += len(name) + 2 + len(str(dx)) + len(str(dy))
            if wire_bytes > _MAX_JSON_BYTES:
                fail("Image.neighborhoodToBands output exceeds 1 MB")
    _charge(
        translator,
        name_work + spec_work + raw_name_work + 3 * output_count,
        "Neighborhood-to-bands names, specifications and output allocation",
    )

    from ...focal_spec import prepare_focal_spec

    specs = {}
    for offset in offsets:
        try:
            specs[offset] = prepare_focal_spec(
                "mean", [offset], iterations=1, skip_masked=False,
            )
        except ValueError as error:
            fail(f"Image.neighborhoodToBands produced an invalid focal spec: {error}")

    output = []
    output_names = set()
    for name, pixel in bands:
        for offset in offsets:
            dx, dy = offset
            output_name = f"{name}_{dx}_{dy}"
            if output_name in output_names:
                fail("Image.neighborhoodToBands output band names would collide")
            output_names.add(output_name)
            output.append((output_name, Pixel("focal", (pixel, specs[offset]))))
    if len(output) != output_count:
        fail("Image.neighborhoodToBands output expansion was inconsistent")
    return replace(image, bands=output)
