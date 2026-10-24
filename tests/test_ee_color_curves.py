"""Pinned-SDK color/curve compilation and independent numeric graph checks."""
from __future__ import annotations

import numpy as np
import pytest

from ee_color_curves_reference import (
    hsv_to_rgb as reference_hsv_to_rgb,
    rgb_to_hsv as reference_rgb_to_hsv,
)
from ee_float64_graph_reference import evaluate_float64_graph
from ee_color_curves_test_support import (
    BANDS,
    assert_graph_budget,
    encode,
    find_invocation,
    local,
    nodes,
    offline_only,
    pixels,
    ee,
)
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.image_color import (
    IMAGE_COLOR_FUNCTIONS,
    invoke_image_color,
)
from gee.compat.earthengine.image_color_ir import (
    MAX_COLOR_DOMAIN_PROOFS,
    MAX_SCALAR_INTERNED,
    lookup_rgb_to_hsv_domain,
    number,
    remember_rgb_to_hsv_domain,
)
from gee.compat.earthengine.image_curves import IMAGE_CURVE_FUNCTIONS
from gee.compat.earthengine.ir import Image, Pixel, Source, UnsupportedEEError, const
from gee.ee_translate import compile_expression


def test_sdk_serializes_exact_color_and_curve_signatures(ee):
    assert IMAGE_COLOR_FUNCTIONS == {"Image.rgbToHsv", "Image.hsvToRgb"}
    assert IMAGE_CURVE_FUNCTIONS == {"Image.interpolate", "Image.polynomial"}
    image = ee.Image("scene-a")
    cases = (
        (image.select(["red", "green", "blue"]).rgbToHsv(), "Image.rgbToHsv", {"image"}),
        (image.select(["red", "green", "blue"]).hsvToRgb(), "Image.hsvToRgb", {"image"}),
        (image.interpolate([0, 1], [2, 4]), "Image.interpolate", {"image", "x", "y"}),
        (image.polynomial([1, 2]), "Image.polynomial", {"image", "coefficients"}),
    )
    for expression, function_name, arguments in cases:
        invocation = find_invocation(encode(ee, expression), function_name)
        assert invocation is not None
        assert set(invocation["arguments"]) == arguments
    explicit_default = find_invocation(
        encode(ee, image.interpolate([0, 1], [2, 4], None)), "Image.interpolate",
    )
    assert set(explicit_default["arguments"]) == {"image", "x", "y"}
    assert find_invocation(
        encode(ee, image.interpolate([0, 1], [2, 4], "mask")), "Image.interpolate",
    )["arguments"]["behavior"] == "mask"


@pytest.mark.parametrize(
    ("rgb", "expected"),
    [
        ([1, 0, 0], (0.0, 1.0, 1.0)),
        ([1, 1, 0], (1 / 6, 1.0, 1.0)),
        ([0, 1, 0], (1 / 3, 1.0, 1.0)),
        ([0, 1, 1], (0.5, 1.0, 1.0)),
        ([0, 0, 1], (2 / 3, 1.0, 1.0)),
        ([1, 0, 1], (5 / 6, 1.0, 1.0)),
        ([0.25, 0.25, 0.25], (0.0, 0.0, 0.25)),
        ([0, 0, 0], (0.0, 0.0, 0.0)),
        ([0.75, 0.75, 0.25], (1 / 6, 2 / 3, 0.75)),
        ([5e-324, 0.0, 1.0], (2 / 3, 1.0, 1.0)),
    ],
)
def test_rgb_to_hsv_actual_graph_values_ties_zero_masks_and_range(
        ee, local, rgb, expected):
    # The input API is order based. Synthetic BANDS uses B,G,R, so select the
    # required RGB order explicitly before the color conversion.
    source = ee.Image("scene-a").select(["red", "green", "blue"])
    red, green, blue = ([rgb[index]] for index in range(3))
    result = compile_expression(encode(ee, source.rgbToHsv()), *local)
    assert result["bands"] == ["hue", "saturation", "value"]
    assert result["source_item_ids"] == ["scene-a"]
    assert_graph_budget(result)
    actual, names, timed = evaluate_float64_graph(result, pixels(red, green, blue))
    assert names == ["hue", "saturation", "value"] and not timed
    expected_reference = np.asarray(
        [reference_rgb_to_hsv(tuple(rgb))], dtype=np.float64,
    ).T
    np.testing.assert_allclose(actual, expected_reference, rtol=0, atol=1e-14)
    np.testing.assert_allclose(actual[:, :1], np.asarray(expected)[:, None], rtol=0, atol=1e-14)
    assert np.nanmax(np.abs(actual - expected_reference)) < 1e-14


