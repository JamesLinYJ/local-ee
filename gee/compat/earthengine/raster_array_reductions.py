"""Lower bounded Image.arrayReduce calls to single-band pixel reductions."""
from __future__ import annotations

import math

from .array_core import charge_array
from .ir import Pixel, Reducer, fail
from .numeric_reducer_plan import numeric_outputs
from .raster_array_core import RasterArrayImage, check_shape, wrap_array_image
from .raster_array_reduction_layout import reduction_groups, reduction_layout


RASTER_ARRAY_REDUCTION_FUNCTIONS = frozenset({"Image.arrayReduce"})
_OPERATIONS = frozenset({
    "sum", "mean", "min", "max", "count", "first", "last", "median", "sd",
    "product", "stdDev", "variance", "sampleVariance",
})


def invoke_raster_reduction(translator, name, arguments):
    if name not in RASTER_ARRAY_REDUCTION_FUNCTIONS:
        fail(f"Unsupported raster array reduction: {name}")
    translator.allowed(arguments, {"input", "reducer", "axes", "fieldAxis"})
    array = arguments.get("input")
    if not isinstance(array, RasterArrayImage):
        fail("Image.arrayReduce requires a fixed-shape array image")
    input_count = check_shape(array.shape)
    if (type(array.cells) is not tuple or len(array.cells) != input_count
            or any(not isinstance(cell, Pixel) for cell in array.cells)):
        fail("Image.arrayReduce received malformed fixed-shape array cells")

    outputs = numeric_outputs(translator, arguments.get("reducer"))
    if (type(outputs) is not tuple or not outputs
            or any(type(item) is not tuple or len(item) != 2
                   or type(item[0]) is not str or type(item[1]) is not str
                   or item[1] not in _OPERATIONS
                   for item in outputs)):
        fail("Image.arrayReduce requires supported numeric reducer outputs")
    axes, field_axis, shape = reduction_layout(
        array.shape,
        arguments.get("axes"),
        arguments.get("fieldAxis"),
        len(outputs),
    )
    output_count = check_shape(shape)
    reduction_count = math.prod(array.shape[axis] for axis in axes)
    if "sd" in {operation for _, operation in outputs} and reduction_count < 2:
        fail("Sample standard deviation requires at least two array elements")

    # Reserve the input visits for each output field before making group and
    # cast tuples. The existing shape, rank and shared 50000-work caps apply.
    charge_array(
        translator,
        input_count * len(outputs) * (4 + len(array.shape)) + output_count,
    )
    typed = type(arguments.get("reducer")) is not Reducer
    if typed:
        # Prove every set of operands before constructing any Float64 cast
        # node. A fieldAxis can leave several independent groups in the array.
        from .numeric_reducer_grid import require_common_grid

        validated_groups = set()
        for _, offsets in reduction_groups(array.shape, shape, axes, field_axis):
            if offsets in validated_groups:
                continue
            validated_groups.add(offsets)
            require_common_grid(
                translator,
                tuple(array.cells[offset] for offset in offsets),
                label="Image.arrayReduce typed operands",
            )

    cells = []
    for position, offsets in reduction_groups(array.shape, shape, axes, field_axis):
        field = 0 if field_axis is None else position[field_axis]
        group = tuple(array.cells[offset] for offset in offsets)
        if typed:
            # Composed and finite numeric descriptors use native Float64
            # reducers. Legacy Reducer callbacks retain their Float32 path.
            group = tuple(Pixel("to_double", (cell,)) for cell in group)
        cells.append(Pixel("reduce_bands", (group, outputs[field][1])))
    return wrap_array_image(
        array.image, shape, tuple(cells), array.mask, array.name,
    )
