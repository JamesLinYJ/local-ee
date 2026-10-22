"""Stable keyed permutations of fixed Float32 raster-array pixels."""
from __future__ import annotations

import math

from .array_core import charge_array
from .ir import Pixel, fail
from .raster_array_core import combined_mask, wrap_array_image
from .raster_array_values import _array, _result_image


RASTER_ARRAY_SORT_FUNCTIONS = frozenset({"Image.arraySort"})


def _sort_axis(shape, key_shape):
    if len(shape) != len(key_shape) or not 1 <= len(shape) <= 8:
        fail("Image.arraySort requires matching rank-1..8 value and key arrays")
    axes = [axis for axis, length in enumerate(key_shape) if length != 1]
    if not axes and math.prod(shape) == 1:
        return 0
    if len(axes) != 1:
        fail("Image.arraySort keys must identify exactly one non-singleton axis")
    axis = axes[0]
    if key_shape[axis] != shape[axis]:
        fail("Image.arraySort key length must match the selected value axis")
    return axis


def _float_cells(value):
    if any(pixel.op != "to_float" or len(pixel.args) != 1
           or not isinstance(pixel.args[0], Pixel) or pixel.boolean
           for pixel in value.cells):
        fail("Image.arraySort requires explicit top-level toFloat() for every value and key cell")


def _swap(condition, left, right):
    # Selection performs no arithmetic on payload values. An explicit cast
    # preserves the existing array callback dtype for downstream operations.
    return (
        Pixel("to_float", (Pixel("if", (condition, right, left)),)),
        Pixel("to_float", (Pixel("if", (condition, left, right)),)),
    )


def invoke_raster_sort(translator, name, arguments):
    """Sort one fixed axis, moving full slices under the same key permutation.

    Adjacent compare-exchange uses strict greater-than, retaining the original
    order of equal Float32 keys. This is an explicit local tie policy, without
    a Google comparison. All key and payload validity contributes to the mask.
    """
    if name not in RASTER_ARRAY_SORT_FUNCTIONS:
        fail(f"Unsupported raster array sort operation: {name}")
    if not isinstance(arguments, dict):
        fail("Image.arraySort arguments must be a dictionary")
    translator.allowed(arguments, {"image", "keys"})
    if "image" not in arguments:
        fail("Image.arraySort requires image")
    value = _array(arguments["image"], "Image.arraySort image")
    keys = value if arguments.get("keys") is None else _array(
        arguments["keys"], "Image.arraySort keys",
    )
    axis = _sort_axis(value.shape, keys.shape)
    length = value.shape[axis]
    outer, inner = math.prod(value.shape[:axis]), math.prod(value.shape[axis + 1:])
    slices = outer * inner
    exchanges = length * (length - 1) // 2
    # Charge key scans, detached output slots and every comparison, selection
    # and cast before building the potentially quadratic Pixel DAG. The graph
    # compiler's separate 500-node cap remains authoritative.
    metadata_work = len(value.image.bands) + len(value.image.props) + len(value.name)
    charge_array(translator, len(value.cells) + len(keys.cells) + 2 * len(value.shape)
                 + exchanges * (5 + 4 * slices) + metadata_work + 1)
    _float_cells(value)
    _float_cells(keys)
    cells, ordered_keys = list(value.cells), list(keys.cells)
    for end in range(length - 1, 0, -1):
        for position in range(end):
            left_key, right_key = ordered_keys[position:position + 2]
            condition = Pixel("gt", (left_key, right_key), True)
            ordered_keys[position:position + 2] = _swap(condition, left_key, right_key)
            for block in range(outer):
                for offset in range(inner):
                    left = (block * length + position) * inner + offset
                    right = left + inner
                    cells[left], cells[right] = _swap(condition, cells[left], cells[right])

    return wrap_array_image(
        _result_image(value, keys), value.shape, tuple(cells),
        combined_mask(value.mask, keys.mask), value.name,
    )
