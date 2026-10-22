"""Typed multi-array Image selection and metadata behavior through the EE SDK."""
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, UnsupportedEEError, const
from gee.compat.earthengine.raster_array_bands import (
    RasterArrayBands,
    handles_array_bands,
    invoke_array_bands,
    wrap_array_bands,
)
from gee.compat.earthengine.raster_array_core import RasterArrayImage, wrap_array_image
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


@pytest.fixture
def local():
    names = ["x", "y1", "y2"]
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": names}}}]
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [3, 0], [3, 1], [0, 1], [0, 0]]],
    }
    ids = ["a", "b", "c"]
    items = {"sentinel-2-l2a": [
        {"id": item_id, "bbox": [0, 0, 3, 1], "geometry": geometry,
         "properties": {"system:index": item_id}}
        for item_id in ids
    ]}
    # The final pixel has only one complete row. Pixel 1 loses the middle
    # observation because one response is NoData, so both responses use rows
    # a and c from the same common complete-case set.
    rasters = {
        "a": {"x": np.array([1., 1., 1.]), "y1": np.array([2., 3., 2.]),
              "y2": np.array([-1., 4., 1.])},
        "b": {"x": np.array([2., 2., 2.]), "y1": np.array([4., np.nan, np.nan]),
              "y2": np.array([-2., 8., np.nan])},
        "c": {"x": np.array([3., 3., 3.]), "y1": np.array([6., 9., np.nan]),
              "y2": np.array([-3., 12., np.nan])},
    }
    return catalog, items, rasters


def compile_value(ee, value, local):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, local[0], local[1])


def invocation(value, name):
    if isinstance(value, dict):
        if value.get("type") == "Invocation" and value.get("functionName") == name:
            return value
        for child in value.values():
            found = invocation(child, name)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for child in value:
            found = invocation(child, name)
            if found is not None:
                return found
    return None


def make_array(image, shape, name, start=0):
    count = int(np.prod(shape)) if shape else 1
    cells = tuple(const(start + index) for index in range(count))
    return wrap_array_image(image, tuple(shape), cells, const(True), name)


def test_sdk_regression_bundle_select_rename_rewrap_and_masks(ee, local):
    fit = ee.ImageCollection("sentinel-2-l2a").reduce(
        ee.Reducer.linearRegression(numX=1, numY=2))
    renamed = fit.rename(["errors", "betas"]).set("tag", "kept")
    assert compile_value(ee, renamed.bandNames(), local)["value"] == ["errors", "betas"]
    conditional = ee.Image(ee.Algorithms.If(True, renamed, fit))
    dictionary_value = ee.Image(ee.Dictionary({"fit": renamed}).get("fit"))
    for carried in (conditional, dictionary_value):
        assert compile_value(ee, carried.bandNames(), local)["value"] == ["errors", "betas"]

    # Rewrapping an Image must retain the bundle type. Select supports exact
    # names and integer indices, preserves the requested order, and permits a
    # per-selection rename before each real array layout operation.
    bundle = ee.Image(renamed).select([1, 0], ["residuals", "coefficients"])
    coefficients = bundle.select("coefficients").arrayFlatten(
        [["x"], ["y1", "y2"]], separator="_")
    residuals = bundle.select("residuals").arrayFlatten([["y1", "y2"]])
    result = compile_value(ee, coefficients.addBands(residuals), local)
    assert result["kind"] == "image"
    assert result["bands"] == ["x_y1", "x_y2", "y1", "y2"]
    assert result["properties"] == {"tag": "kept"}

    values, names, timed = evaluate_graph(result, local[2])
    assert not timed
    assert names == result["bands"]
    np.testing.assert_allclose(values[:, 0], [2, -1, 0, 0], atol=1e-12)
    np.testing.assert_allclose(values[:, 1], [3, 4, 0, 0], atol=1e-12)
    assert np.isnan(values[:, 2]).all()

    with pytest.raises(UnsupportedEEError, match="Multiple array bands require select"):
        compile_value(ee, fit, local)
    with pytest.raises(UnsupportedEEError, match="static scalar/list/dictionary"):
        compile_value(ee, ee.Algorithms.If(fit, 1, 0), local)
    with pytest.raises(UnsupportedEEError, match="public JSON boundary"):
        compile_value(ee, ee.List([fit]), local)

    expression = deepcopy(ee.serializer.encode(renamed.bandNames(), for_cloud_api=False))
    wire_call = invocation(expression, "Image.bandNames")
    assert wire_call is not None
    wire_call["arguments"]["ignored"] = 1
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(expression, local[0], local[1])


