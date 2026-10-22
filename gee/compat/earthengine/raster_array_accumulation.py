"""Prefix reductions for bounded Float32 raster-array images."""
from __future__ import annotations

import math

from .array_core import charge_array
from .ir import Pixel, Reducer, fail
from .raster_array_core import check_shape, wrap_array_image
from .raster_array_values import _array


RASTER_ARRAY_ACCUMULATION_FUNCTIONS = frozenset({"Image.arrayAccum"})
_OPERATIONS = {"sum": "add", "min": "min2", "max": "max2"}


def _arguments(translator, name, arguments):
    if not isinstance(arguments, dict):
        fail(f"{name} arguments must be a dictionary")
    translator.allowed(arguments, {"input", "axis", "reducer"})
    missing = {"input", "axis"} - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def _float32_cells(array, name):
    if any(pixel.op != "to_float" or len(pixel.args) != 1
           or not isinstance(pixel.args[0], Pixel) or pixel.boolean
           for pixel in array.cells):
        fail(f"{name} requires explicit top-level toFloat() for every array cell")


def _axis(value, rank, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"{name} axis must be an integer")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        fail(f"{name} axis must be an integer")
    axis = int(value)
    if not 0 <= axis < rank:
        fail(f"{name} axis must be within the input array rank")
    return axis


def invoke_raster_accumulation(translator, name, arguments):
    """Build a row-major prefix scan along one fixed array axis."""
    if name not in RASTER_ARRAY_ACCUMULATION_FUNCTIONS:
        fail(f"Unsupported raster array accumulation operation: {name}")
    _arguments(translator, name, arguments)

    array = _array(arguments["input"], f"{name} input")
    rank = len(array.shape)
    if not 1 <= rank <= 8:
        fail(f"{name} supports only rank-1..8 RasterArrayImages")
    count = check_shape(array.shape)
    axis = _axis(arguments["axis"], rank, name)

    reducer = arguments.get("reducer")
    operation = "add"
    if reducer is not None:
        if (not isinstance(reducer, Reducer) or reducer.name not in _OPERATIONS
                or reducer.unweighted):
            fail(f"{name} supports only SUM, MIN, or MAX reducers")
        operation = _OPERATIONS[reducer.name]

    axis_length = array.shape[axis]
    outer = math.prod(array.shape[:axis])
    inner = math.prod(array.shape[axis + 1:])
    operations = outer * inner * max(0, axis_length - 1)
    # Scan input types and indices, materialize one output slot per input cell,
    # and create an arithmetic Pixel plus Float32 cast per prefix update.
    charge_array(translator, 4 * count + 2 * operations + 2 * rank + 8)
    _float32_cells(array, name)

    cells = [None] * count
    for outer_index in range(outer):
        block_start = outer_index * axis_length * inner
        for inner_index in range(inner):
            offset = block_start + inner_index
            accumulated = array.cells[offset]
            cells[offset] = accumulated
            for position in range(1, axis_length):
                offset = block_start + position * inner + inner_index
                accumulated = Pixel(
                    "to_float",
                    (Pixel(operation, (accumulated, array.cells[offset])),),
                )
                cells[offset] = accumulated

    return wrap_array_image(
        array.image, array.shape, tuple(cells), array.mask, array.name,
    )