def test_rgb_to_hsv_masks_out_of_range_and_missing_inputs_without_float_narrowing(ee, local):
    rgb = [
        (0.25, 0.5, 1.0),
        (0.3, 0.2, 0.1),
        (-0.01, 0.2, 0.4),
        (1.01, 0.5, 0.4),
        (0.1, np.nan, 0.4),
    ]
    source = ee.Image("scene-a").select(["red", "green", "blue"]).toDouble()
    result = compile_expression(encode(ee, source.rgbToHsv()), *local)
    assert result["bands"] == ["hue", "saturation", "value"]
    assert nodes(result, "local_ee_integer_values")
    assert nodes(result, "local_ee_to_double")
    assert not nodes(result, "local_ee_to_float")
    actual, _names, _timed = evaluate_float64_graph(
        result,
        pixels([row[0] for row in rgb], [row[1] for row in rgb],
               [row[2] for row in rgb]),
    )
    reference = np.asarray(
        [reference_rgb_to_hsv(tuple(row)) for row in rgb], dtype=np.float64,
    ).T
    np.testing.assert_allclose(actual, reference, rtol=0, atol=1e-14, equal_nan=True)
    assert np.isnan(actual[:, 2:]).all()


def test_hsv_to_rgb_matches_colorsys_and_wraps_hue_one(ee, local):
    hsv = [
        (0.0, 1.0, 1.0), (1 / 6, 1.0, 0.8), (1 / 3, 1.0, 0.6),
        (0.5, 1.0, 1.0), (2 / 3, 1.0, 1.0), (5 / 6, 1.0, 0.7),
        (1.0, 1.0, 1.0), (0.37, 0.0, 0.6), (0.82, 0.3, 0.0),
        (-0.01, 1.0, 1.0), (0.2, 1.01, 0.5), (0.2, 0.5, 1.01),
        (0.2, np.nan, 0.5),
    ]
    source = ee.Image("scene-a").select(["red", "green", "blue"])
    result = compile_expression(encode(ee, source.hsvToRgb()), *local)
    assert result["bands"] == ["red", "green", "blue"]
    assert_graph_budget(result)
    actual, names, _timed = evaluate_float64_graph(
        result, pixels([row[0] for row in hsv], [row[1] for row in hsv],
                       [row[2] for row in hsv]),
    )
    reference = np.asarray(
        [reference_hsv_to_rgb(tuple(row)) for row in hsv], dtype=np.float64,
    ).T
    np.testing.assert_allclose(actual, reference, rtol=0, atol=1e-14, equal_nan=True)
    np.testing.assert_allclose(actual[:, 0], actual[:, 6], rtol=0, atol=0)
    assert np.isnan(actual[:, 9:]).all()
    assert names == ["red", "green", "blue"]


def test_rgb_hsv_roundtrip_composes_within_shared_graph_budgets(ee, local):
    rgb = [
        (1.0, 0.0, 0.0), (0.3, 0.8, 0.1), (0.2, 0.2, 0.2),
        (0.0, 0.0, 0.0), (0.01, 0.5, 0.99), (0.9, 0.4, 0.7),
        (-0.01, 0.2, 0.3), (0.2, 1.01, 0.4), (0.2, np.nan, 0.3),
    ]
    source = ee.Image("scene-a").select(["red", "green", "blue"]).toDouble()
    expression = source.rgbToHsv().hsvToRgb()
    result = compile_expression(encode(ee, expression), *local)
    assert result["bands"] == ["red", "green", "blue"]
    assert_graph_budget(result)
    actual, names, _timed = evaluate_float64_graph(
        result,
        pixels([row[0] for row in rgb], [row[1] for row in rgb],
               [row[2] for row in rgb]),
    )
    expected = np.asarray([
        tuple(float("nan") for _ in range(3))
        if any(not 0 <= channel <= 1 for channel in row)
        else reference_hsv_to_rgb(reference_rgb_to_hsv(row))
        for row in rgb
    ], dtype=np.float64).T
    np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-14, equal_nan=True)
    finite = np.isfinite(expected)
    assert np.max(np.abs(actual[finite] - expected[finite])) < 2e-14
    assert names == ["red", "green", "blue"]


