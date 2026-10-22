"""Raster-array layout controls against raw IR and the pinned EE SDK."""
from pathlib import Path
import runpy

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, Source, const
from gee.compat.earthengine.raster_array_core import (
    RasterArrayImage,
    wrap_array_image,
)
from gee.compat.earthengine.raster_array_layout import (
    RASTER_ARRAY_LAYOUT_FUNCTIONS,
    invoke_raster_layout,
)
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def local_catalog():
    names = ["blue", "red"]
    catalog = [{
        "id": "sentinel-2-l2a",
        "cube:dimensions": {"bands": {"values": names}},
    }]
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
    }
    items = {"sentinel-2-l2a": [{
        "id": "scene-1",
        "bbox": [0, 0, 2, 2],
        "geometry": geometry,
        "properties": {"system:time_start": 1000, "system:index": "scene-1"},
    }]}
    rasters = {
        "scene-1": {
            "blue": np.array([1.0, 2.0]),
            "red": np.array([3.0, np.nan]),
        },
    }
    return catalog, items, rasters


def compile_sdk(ee, value, catalog, items):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, catalog, items)


def evaluate(result, rasters):
    # Reuse the independent graph evaluator and its manual NumPy reference
    # conventions from the existing compiler tests.
    helpers = runpy.run_path(str(ROOT / "tests/test_ee_translate.py"))
    return helpers["evaluate_graph"](result, rasters)


def raster(shape, values, *, mask=None, name="array", props=None):
    source = Source("local", ("scene-1",), ("blue", "red"))
    image = Image([("input", Pixel("band", (source, "blue")))], props or {"meta": "kept"})
    cells = tuple(const(float(value)) for value in np.asarray(values).flat)
    mask = const(True) if mask is None else mask
    return wrap_array_image(image, tuple(shape), cells, mask, name)


def invoke(name, **arguments):
    return invoke_raster_layout(Translator([], {}, {}), name, arguments)


def test_sdk_serialization_flattens_transpose_and_project_with_row_major_names(ee):
    catalog, items, rasters = local_catalog()
    image = ee.ImageCollection("sentinel-2-l2a").first().select(["blue", "red"])
    # toArray(axis=1) appends a singleton axis to the existing vector. Swapping
    # it back exercises the two-axis permutation while preserving row order.
    value = (
        image.toArray()
        .toArray(axis=1)
        .arrayTranspose()
        .arrayProject([0, 1])
        .arrayFlatten([["row"], ["B", "R"]], separator="::")
    )

    result = compile_sdk(ee, value, catalog, items)
    evaluated, names, timed = evaluate(result, rasters)

    assert names == ["row::B", "row::R"]
    assert timed is False
    np.testing.assert_allclose(evaluated[0], [1.0, np.nan], equal_nan=True)
    np.testing.assert_allclose(evaluated[1], [3.0, np.nan], equal_nan=True)


def test_sdk_constant_image_slice_and_get_keep_the_array_mask(ee):
    catalog, items, rasters = local_catalog()
    image = ee.ImageCollection("sentinel-2-l2a").first().select(["blue", "red"])
    value = (
        image.toArray()
        .arraySlice(axis=0, start=ee.Image.constant(1), end=ee.Image.constant(2))
        .arrayGet(ee.Image.constant(0))
    )

    result = compile_sdk(ee, value, catalog, items)
    evaluated, names, timed = evaluate(result, rasters)

    assert names == ["array"]
    assert timed is False
    np.testing.assert_allclose(evaluated[0], [3.0, np.nan], equal_nan=True)


def test_sdk_rank_zero_project_and_empty_position_get_preserve_the_whole_mask(ee):
    catalog, items, rasters = local_catalog()
    image = ee.ImageCollection("sentinel-2-l2a").first().select(["red"])
    value = image.toArray().arrayProject([]).arrayGet(ee.Image.constant([]))

    result = compile_sdk(ee, value, catalog, items)
    evaluated, names, timed = evaluate(result, rasters)

    assert names == ["array"]
    assert timed is False
    np.testing.assert_allclose(evaluated[0], [3.0, np.nan], equal_nan=True)


def test_sdk_dynamic_slice_and_get_coordinates_are_rejected(ee):
    catalog, items, _ = local_catalog()
    image = ee.ImageCollection("sentinel-2-l2a").first().select(["blue", "red"])
    dynamic = ee.ImageCollection("sentinel-2-l2a").first().select(["blue"])
    array = image.toArray()

    with pytest.raises(UnsupportedEEError, match="pure constant scalar image"):
        compile_sdk(ee, array.arraySlice(start=dynamic), catalog, items)
    with pytest.raises(UnsupportedEEError, match="pure constant scalar image"):
        compile_sdk(ee, array.arrayGet(dynamic), catalog, items)


