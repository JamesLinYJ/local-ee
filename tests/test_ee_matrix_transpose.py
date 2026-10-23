"""The pinned matrixTranspose alias preserves array cells and all boundaries."""
import json
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, Source, const
from gee.compat.earthengine.raster_array_core import wrap_array_image
from gee.compat.earthengine.raster_array_dispatch import invoke_raster_array
from gee.ee_translate import UnsupportedEEError


def _array(shape):
    count = int(np.prod(shape))
    source = Source("synthetic", ("scene",), ("value",))
    image = Image([], {"origin": "transpose-control"}, source)
    cells = tuple(Pixel("to_double", (Pixel("to_float", (const(i + 0.25),)),))
                  for i in range(count))
    return wrap_array_image(image, shape, cells, const(False), "factor")


def _invoke(array, **axes):
    return invoke_raster_array(Translator([], {}, {}), "Image.matrixTranspose", {"input": array, **axes})


@pytest.mark.parametrize("shape,axes", [
    ((2, 3), (0, 1)), ((2, 2, 3), (0, 2)), ((1,) * 8, (1, 7)),
    ((64,), (0, 0)), ((2, 3), (1, 1)),
])
def test_alias_preserves_exact_cell_identities_mask_casts_and_metadata(shape, axes):
    array = _array(shape)
    result = _invoke(array, axis1=axes[0], axis2=axes[1])
    indexes = np.arange(len(array.cells)).reshape(shape).swapaxes(*axes)
    assert result.shape == indexes.shape
    assert all(result.cells[i] is array.cells[int(index)] for i, index in enumerate(indexes.flat))
    assert result.mask is array.mask and result.name == array.name
    assert result.image.props == array.image.props
    assert result.image.source == array.image.source
    assert all(pixel.op == "to_double" and pixel.args[0].op == "to_float" for pixel in result.cells)


@pytest.mark.parametrize("axes", [
    {"axis1": -1}, {"axis2": 2}, {"axis1": True}, {"axis1": None},
    {"axis1": 0.5}, {"axis2": float("inf")}, {"axis2": float("nan")},
    {"value": 0},
])
def test_alias_rejects_invalid_axes_and_unknown_arguments(axes):
    with pytest.raises(UnsupportedEEError):
        _invoke(_array((2, 3)), **axes)


def test_alias_default_axes_and_unchanged_work_budget():
    array = _array((2, 3))
    result = _invoke(array)
    assert result.shape == (3, 2)
    assert result.cells == tuple(array.cells[i] for i in (0, 3, 1, 4, 2, 5))
    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_raster_array(translator, "Image.matrixTranspose", {"input": array})
    assert translator.steps == 49_999


def test_pinned_alias_signatures_have_identical_input_and_axis_contracts():
    algorithms = json.loads((Path(__file__).resolve().parents[1] /
                             "vendor/earthengine-js/algorithms.json").read_text())["algorithms"]
    signatures = {entry["name"]: entry for entry in algorithms}
    matrix = signatures["algorithms/Image.matrixTranspose"]
    array = signatures["algorithms/Image.arrayTranspose"]
    assert matrix["arguments"] == array["arguments"]
    assert matrix["returnType"] == array["returnType"]
