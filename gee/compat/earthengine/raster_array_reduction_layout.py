"""Fixed-shape layout planning for raster array reductions."""
from __future__ import annotations

import itertools
import math

from .ir import fail, integer
from .raster_array_core import check_shape


def reduction_layout(shape, raw_axes, raw_field_axis, output_count):
    """Validate axes and derive the fixed output shape and field-axis index."""
    rank = len(shape)
    if not isinstance(raw_axes, list) or not raw_axes or len(raw_axes) > rank:
        fail("Image.arrayReduce requires a nonempty list of array axes")
    axes = tuple(integer(axis, "Image.arrayReduce axis", 0) for axis in raw_axes)
    if len(set(axes)) != len(axes) or any(axis >= rank for axis in axes):
        fail("Image.arrayReduce axes must be unique and within the array rank")

    if type(output_count) is not int or output_count < 1:
        fail("Image.arrayReduce requires at least one numeric reducer output")
    field_axis = None
    if raw_field_axis is None:
        if output_count != 1:
            fail("Image.arrayReduce requires fieldAxis for a multi-output reducer")
    else:
        field_axis = integer(raw_field_axis, "Image.arrayReduce fieldAxis", 0)
        if field_axis >= rank:
            fail("Image.arrayReduce fieldAxis is outside the array rank")
        if field_axis in axes:
            fail("Image.arrayReduce fieldAxis cannot overlap a reduced axis")
        if shape[field_axis] != 1:
            fail("Image.arrayReduce input fieldAxis must have length 1")

    output_shape = tuple(
        output_count if axis == field_axis else 1 if axis in axes else length
        for axis, length in enumerate(shape)
    )
    check_shape(output_shape)
    return axes, field_axis, output_shape


def reduction_groups(input_shape, output_shape, axes, field_axis):
    """Yield row-major input offsets for each output cell."""
    strides = [math.prod(input_shape[axis + 1:])
               for axis in range(len(input_shape))]
    reduced = set(axes)
    for position in itertools.product(*(range(length) for length in output_shape)):
        fixed = [0 if axis == field_axis else index
                 for axis, index in enumerate(position)]
        ranges = [range(input_shape[axis]) if axis in reduced else (fixed[axis],)
                  for axis in range(len(input_shape))]
        offsets = tuple(
            sum(index * stride for index, stride in zip(coordinates, strides))
            for coordinates in itertools.product(*ranges)
        )
        yield position, offsets