def test_flatten_uses_axis_labels_separator_and_preserves_metadata_mask():
    mask = Pixel("band", (Source("local", ("scene-1",), ("valid",)), "valid"), True)
    value = raster((2, 3), [[1, 2, 3], [4, 5, 6]], mask=mask, name="cube")

    result = invoke(
        "Image.arrayFlatten",
        image=value,
        coordinateLabels=[["day0", "day1"], ["red", "green", "blue"]],
        separator="/",
    )

    assert isinstance(result, Image)
    assert [name for name, _ in result.bands] == [
        "day0/red", "day0/green", "day0/blue",
        "day1/red", "day1/green", "day1/blue",
    ]
    assert result.props == {"meta": "kept"}
    assert all(pixel.op == "if" and pixel.args[0] is mask for _, pixel in result.bands)


@pytest.mark.parametrize("labels,separator,match", [
    ([["x"], ["y", "z"]], "_", "axis 0"),
    ([["x", "x"], ["y", "y"]], "", "duplicate band names"),
    ([["x", 1], ["y", "z"]], "_", "strings"),
    ([["x", "y"], ["z", "w"]], 1, "separator must be a string"),
])
def test_flatten_rejects_malformed_labels_and_separator(labels, separator, match):
    value = raster((2, 2), [[1, 2], [3, 4]])
    with pytest.raises(UnsupportedEEError, match=match):
        invoke(
            "Image.arrayFlatten", image=value,
            coordinateLabels=labels, separator=separator,
        )


def test_flatten_rejects_rank_zero_and_preflights_bandname_budget(monkeypatch):
    scalar = raster((), 7)
    with pytest.raises(UnsupportedEEError, match="rank-zero"):
        invoke("Image.arrayFlatten", image=scalar, coordinateLabels=[])

    value = raster((2, 2), [[1, 2], [3, 4]])
    translator = Translator([], {}, {})
    translator.steps = 49_999

    def product_forbidden(*args, **kwargs):
        raise AssertionError("flatten built the Cartesian product before preflight")

    import gee.compat.earthengine.raster_array_layout as raster_layout
    monkeypatch.setattr(raster_layout.itertools, "product", product_forbidden)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_raster_layout(
            translator, "Image.arrayFlatten",
            {"image": value, "coordinateLabels": [["a", "b"], ["c", "d"]]},
        )
    assert translator.steps == 49_999


def test_project_drops_singletons_and_allows_zero_rank_result():
    value = raster((2, 1, 3), [[[1, 2, 3]], [[4, 5, 6]]])
    projected = invoke("Image.arrayProject", input=value, axes=[0, 2])
    assert isinstance(projected, RasterArrayImage)
    assert projected.shape == (2, 3)
    assert [cell.args[0] for cell in projected.cells] == [1, 2, 3, 4, 5, 6]

    scalar = invoke(
        "Image.arrayProject", input=raster((1, 1), [[7]]), axes=[]
    )
    assert scalar.shape == ()
    assert scalar.cells[0].args == (7.0,)


@pytest.mark.parametrize("axes,match", [
    ([2, 0], "ascending"),
    ([0, 0], "ascending"),
    ([0], "singleton"),
    ([3], "outside"),
    ("0", "list"),
])
def test_project_rejects_unsafe_axis_order_and_dropped_dimensions(axes, match):
    value = raster((2, 1, 3), [[[1, 2, 3]], [[4, 5, 6]]])
    with pytest.raises(UnsupportedEEError, match=match):
        invoke("Image.arrayProject", input=value, axes=axes)


def test_transpose_swaps_any_two_axes_in_row_major_storage():
    value = raster((2, 1, 3), [[[1, 2, 3]], [[4, 5, 6]]])
    result = invoke("Image.arrayTranspose", input=value, axis1=0, axis2=2)

    assert result.shape == (3, 1, 2)
    assert [cell.args[0] for cell in result.cells] == [1, 4, 2, 5, 3, 6]
    assert result.mask is value.mask
    assert result.image.props == value.image.props


def test_transpose_rejects_axes_outside_array_rank():
    with pytest.raises(UnsupportedEEError, match="outside"):
        invoke("Image.arrayTranspose", input=raster((2,), [1, 2]), axis1=4, axis2=0)


def test_slice_accepts_static_image_bounds_negative_offsets_and_step_origin():
    value = raster((2, 5), [[0, 1, 2, 3, 4], [10, 11, 12, 13, 14]])
    unchanged = invoke("Image.arraySlice", input=value)
    assert unchanged.shape == value.shape
    assert unchanged.cells == value.cells

    sliced = invoke(
        "Image.arraySlice", input=value, axis=1,
        start=Image([("constant", const(-3))], {}),
        end=Image([("constant", const(-1))], {}), step=2,
    )
    assert sliced.shape == (2, 1)
    assert [cell.args[0] for cell in sliced.cells] == [2.0, 12.0]

    vector = raster((5,), [0, 1, 2, 3, 4])
    origin = invoke(
        "Image.arraySlice", input=vector, start=-10, end=5, step=3,
    )
    assert origin.shape == (2,)
    assert [cell.args[0] for cell in origin.cells] == [1.0, 4.0]


