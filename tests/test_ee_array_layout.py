"""Pinned Python Array layout serialization and bounded semantic controls."""
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine import array_layout
from gee.compat.earthengine.array_core import StaticArray, wrap_array
from gee.compat.earthengine.array_values import invoke_array
from gee.compat.earthengine.decoder import Translator
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def output(ee, value):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, [], {})["value"]


def array(values):
    return invoke_array(Translator([], {}, {}), "Array", {"values": values})


def layout(name, **arguments):
    return array_layout.invoke_layout(Translator([], {}, {}), name, arguments)


def test_pinned_sdk_serializes_slice_defaults_negative_offsets_and_empty_axes(ee):
    values = ee.Array([[0, 1, 2, 3, 4], [10, 11, 12, 13, 14]])
    assert output(ee, values.slice()) == [[0, 1, 2, 3, 4], [10, 11, 12, 13, 14]]
    assert output(ee, values.slice(axis=1, start=-3, end=-1, step=2)) == [[2], [12]]
    assert output(ee, values.slice(axis=1, start=20, end=30)) == [[], []]


def test_pinned_sdk_serializes_whole_array_repeat_and_project_and_cat(ee):
    assert output(ee, ee.Array([1, 2]).repeat(copies=3)) == [1, 2, 1, 2, 1, 2]
    values = ee.Array([[[1, 2, 3]], [[4, 5, 6]]])
    assert output(ee, values.project([0, 2])) == [[1, 2, 3], [4, 5, 6]]
    left = ee.Array([[1, 2], [3, 4]])
    right = ee.Array([[5], [6]])
    assert output(ee, ee.Array.cat([left, right], axis=1)) == [[1, 2, 5], [3, 4, 6]]


def test_pinned_sdk_raw_cat_lists_are_not_typed_array_coercions(ee):
    # The official SDK serializes these as plain nested lists. This local
    # backend requires each List<Array> member to be an actual ee.Array value.
    expression = ee.Array.cat([[[1, 2]], [[3, 4]]])
    with pytest.raises(UnsupportedEEError, match="static ee.Array"):
        output(ee, expression)


def test_slice_preserves_step_origin_for_negative_offsets_and_rank():
    values = array([0, 1, 2, 3, 4])
    result = layout("Array.slice", array=values, start=-10, end=5, step=3)
    assert result.data.shape == (2,)
    assert result.to_value() == [1, 4]
    assert layout("Array.slice", array=values, start=0, end=-1, step=2).to_value() == [0, 2]

    matrix = array([[0, 1, 2], [3, 4, 5]])
    empty = layout("Array.slice", array=matrix, axis=0, start=8, end=20)
    assert empty.data.shape == (0, 3)
    assert empty.to_value() == []


def test_project_drops_only_singletons_and_keeps_zero_axis_when_retained():
    cube = array([[[1, 2, 3]], [[4, 5, 6]]])
    projected = layout("Array.project", array=cube, axes=[0, 2])
    assert projected.data.shape == (2, 3)
    assert projected.to_value() == [[1, 2, 3], [4, 5, 6]]

    matrix = array([[1, 2], [3, 4]])
    with pytest.raises(UnsupportedEEError, match="singleton"):
        layout("Array.project", array=matrix, axes=[0])
    with pytest.raises(UnsupportedEEError, match="ascending"):
        layout("Array.project", array=cube, axes=[2, 0])
    with pytest.raises(UnsupportedEEError, match="ascending"):
        layout("Array.project", array=cube, axes=[0, 0])

    empty = layout("Array.slice", array=cube, axis=1, start=1, end=1)
    assert empty.data.shape == (2, 0, 3)
    assert layout("Array.project", array=empty, axes=[0, 1, 2]).data.shape == (2, 0, 3)
    with pytest.raises(UnsupportedEEError, match="zero-length"):
        layout("Array.project", array=empty, axes=[0, 2])


def test_repeat_tiles_the_full_array_and_cat_concatenates_only_one_axis():
    matrix = array([[1, 2], [3, 4]])
    tiled = layout("Array.repeat", array=matrix, axis=1, copies=2)
    assert tiled.to_value() == [[1, 2, 1, 2], [3, 4, 3, 4]]
    assert tiled.data.shape == (2, 4)

    combined = layout("Array.cat", arrays=[array([[1], [2]]), array([[3, 4], [5, 6]])], axis=1)
    assert combined.to_value() == [[1, 3, 4], [2, 5, 6]]
    assert combined.data.shape == (2, 3)


def test_layout_outputs_are_independent_read_only_arrays():
    source = array([[1, 2], [3, 4]])
    result = layout("Array.repeat", array=source, axis=0, copies=2)
    assert isinstance(result, StaticArray)
    assert result.data.flags.writeable is False
    assert not np.shares_memory(source.data, result.data)
    assert source.to_value() == [[1, 2], [3, 4]]
    with pytest.raises(ValueError):
        result.data[0, 0] = 99


