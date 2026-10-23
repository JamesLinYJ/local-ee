"""Shape validation and bounded output layout for static Array.reduce."""
from __future__ import annotations

import math

from .array_core import MAX_ARRAY_CELLS
from .ir import fail, integer


def _axis(value, rank, label):
    axis = integer(value, label, 0)
    if axis >= rank:
        fail("Array reduction axis is outside the array rank")
    return axis


def _axes(value, rank):
    if type(value) is not list or not value or len(value) > rank:
        fail("Array.reduce requires a nonempty list of axes")
    axes = tuple(_axis(axis, rank, "Array reduction axis") for axis in value)
    if len(set(axes)) != len(axes):
        fail("Array.reduce axes must be unique")
    return tuple(sorted(axes))


def reduction_layout(shape, axes_value, field_axis_value, input_count, output_count):
    """Validate field/reduction axes and preflight the shape-preserving result."""
    rank = len(shape)
    axes = _axes(axes_value, rank)
    field_axis = None
    if field_axis_value is None:
        if input_count != 1 or output_count != 1:
            fail("Array.reduce requires fieldAxis for multi-input or multi-output reducers")
    else:
        field_axis = _axis(field_axis_value, rank, "Array.reduce fieldAxis")
        if field_axis in axes:
            fail("Array.reduce fieldAxis cannot also be a reduction axis")
        if shape[field_axis] != input_count:
            fail("Array.reduce fieldAxis length must equal the reducer input count")

    reduced_count = math.prod(shape[axis] for axis in axes)
    if reduced_count == 0:
        fail("Empty Array reductions are currently unsupported")
    output_shape = tuple(
        1 if axis in axes else output_count if axis == field_axis else length
        for axis, length in enumerate(shape)
    )
    output_cells = math.prod(output_shape)
    if output_cells > MAX_ARRAY_CELLS:
        fail("Array.reduce result exceeds 10000 cells")
    retained = tuple(axis for axis in range(rank) if axis not in axes and axis != field_axis)
    group_count = math.prod(shape[axis] for axis in retained)
    return axes, field_axis, reduced_count, output_shape, output_cells, retained, group_count
