"""Grid proof and bounded-layout checks for raster-array reductions."""
import pytest

from gee.compat.earthengine.composed_reducer_spec import ReducerSpec
from gee.compat.earthengine.finite_reducer_leaves import FiniteReducerLeaf
from gee.compat.earthengine.ir import (
    Image, Pixel, Reducer, Source, UnsupportedEEError, const,
)
from gee.compat.earthengine.raster_array_core import RasterArrayImage
from gee.compat.earthengine.raster_array_reduction_layout import reduction_layout
from gee.compat.earthengine.raster_array_reductions import invoke_raster_reduction


class _Budget:
    def __init__(self, steps=0):
        self.steps = steps

    def allowed(self, arguments, keys):
        if set(arguments) - keys:
            raise AssertionError("unexpected arguments")


class _GridTranslator(_Budget):
    def __init__(self, items):
        super().__init__()
        self.items = items

    def member(self, source, item_id):
        return self.items[source.cid][item_id]


def _typed_two_source_array(grid_b_shift):
    left_source = Source("one-catalog", ("left",), ("red",))
    right_source = Source("one-catalog", ("right",), ("red",))
    transform = [1, 0, 0, 0, -1, 1]
    items = {
        "one-catalog": {
            "left": {"id": "left", "properties": {
                "proj:code": "EPSG:4326", "proj:transform": transform,
            }},
            "right": {"id": "right", "properties": {
                "proj:code": "EPSG:4326",
                "proj:transform": [1, 0, grid_b_shift, 0, -1, 1],
            }},
        },
    }
    image = Image([], {}, left_source)
    array = RasterArrayImage(
        image, (2,),
        (Pixel("band", (left_source, "red")),
         Pixel("band", (right_source, "red"))),
        const(True),
    )
    reducer = ReducerSpec(
        "leaf", 1, ("stdDev",), leaf=FiniteReducerLeaf("stdDev"),
    )
    return _GridTranslator(items), array, reducer


def test_typed_array_reduction_proves_alignment_before_float64_cast():
    translator, array, reducer = _typed_two_source_array(1)
    result = invoke_raster_reduction(
        translator, "Image.arrayReduce",
        {"input": array, "reducer": reducer, "axes": [0]},
    )
    assert result.cells[0].op == "reduce_bands"
    assert result.cells[0].args[1] == "stdDev"
    assert all(pixel.op == "to_double" for pixel in result.cells[0].args[0])

    translator, array, reducer = _typed_two_source_array(0.5)
    with pytest.raises(UnsupportedEEError, match="common pixel grid"):
        invoke_raster_reduction(
            translator, "Image.arrayReduce",
            {"input": array, "reducer": reducer, "axes": [0]},
        )


@pytest.mark.parametrize("shape", [(65,), (8, 8, 2), (1,) * 9])
def test_input_shape_caps_reject_before_cell_walk(shape):
    invalid = RasterArrayImage(Image([], {}), shape, (), const(True))
    with pytest.raises(UnsupportedEEError, match="Raster Array"):
        invoke_raster_reduction(
            _Budget(), "Image.arrayReduce",
            {"input": invalid, "reducer": Reducer("sum"), "axes": [0]},
        )


@pytest.mark.parametrize("shape,axes,field_axis,outputs,reason", [
    ((1, 1), [0], 1, 65, "axes"),
    ((2, 32, 1), [0], 2, 3, "64 cells"),
])
def test_output_axis_and_cell_caps_apply_before_layout_allocation(
        shape, axes, field_axis, outputs, reason):
    with pytest.raises(UnsupportedEEError, match=reason):
        reduction_layout(shape, axes, field_axis, outputs)


def test_reduction_shares_the_existing_50000_work_budget():
    translator = _Budget(steps=49_999)
    array = RasterArrayImage(
        Image([], {}), (2,), (const(1), const(2)), const(True),
    )
    with pytest.raises(UnsupportedEEError, match="50000|work budget"):
        invoke_raster_reduction(
            translator, "Image.arrayReduce",
            {"input": array, "reducer": Reducer("sum"), "axes": [0]},
        )
    assert translator.steps == 49_999
