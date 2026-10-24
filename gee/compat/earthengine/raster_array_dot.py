"""One-dimensional dot products for bounded raster-array image bands."""
from __future__ import annotations

from dataclasses import replace

from .array_core import charge_array
from .ir import Pixel, const, fail
from .numeric_reducer_grid import require_common_grid
from .pixel_math_graph import _PixelFactsWalker
from .raster_array_bands import RasterArrayBands, _require_bundle
from .raster_array_core import (
    RasterArrayImage,
    check_shape,
    combined_mask,
)
from .raster_array_values import _array, _result_image


RASTER_ARRAY_DOT_FUNCTIONS = frozenset({"Image.arrayDotProduct"})
RASTER_ARRAY_DOT_ARGUMENTS = {
    "Image.arrayDotProduct": (frozenset({"image1", "image2"}), frozenset()),
}


def _bands(translator, value, label):
    if isinstance(value, RasterArrayImage):
        return (_array(value, label),)
    if isinstance(value, RasterArrayBands):
        bundle = _require_bundle(translator, value, label)
        return tuple(_array(array, f"{label} band") for array in bundle.arrays)
    fail(f"{label} must contain fixed-shape array bands")


def _pairs(left, right, name):
    if len(left) == 1 and len(right) > 1:
        return [(array.name, left[0], array) for array in right]
    if len(right) == 1:
        return [(array.name, array, right[0]) for array in left]
    if len(left) != len(right):
        fail(f"{name} requires equal band counts or a single broadcast array band")
    return [(a.name, a, b) for a, b in zip(left, right)]


def _source_facts(translator, array, walker, operands):
    identities = set()
    for pixel in array.cells:
        sources = walker.inspect(pixel).sources
        if sources:
            identities.update(sources)
            charge_array(translator, 1)
            operands.append(pixel)
    sources = walker.inspect(array.mask).sources
    if sources:
        identities.update(sources)
        charge_array(translator, 1)
        operands.append(array.mask)
    return frozenset(identities)


def _require_aligned_sources(translator, pairs, name):
    walker = _PixelFactsWalker(translator)
    operands = []
    output_lineage = None
    for _label, left, right in pairs:
        left_sources = _source_facts(translator, left, walker, operands)
        right_sources = _source_facts(translator, right, walker, operands)
        if left_sources and right_sources and left_sources != right_sources:
            fail(f"{name} requires matching source scene identities")
        pair_lineage = left_sources or right_sources
        if output_lineage is None:
            output_lineage = pair_lineage
        elif pair_lineage != output_lineage:
            fail(f"{name} requires matching source scene identities across output bands")

    if output_lineage:
        charge_array(translator, len(operands))
        require_common_grid(
            translator,
            operands,
            label=name,
            check_single_item_assets=True,
        )


def _dot(left, right):
    result = Pixel("multiply", (left.cells[0], right.cells[0]))
    for left_cell, right_cell in zip(left.cells[1:], right.cells[1:]):
        product = Pixel("multiply", (left_cell, right_cell))
        result = Pixel("add", (result, product))
    return result


def invoke_raster_array_dot(translator, name, arguments):
    """Compute paired rank-1 vector dots with shared validity and image metadata."""
    if name not in RASTER_ARRAY_DOT_FUNCTIONS:
        fail(f"Unsupported raster array dot operation: {name}")
    if not isinstance(arguments, dict):
        fail(f"{name} arguments must be a dictionary")
    required, optional = RASTER_ARRAY_DOT_ARGUMENTS[name]
    translator.allowed(arguments, required | optional)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")

    left = _bands(translator, arguments["image1"], f"{name} image1")
    right = _bands(translator, arguments["image2"], f"{name} image2")
    if not (len(left) == 1 or len(right) == 1 or len(left) == len(right)):
        fail(f"{name} requires equal band counts or a single broadcast array band")
    charge_array(translator, len(left) + len(right) + max(len(left), len(right)))
    pairs = _pairs(left, right, name)

    for _label, first, second in pairs:
        if len(first.shape) != 1 or len(second.shape) != 1:
            fail(f"{name} requires rank-1 array vectors")
        if first.shape != second.shape:
            fail(f"{name} requires paired vectors with equal lengths")
        check_shape(first.shape)

    output_bands = len(pairs)
    metadata_work = sum(
        len(array.image.bands) + len(array.image.props)
        + len(array.name) + 1
        for array in (*left, *right)
    )
    arithmetic_work = sum(
        2 * len(first.cells) + max(0, len(first.cells) - 1) + 2
        for _label, first, _second in pairs
    )
    charge_array(translator, metadata_work + output_bands + arithmetic_work)

    # Scene identity and source-grid checks happen before constructing any
    # cross-source arithmetic expression, so a mismatched source cannot be
    # implicitly reprojected by the downstream cube merge.
    _require_aligned_sources(translator, pairs, name)

    first_left, first_right = pairs[0][1], pairs[0][2]
    metadata = _result_image(first_left, first_right)
    output = []
    for band_name, first, second in pairs:
        mask = combined_mask(first.mask, second.mask)
        value = _dot(first, second)
        if not (mask.op == "constant" and mask.args == (True,)):
            value = Pixel("if", (mask, value, const(None)))
        output.append((band_name, value))
    return replace(metadata, bands=output)
