"""Typed array-image metadata and control-flow boundaries stay explicit."""
import numpy as np
import pytest

from gee.ee_translate import UnsupportedEEError, compile_expression
from test_ee_raster_array_values import ee, compile_value, evaluated_bands
from test_ee_translate import arrays as sample_arrays, local as local_fixture


def test_static_if_and_dictionary_default_preserve_array_image_type(ee, local_fixture, sample_arrays):
    first = ee.Image("a").select(["red", "nir"]).toArray()
    other = ee.Image("b").select(["red", "nir"]).toArray()
    expressions = [ee.Image(ee.Algorithms.If(True, first, other)),
                   ee.Image(ee.Dictionary({}).get("absent", first))]
    for expression in expressions:
        result = compile_value(ee, expression.arrayFlatten([["red", "nir"]]), local_fixture)
        actual = evaluated_bands(result, sample_arrays)
        np.testing.assert_allclose(actual["red"], [1, 3])
        np.testing.assert_allclose(actual["nir"], [1, 3])
        assert result["source_item_ids"] == ["a"]


def test_array_metadata_rename_and_copy_keep_the_logical_band_and_mask(ee, local_fixture, sample_arrays):
    source = ee.Image("b").select(["red", "nir"])
    array = source.toArray().rename("vector").set("tag", "sample")
    array = ee.Image(array.copyProperties(source, ["system:index"]))
    assert compile_value(ee, array.bandNames(), local_fixture)["value"] == ["vector"]
    assert compile_value(ee, array.get("tag"), local_fixture)["value"] == "sample"
    assert compile_value(ee, array.get("system:index"), local_fixture)["value"] == "b"
    result = compile_value(ee, array.arrayGet([0]), local_fixture)
    assert result["bands"] == ["vector"]
    actual = evaluated_bands(result, sample_arrays)
    np.testing.assert_allclose(actual["vector"], [1, np.nan], equal_nan=True)


def test_array_image_is_neither_a_static_truth_value_nor_public_json(ee, local_fixture):
    array = ee.Image("a").select(["red", "nir"]).toArray()
    with pytest.raises(UnsupportedEEError, match="static scalar/list/dictionary condition"):
        compile_value(ee, ee.Algorithms.If(array, 1, 0), local_fixture)
    with pytest.raises(UnsupportedEEError, match="public JSON boundary"):
        compile_value(ee, ee.List([array]), local_fixture)
    with pytest.raises(UnsupportedEEError, match="Unsupported operation on a fixed-shape array image"):
        compile_value(ee, array.sqrt().arrayFlatten([["red", "nir"]]), local_fixture)


def test_array_metadata_does_not_silently_accept_unknown_parameters(ee, local_fixture):
    value = ee.Image("a").select(["red", "nir"]).toArray().get("system:index")
    expression = ee.serializer.encode(value, for_cloud_api=False)
    for _, node in expression["scope"]:
        if isinstance(node, dict) and node.get("functionName") == "Element.get":
            node["arguments"]["ignored"] = 1
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(expression, *local_fixture)


def test_storing_array_image_metadata_never_substitutes_its_scalar_source(ee, local_fixture):
    source = ee.Image("a")
    array = source.select(["red", "nir"]).toArray()
    for expression in [source.set("array_value", array),
                       source.set({"array_value": array}),
                       array.set("array_value", array)]:
        with pytest.raises(UnsupportedEEError, match="Only static JSON values"):
            compile_value(ee, expression, local_fixture)