@pytest.mark.parametrize("name,args", [
    ("Array.slice", {}),
    ("Array.slice", {"array": [[1]], "axis": 0}),
    ("Array.slice", {"array": None, "ignored": 1}),
    ("Array.project", {"array": None}),
    ("Array.project", {"array": None, "axes": [], "extra": 1}),
    ("Array.repeat", {}),
    ("Array.repeat", {"array": None, "copies": True}),
    ("Array.cat", {}),
    ("Array.cat", {"arrays": [[1, 2]]}),
    ("Array.cat", {"arrays": []}),
])
def test_layout_rejects_missing_unknown_and_untyped_arguments(name, args):
    with pytest.raises(UnsupportedEEError):
        array_layout.invoke_layout(Translator([], {}, {}), name, args)


@pytest.mark.parametrize("operation", [
    lambda: layout("Array.slice", array=array([1, 2]), axis=1),
    lambda: layout("Array.slice", array=array([1, 2]), step=0),
    lambda: layout("Array.slice", array=array([1, 2]), step=-1),
    lambda: layout("Array.slice", array=array([1, 2]), start=1.5),
    lambda: layout("Array.repeat", array=array([1, 2]), axis=1),
    lambda: layout("Array.repeat", array=array([1, 2]), copies=-1),
    lambda: layout("Array.repeat", array=array([1, 2]), copies=2.5),
    lambda: layout("Array.project", array=array([1, 2]), axes=[True]),
    lambda: layout("Array.project", array=array([1, 2]), axes=[2]),
    lambda: layout("Array.project", array=array([1, 2]), axes="0"),
    lambda: layout("Array.cat", arrays=[array([1, 2]), array([[3, 4]])]),
    lambda: layout("Array.cat", arrays=[array([1, 2]), array([3, 4])], axis=1),
])
def test_layout_rejects_invalid_axes_types_and_shapes(operation):
    with pytest.raises(UnsupportedEEError):
        operation()


def test_zero_rank_and_zero_copy_edges_are_bounded():
    scalar = array(7)
    assert layout("Array.project", array=scalar, axes=[]).to_value() == 7
    with pytest.raises(UnsupportedEEError, match="at least one axis"):
        layout("Array.slice", array=scalar)
    with pytest.raises(UnsupportedEEError, match="at least one axis"):
        layout("Array.repeat", array=scalar)
    with pytest.raises(UnsupportedEEError, match="at least one axis"):
        layout("Array.cat", arrays=[scalar])

    result = layout("Array.repeat", array=array([1, 2]), copies=0)
    assert result.data.shape == (0,)
    assert result.to_value() == []


def test_cat_enforces_array_list_and_result_cell_budgets_before_allocation(monkeypatch):
    single = array([1])
    with pytest.raises(UnsupportedEEError, match="1..1000"):
        layout("Array.cat", arrays=[single] * 1001)

    large = array(list(range(10_000)))

    def allocation_forbidden(*args, **kwargs):
        raise AssertionError("cat allocated before rejecting an oversized result")

    monkeypatch.setattr(array_layout.np, "concatenate", allocation_forbidden)
    with pytest.raises(UnsupportedEEError, match="10000"):
        layout("Array.cat", arrays=[large, single])


def test_repeat_preflights_zero_axis_copy_count_shape_and_work(monkeypatch):
    empty = layout("Array.slice", array=array([1, 2]), start=1, end=1)

    def allocation_forbidden(*args, **kwargs):
        raise AssertionError("repeat allocated before validating its budget")

    monkeypatch.setattr(array_layout.np, "concatenate", allocation_forbidden)
    with pytest.raises(UnsupportedEEError, match="copies exceed"):
        layout("Array.repeat", array=empty, copies=10_001)

    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        array_layout.invoke_layout(translator, "Array.repeat", {"array": array([1]), "copies": 2})
    assert translator.steps == 49_999


def test_slice_preflights_work_before_gather_allocation(monkeypatch):
    translator = Translator([], {}, {})
    translator.steps = 49_999

    def allocation_forbidden(*args, **kwargs):
        raise AssertionError("slice allocated before checking its work budget")

    monkeypatch.setattr(array_layout.np, "take", allocation_forbidden)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        array_layout.invoke_layout(
            translator, "Array.slice", {"array": array([1, 2]), "start": 0, "end": 1}
        )
    assert translator.steps == 49_999


def test_cat_and_project_work_budgets_are_shared_with_the_translator():
    values = array([[1, 2], [3, 4]])
    translator = Translator([], {}, {})
    translator.steps = 49_998
    with pytest.raises(UnsupportedEEError, match="work budget"):
        array_layout.invoke_layout(translator, "Array.project", {"array": values, "axes": [0, 1]})
    assert translator.steps == 49_998

    translator = Translator([], {}, {})
    translator.steps = 49_998
    with pytest.raises(UnsupportedEEError, match="work budget"):
        array_layout.invoke_layout(
            translator, "Array.cat", {"arrays": [array([1]), array([2])]}
        )
    assert translator.steps == 49_998
