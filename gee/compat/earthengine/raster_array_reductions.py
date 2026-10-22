"""Lower fixed-shape, single-field array pixel reductions to scalar IR."""
from __future__ import annotations

import itertools
import math

from .array_core import charge_array
from .ir import Pixel, Reducer, fail, integer
from .raster_array_core import RasterArrayImage, check_shape, wrap_array_image


RASTER_ARRAY_REDUCTION_FUNCTIONS = frozenset({"Image.arrayReduce"})
_REDUCERS = frozenset({"sum", "mean", "min", "max", "count", "median", "sd"})


def invoke_raster_reduction(translator, name, arguments):
    if name not in RASTER_ARRAY_REDUCTION_FUNCTIONS:
        fail(f"Unsupported raster array reduction: {name}")
    translator.allowed(arguments, {"input", "reducer", "axes", "fieldAxis"})
    array, reducer, axes = (arguments.get(key) for key in ("input", "reducer", "axes"))
    if not isinstance(array, RasterArrayImage):
        fail("Image.arrayReduce requires a fixed-shape array image")
    if arguments.get("fieldAxis") is not None:
        fail("Image.arrayReduce fieldAxis is currently unsupported")
    if not isinstance(reducer, Reducer) or reducer.name not in _REDUCERS or reducer.unweighted:
        fail("Image.arrayReduce requires a supported single-output scalar Reducer")
    if not isinstance(axes, list) or not axes or len(axes) > len(array.shape):
        fail("Image.arrayReduce requires a nonempty list of array axes")
    axes = tuple(integer(axis, "Image.arrayReduce axis", 0) for axis in axes)
    if len(set(axes)) != len(axes) or any(axis >= len(array.shape) for axis in axes):
        fail("Image.arrayReduce axes must be unique and within the array rank")
    count = math.prod(array.shape[axis] for axis in axes)
    if reducer.name == "sd" and count < 2:
        fail("Sample standard deviation requires at least two array elements")
    shape = tuple(1 if axis in axes else length for axis, length in enumerate(array.shape))
    size = check_shape(shape)
    charge_array(translator, len(array.cells) * (4 + len(shape)) + size)
    strides = [math.prod(array.shape[axis + 1:]) for axis in range(len(shape))]
    cells = []
    for position in itertools.product(*(range(length) for length in shape)):
        group = []
        ranges = [range(array.shape[axis]) if axis in axes else [index]
                  for axis, index in enumerate(position)]
        for coordinates in itertools.product(*ranges):
            offset = sum(index * stride for index, stride in zip(coordinates, strides))
            group.append(array.cells[offset])
        cells.append(Pixel("reduce_bands", (tuple(group), reducer.name)))
    return wrap_array_image(array.image, shape, tuple(cells), array.mask, array.name)