@pytest.mark.parametrize("arguments,match", [
    ({"axis": 0, "start": 4, "end": 4}, "empty array"),
    ({"axis": 0, "start": 8, "end": 20}, "empty array"),
    ({"axis": 0, "step": 0}, "step must be >= 1"),
    ({"axis": 0, "step": -1}, "step must be >= 1"),
    ({"axis": 2}, "outside"),
])
def test_slice_rejects_empty_ranges_and_invalid_bounds(arguments, match):
    value = raster((5,), [0, 1, 2, 3, 4])
    with pytest.raises(UnsupportedEEError, match=match):
        invoke("Image.arraySlice", input=value, **arguments)


def test_slice_rejects_dynamic_and_multiband_image_coordinates():
    value = raster((3,), [0, 1, 2])
    dynamic = Image([("source", Pixel("band", (Source("local", ("s",), ("b",)), "b")))], {})
    with pytest.raises(UnsupportedEEError, match="pure constant scalar image"):
        invoke("Image.arraySlice", input=value, start=dynamic)
    with pytest.raises(UnsupportedEEError, match="exactly one scalar band"):
        invoke("Image.arraySlice", input=value, end=Image([("a", const(2)), ("b", const(3))], {}))


def test_get_uses_constant_coordinates_and_preserves_array_mask_and_name():
    mask = Pixel("band", (Source("local", ("scene-1",), ("valid",)), "valid"), True)
    value = raster((2, 3), [[1, 2, 3], [4, 5, 6]], mask=mask, name="matrix")
    position = Image([("row", const(1)), ("column", Pixel("add", (const(1), const(1))))], {})

    result = invoke("Image.arrayGet", image=value, position=position)

    assert result.bands[0][0] == "matrix"
    assert result.bands[0][1].op == "if"
    assert result.bands[0][1].args[0] is mask
    assert result.bands[0][1].args[1].args == (6.0,)
    assert result.props == {"meta": "kept"}


def test_get_accepts_rank_zero_array_with_zero_coordinate_bands():
    mask = Pixel("band", (Source("local", ("scene-1",), ("valid",)), "valid"), True)
    value = raster((), 7, mask=mask, name="scalar")

    result = invoke("Image.arrayGet", image=value, position=Image([], {}))

    assert result.bands[0][0] == "scalar"
    assert result.bands[0][1].op == "if"
    assert result.bands[0][1].args[0] is mask
    assert result.bands[0][1].args[1].args == (7.0,)


@pytest.mark.parametrize("position,match", [
    (Image([], {}), "one scalar band per"),
    (Image([("row", const(-1)), ("column", const(0))], {}), ">= 0"),
    (Image([("row", const(2)), ("column", const(0))], {}), "outside"),
    (Image([("row", Pixel("band", (Source("local", ("s",), ("b",)), "b"))), ("column", const(0))], {}), "pure constant scalar image"),
])
def test_get_rejects_missing_negative_dynamic_and_out_of_range_positions(position, match):
    value = raster((2, 3), [[1, 2, 3], [4, 5, 6]])
    with pytest.raises(UnsupportedEEError, match=match):
        invoke("Image.arrayGet", image=value, position=position)


def test_array_layout_preflights_work_before_transpose_and_get_materialization(monkeypatch):
    value = raster((2, 2), [[1, 2], [3, 4]])
    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_raster_layout(translator, "Image.arrayTranspose", {"input": value})
    assert translator.steps == 49_999

    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_raster_layout(
            translator, "Image.arrayProject", {"input": raster((1,), [1]), "axes": []}
        )
    assert translator.steps == 49_999

    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_raster_layout(
            translator, "Image.arraySlice", {"input": value, "start": 0, "end": 1}
        )
    assert translator.steps == 49_999

    def scalar_forbidden(*args, **kwargs):
        raise AssertionError("get materialized a scalar before checking work")

    import gee.compat.earthengine.raster_array_layout as raster_layout
    monkeypatch.setattr(raster_layout, "masked_scalar", scalar_forbidden)
    translator = Translator([], {}, {})
    translator.steps = 49_998
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_raster_layout(
            translator, "Image.arrayGet",
            {"image": value, "position": Image([("row", const(0)), ("col", const(0))], {})},
        )


def test_handler_inventory_and_unknown_arguments_are_explicit():
    assert RASTER_ARRAY_LAYOUT_FUNCTIONS == {
        "Image.arrayFlatten", "Image.arrayProject", "Image.arrayTranspose",
        "Image.arraySlice", "Image.arrayGet",
    }
    value = raster((1,), [1])
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke("Image.arrayGet", image=value, position=Image([("p", const(0))], {}), ignored=True)