def test_bundle_factory_validates_provenance_names_masks_shapes_and_total_cells():
    translator = Translator([], {}, {})
    image = Image([], {"tag": "source"})
    arrays = (make_array(image, (2,), "left"), make_array(image, (1, 2), "right", 4))
    bundle = wrap_array_bands(translator, image, arrays)
    assert isinstance(bundle, RasterArrayBands)
    assert bundle.image is image
    assert all(array.image is bundle.image for array in bundle.arrays)
    assert [array.name for array in bundle.arrays] == ["left", "right"]

    with pytest.raises(UnsupportedEEError, match="exact metadata Image"):
        wrap_array_bands(translator, image, (make_array(Image([], {}), (1,), "other"),))
    with pytest.raises(UnsupportedEEError, match="unique"):
        wrap_array_bands(translator, image, (make_array(image, (1,), "same"),
                                               make_array(image, (2,), "same")))
    with pytest.raises(UnsupportedEEError, match="64 total array cells"):
        too_many = (make_array(image, (64,), "wide"),) + tuple(
            make_array(image, (1,), f"b{index}") for index in range(7))
        wrap_array_bands(translator, image, too_many)
    with pytest.raises(UnsupportedEEError, match="placeholder bands"):
        wrap_array_bands(translator, Image([("fake", const(0))], {}),
                         (make_array(image, (1,), "only"),))


def test_selection_rejects_regex_duplicates_negative_indices_and_bad_new_names():
    translator = Translator([], {}, {})
    image = Image([], {})
    bundle = wrap_array_bands(translator, image, (
        make_array(image, (2,), "coefficients"),
        make_array(image, (1, 2), "residuals", 2),
    ))
    assert handles_array_bands("Image.select", {"input": bundle})

    scalar = invoke_array_bands(translator, "Image.select", {
        "input": bundle, "bandSelectors": ["residuals"], "newNames": ["errors"],
    })
    assert isinstance(scalar, RasterArrayImage)
    assert scalar.name == "errors"
    selected = invoke_array_bands(translator, "Image.select", {
        "input": bundle, "bandSelectors": [1, 0], "newNames": ["r", "c"],
    })
    assert isinstance(selected, RasterArrayBands)
    assert [array.name for array in selected.arrays] == ["r", "c"]

    invalid = [
        ({"bandSelectors": ["coef.*"]}, "exact array band name"),
        ({"bandSelectors": ["coefficients", "coefficients"]}, "duplicate"),
        ({"bandSelectors": [-1]}, "out of range"),
        ({"bandSelectors": [0], "newNames": ["",]}, "newNames"),
        ({"bandSelectors": [0, 1], "newNames": ["same", "same"]}, "newNames"),
    ]
    for options, message in invalid:
        with pytest.raises(UnsupportedEEError, match=message):
            invoke_array_bands(translator, "Image.select", {"input": bundle, **options})


def test_bundle_metadata_rebinds_every_array_and_other_image_ops_reject():
    translator = Translator([], {}, {})
    image = Image([], {"system:index": "a"})
    bundle = wrap_array_bands(translator, image, (
        make_array(image, (2,), "coefficients"),
        make_array(image, (1,), "residuals"),
    ))
    updated = invoke_array_bands(translator, "Element.set", {
        "object": bundle, "key": "tag", "value": "kept",
    })
    assert isinstance(updated, RasterArrayBands)
    assert updated.image.props["tag"] == "kept"
    assert all(array.image is updated.image for array in updated.arrays)
    assert [array.name for array in updated.arrays] == ["coefficients", "residuals"]

    with pytest.raises(UnsupportedEEError, match="Only static JSON values"):
        invoke_array_bands(translator, "Element.set", {
            "object": bundle, "key": "nested", "value": bundle,
        })
    with pytest.raises(UnsupportedEEError, match="Unsupported operation"):
        invoke_array_bands(translator, "Image.cast", {
            "image": bundle, "bandTypes": {"coefficients": "double"},
        })
    assert not handles_array_bands("Image.cast", {"image": Image([], {})})


def test_factory_preflights_shared_budget_before_copying():
    translator = Translator([], {}, {})
    translator.steps = 49_999
    image = Image([], {})
    array = make_array(image, (2,), "coefficients")
    with pytest.raises(UnsupportedEEError, match="work budget"):
        wrap_array_bands(translator, image, (array,))
    assert translator.steps == 49_999