def test_color_scalar_interning_shares_only_identical_child_references_and_stays_bounded():
    translator = Translator([], {}, {})
    source = Source("sentinel-2-l2a", ("scene-a",), ("red",))
    shared = Pixel("band", (source, "red"))
    shared_identity = id(shared)
    first = number(translator, "add", shared, const(1.0))
    repeated = number(translator, "add", shared, const(1.0))
    del shared
    held_operand = next(
        operand for operands, _pixel in translator._image_color_scalar_cache.values()
        for operand in operands if id(operand) == shared_identity
    )
    assert id(held_operand) == shared_identity
    fresh = Pixel("band", (source, "red"))
    assert id(fresh) != shared_identity
    distinct = number(translator, "add", fresh, const(1.0))
    assert first is repeated
    assert distinct is not first
    cache = translator._image_color_scalar_cache
    assert len(cache) <= MAX_SCALAR_INTERNED
    assert held_operand is not fresh


def test_color_scalar_intern_cache_never_exceeds_its_fixed_bound():
    translator = Translator([], {}, {})
    for index in range(MAX_SCALAR_INTERNED + 17):
        number(
            translator, "add", const(float(index)), const(1.0),
        )
    assert len(translator._image_color_scalar_cache) == MAX_SCALAR_INTERNED


def test_color_scalar_cache_precharges_before_allocation_near_work_limit():
    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        number(translator, "add", Pixel("band", (object(), "red")), const(1.0))
    assert not hasattr(translator, "_image_color_scalar_cache")


def test_rgb_hsv_domain_proof_is_bounded_strong_and_order_sensitive():
    translator = Translator([], {}, {})
    source = Source("sentinel-2-l2a", ("scene-a",), ("red", "green", "blue"))
    outputs = tuple(Pixel("band", (source, name)) for name in source.names)
    output_identities = tuple(map(id, outputs))
    condition = Pixel("greater_than", (outputs[0], const(0.0)), True)
    remember_rgb_to_hsv_domain(translator, outputs, condition)
    del outputs
    retained, retained_condition = translator._image_color_domain_proofs[0]
    assert tuple(map(id, retained)) == output_identities
    assert lookup_rgb_to_hsv_domain(translator, retained) is retained_condition
    assert retained_condition is condition
    assert lookup_rgb_to_hsv_domain(translator, tuple(reversed(retained))) is None

    for index in range(MAX_COLOR_DOMAIN_PROOFS + 3):
        values = tuple(
            Pixel("band", (source, f"{index}-{slot}")) for slot in range(3)
        )
        remember_rgb_to_hsv_domain(translator, values, condition)
    assert len(translator._image_color_domain_proofs) == MAX_COLOR_DOMAIN_PROOFS


def test_rgb_hsv_domain_proof_precharges_before_cache_allocation():
    translator = Translator([], {}, {})
    translator.steps = 49_999
    values = tuple(Pixel("band", (object(), str(index))) for index in range(3))
    condition = Pixel("constant", (True,), True)
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        remember_rgb_to_hsv_domain(translator, values, condition)
    assert not hasattr(translator, "_image_color_domain_proofs")


def test_color_domain_and_source_lineage_fail_closed(ee, local):
    source = ee.Image("scene-a")
    for selected in (["red", "green"], ["red", "green", "blue", "nir"]):
        with pytest.raises(UnsupportedEEError, match="exactly 3 input bands"):
            compile_expression(encode(ee, source.select(selected).rgbToHsv()), *local)

    mixed = source.select("red").addBands(
        ee.Image("scene-b").select("green"),
    ).addBands(source.select("blue"))
    with pytest.raises(UnsupportedEEError, match="common pixel grid|same ordered source"):
        compile_expression(encode(ee, mixed.rgbToHsv()), *local)


def test_unknown_arguments_and_invalid_color_band_shapes_are_rejected():
    translator = Translator([], {}, {})
    image = Image([(name, const(index)) for index, name in enumerate(BANDS[:3])], {})
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_image_color(
            translator, "Image.rgbToHsv", {"image": image, "unexpected": 1},
        )
    with pytest.raises(UnsupportedEEError, match="requires exactly 3 input bands"):
        invoke_image_color(
            translator, "Image.hsvToRgb", {"image": Image([], {})},
        )
