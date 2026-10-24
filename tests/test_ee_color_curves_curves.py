"""Pinned-SDK interpolation and polynomial graph/value tests."""
from __future__ import annotations

import numpy as np
import pytest

from ee_color_curves_reference import interpolate as reference_interpolate
from ee_color_curves_reference import polynomial as reference_polynomial
from ee_float64_graph_reference import evaluate_float64_graph
from ee_color_curves_test_support import (
    BANDS,
    assert_graph_budget,
    encode,
    ee,
    find_invocation,
    local,
    nodes,
    offline_only,
    pixels,
)
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.image_curves import invoke_image_curves
from gee.compat.earthengine.ir import Image, Pixel, UnsupportedEEError, const
from gee.ee_translate import compile_expression


@pytest.mark.parametrize("behavior", ["extrapolate", "clamp", "input", "mask"])
def test_interpolate_each_first_band_sample_against_fraction_reference(
        ee, local, behavior):
    values = [-3.0, -2.0, -1.0, -0.5, 0.0, 0.25, 1.0, 1.5, 2.0, 3.0, 4.0]
    x = (-2.0, 0.0, 2.0)
    y = (3.0, -1.0, 5.0)
    image = ee.Image("scene-a").interpolate(list(x), list(y), behavior)
    result = compile_expression(encode(ee, image), *local)
    assert result["bands"] == ["blue"]
    assert result["source_item_ids"] == ["scene-a"]
    assert_graph_budget(result)
    data = pixels([0.2] * len(values), [0.1] * len(values), values)
    actual, names, _timed = evaluate_float64_graph(result, data)
    expected = np.asarray(
        [reference_interpolate(value, x, y, behavior) for value in values],
        dtype=np.float64,
    )[None, :]
    np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-14, equal_nan=True)
    finite = np.isfinite(expected)
    error = np.max(np.abs(actual[finite] - expected[finite])) if finite.any() else 0.0
    assert error < 2e-14
    assert names == ["blue"]


def test_interpolate_masks_first_band_only_and_uses_default_or_null_behavior(ee, local):
    values = [-1.0, 0.0, 0.5, 1.0, 2.0]
    image = ee.Image("scene-a").interpolate([0.0, 1.0], [2.0, 4.0])
    result = compile_expression(encode(ee, image), *local)
    actual, names, _timed = evaluate_float64_graph(
        result, pixels([np.nan] * len(values), [np.nan] * len(values), values),
    )
    expected = np.asarray([
        reference_interpolate(value, (0.0, 1.0), (2.0, 4.0), "extrapolate")
        for value in values
    ])[None, :]
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-14)
    assert names == ["blue"]
    explicit_null = find_invocation(
        encode(ee, ee.Image("scene-a").interpolate([0.0, 1.0], [2.0, 4.0], None)),
        "Image.interpolate",
    )
    assert "behavior" not in explicit_null["arguments"]


@pytest.mark.parametrize("band_count", range(1, 9))
def test_polynomial_applies_ascending_coefficients_to_all_bands(
        ee, local, band_count):
    if band_count <= len(BANDS):
        output_names = BANDS[:band_count]
        source_names = output_names
        source = ee.Image("scene-a").select(output_names).toDouble()
    else:
        output_names = list(BANDS)
        source_names = list(BANDS)
        source = ee.Image("scene-a").select(BANDS).toDouble()
        for index in range(len(BANDS), band_count):
            source_name = BANDS[index % len(BANDS)]
            output_name = f"extra{index}"
            source = source.addBands(
                ee.Image("scene-a").select([source_name]).rename([output_name]).toDouble(),
            )
            output_names.append(output_name)
            source_names.append(source_name)
    coefficients = (1.25, -2.5, 0.75, -0.125)
    result = compile_expression(
        encode(ee, source.polynomial(list(coefficients))), *local,
    )
    assert result["bands"] == output_names
    assert result["source_item_ids"] == ["scene-a"]
    assert_graph_budget(result)
    base = np.asarray([-2.0, -0.5, 0.0, 1.0, 2.0], dtype=np.float64)
    arrays = {"scene-a": {name: base + band_index / 8
                           for band_index, name in enumerate(BANDS)}}
    actual, names, _timed = evaluate_float64_graph(result, arrays)
    expected = np.asarray([
        [reference_polynomial(value, coefficients)
         for value in arrays["scene-a"][source_name]]
        for source_name in source_names
    ])
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-13)
    assert names == output_names


def test_polynomial_constant_and_float32_cast_staging_preserve_masks(ee, local):
    source = ee.Image("scene-a").select(["red", "green"]).toFloat().toDouble()
    result = compile_expression(encode(ee, source.polynomial([4.0])), *local)
    assert result["bands"] == ["red", "green"]
    arrays = {"scene-a": {
        "red": np.asarray([16777217.0, np.nan, 3.0]),
        "green": np.asarray([-16777219.0, 0.0, 7.0]),
    }}
    actual, _names, _timed = evaluate_float64_graph(result, arrays)
    np.testing.assert_allclose(
        actual, np.asarray([[4.0, np.nan, 4.0], [4.0, 4.0, 4.0]]),
        rtol=0, atol=0, equal_nan=True,
    )
    assert nodes(result, "local_ee_to_float")
    assert nodes(result, "local_ee_to_double")

    identity = ee.Image("scene-a").select("red").toFloat().toDouble().polynomial([0, 1])
    staged = compile_expression(encode(ee, identity), *local)
    values, _names, _timed = evaluate_float64_graph(
        staged, {"scene-a": {"red": np.asarray([16777217.0, -16777219.0])}},
    )
    expected = np.asarray(np.asarray([16777217.0, -16777219.0], dtype=np.float32),
                          dtype=np.float64)[None, :]
    np.testing.assert_array_equal(values, expected)


def test_source_free_polynomial_folds_without_fabricating_a_grid():
    translator = Translator([], {}, {})
    image = Image([("constant", const(3.0))], {})
    result = invoke_image_curves(
        translator, "Image.polynomial",
        {"image": image, "coefficients": [2.0, -1.0, 0.5]},
    )
    graph_value = __import__(
        "gee.compat.earthengine.graph", fromlist=["Graph"],
    ).Graph(translator).expression(result.bands[0][1])
    assert graph_value == (3.5, None, True)


@pytest.mark.parametrize(
    "name,args,message",
    [
        ("Image.interpolate", {"x": [0, 0], "y": [1, 2]}, "strictly increasing"),
        ("Image.interpolate", {"x": [0, 1], "y": [1, 2, 3]}, "equal lengths"),
        ("Image.interpolate", {"x": [0, float("nan")], "y": [1, 2]}, "finite"),
        ("Image.interpolate", {"x": [0, 1], "y": [1, 2], "behavior": "wrap"}, "behavior"),
        ("Image.polynomial", {"coefficients": []}, "literal list"),
        ("Image.polynomial", {"coefficients": [True]}, "non-boolean"),
        ("Image.polynomial", {"coefficients": [float("inf")]}, "finite"),
    ],
)
def test_curve_arguments_reject_invalid_values_explicitly(name, args, message):
    translator = Translator([], {}, {})
    image = Image([("value", Pixel("band", (object(), "value")))], {})
    with pytest.raises(UnsupportedEEError, match=message):
        invoke_image_curves(translator, name, {"image": image, **args})
