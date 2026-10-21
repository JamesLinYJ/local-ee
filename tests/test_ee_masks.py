"""Image.unmask's band, pixel-mask and geometry contracts."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import box, shape

from gee.compat.earthengine.ir import Image, Pixel, Source, UnsupportedEEError
from gee.ee_masks import SUPPORTED_MASK_FUNCTIONS, invoke_mask


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-mask-1.7.49.json"
BIG = 16_777_219  # distinguishable from its Float32 rounding at 2**24


def rect(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


class TranslatorStub:
    def __init__(self, items=None, options=None):
        self.items = items or {}
        self.options = options or {}
        self.warnings = []

    @staticmethod
    def allowed(args, names):
        unknown = set(args) - names
        if unknown:
            raise UnsupportedEEError(f"Unsupported algorithm arguments: {sorted(unknown)}")

    def warn(self, message):
        self.warnings.append(message)

    def footprint(self, image):
        if image.footprint is not None and image.footprint_is_absolute:
            return image.footprint
        if image.source is None:
            raise UnsupportedEEError("Image geometry requires a source footprint")
        base = shape(self.items[image.source.cid][image.source.ids[0]]["geometry"])
        if image.footprint is not None:
            base = base.intersection(shape(image.footprint))
        return __import__("shapely.geometry", fromlist=["mapping"]).mapping(base)


def source_image(name="data", geometry=None, bands=("red", "nir"), footprint=None):
    geometry = geometry or rect(0, 0, 2, 1)
    source = Source("local", (name,), tuple(bands))
    values = [(band, Pixel("band", (source, band))) for band in bands]
    image = Image(values, {"system:index": name, "custom": "kept"}, source,
                  inherit_props=False, copied_props=("system:index",),
                  footprint=footprint, footprint_is_absolute=footprint is not None)
    return image, source, {"local": {name: {"geometry": geometry}}}


def independent_unmask(data, data_footprint, fill, fill_footprint, same_footprint,
                       request_region=None):
    """Independent NumPy model; masks and footprints are separate inputs."""
    data = np.asarray(data, dtype=np.float64)
    fill = np.broadcast_to(np.asarray(fill, dtype=np.float64), data.shape)
    data_footprint = np.broadcast_to(np.asarray(data_footprint, dtype=bool), data.shape)
    fill_footprint = np.broadcast_to(np.asarray(fill_footprint, dtype=bool), data.shape)
    footprint = data_footprint if same_footprint else data_footprint | fill_footprint
    valid_data = data_footprint & np.isfinite(data)
    valid_fill = fill_footprint & np.isfinite(fill)
    result = np.where(valid_data, data, np.where(valid_fill, fill, np.nan))
    if request_region is not None:
        footprint = footprint & np.broadcast_to(np.asarray(request_region, dtype=bool), data.shape)
    result = np.where(footprint, result, np.nan)
    return result, footprint


def _final_invocation(value):
    if value.get("type") == "CompoundValue":
        scope = dict(value["scope"])
        return scope[value["value"]["value"]]
    return value


def _invocations(value):
    if isinstance(value, dict):
        if value.get("type") == "Invocation":
            yield value
        for child in value.values():
            yield from _invocations(child)
    elif isinstance(value, list):
        for child in value:
            yield from _invocations(child)


def test_sdk_fixture_is_pinned_offline_and_exercises_unmask_overloads():
    fixture = json.loads(FIXTURE.read_text())
    assert fixture["sdk"] == "1.7.49"
    assert fixture["source_commit"] == "e189e4b89e785019ea5642ea8e80cb644749cd4a"
    expected = {
        "defaultValue", "numericValue", "oneBandBroadcast", "twoBandOrder",
        "maskedReplacement", "sameFootprintFalse", "sameFootprintFalseDefaultValue",
    }
    assert set(fixture["expressions"]) == expected
    for expression in fixture["expressions"].values():
        invocation = _final_invocation(expression)
        assert invocation["functionName"] == "Image.unmask"
    default = _final_invocation(fixture["expressions"]["defaultValue"])["arguments"]
    assert set(default) == {"input"}  # the SDK omits value and sameFootprint defaults
    false_default = _final_invocation(fixture["expressions"]["sameFootprintFalseDefaultValue"])["arguments"]
    assert false_default["sameFootprint"] is False and "value" not in false_default

    raster_expected = {
        "unmaskZero", "unmaskLarge", "unmaskRaster", "unmaskClipped",
        "unmaskDouble", "unmaskMappedMean",
    }
    assert set(fixture["raster_expressions"]) == raster_expected
    for name, expression in fixture["raster_expressions"].items():
        expected_final = "reduce.mean" if name == "unmaskMappedMean" else "Image.unmask"
        assert _final_invocation(expression)["functionName"] == expected_final
        invocations = list(_invocations(expression))
        if name == "unmaskMappedMean":
            assert any(x["functionName"] == "Collection.map" for x in invocations)
            assert any(x["functionName"] == "Image.toFloat" for x in invocations)
            continue
        assert any(x["functionName"] == "DateRange" for x in invocations)
        assert any(x["functionName"] == "Filter.dateRangeContains" for x in invocations)
        assert any(x["functionName"] == "Collection.filter" for x in invocations)
        assert any(x["functionName"] == "Collection.first" for x in invocations)
        assert any(x["functionName"] == "ImageCollection.load"
                   and x["arguments"].get("id") == "sentinel-2-l2a" for x in invocations)
    double_ops = [x["functionName"] for x in _invocations(fixture["raster_expressions"]["unmaskDouble"])]
    assert "Image.toDouble" in double_ops
    clipped_ops = [x["functionName"] for x in _invocations(fixture["raster_expressions"]["unmaskClipped"])]
    assert "Image.clip" in clipped_ops


def test_fixture_generator_cannot_call_earth_engine_service():
    source = (ROOT / "scripts/ee_mask_fixtures.cjs").read_text()
    assert "ee.data.computeValue = () => { throw Error" in source
    assert "http://localhost/disabled" in source
    assert "vendor/earthengine-js" in source


def test_default_zero_and_large_scalar_use_exact_unmask_constant_ir():
    image, _, items = source_image()
    translator = TranslatorStub(items)
    default = invoke_mask(translator, "Image.unmask", {"input": image})
    assert [name for name, _ in default.bands] == ["red", "nir"]
    assert all(pixel.op == "clip" and pixel.args[0].op == "unmask_constant"
               and pixel.args[0].args[1] == 0 for _, pixel in default.bands)
    assert default.footprint is image.footprint
    assert default.props == image.props and default.source is image.source
    assert (default.inherit_props, default.copied_props) == (image.inherit_props, image.copied_props)

    large = invoke_mask(translator, "Image.unmask", {"input": image, "value": BIG})
    values = [pixel.args[0].args[1] for _, pixel in large.bands]
    assert values == [BIG, BIG]
    assert all(type(value) is int for value in values)
    assert np.float32(BIG).item() != float(BIG)


def test_value_band_broadcast_and_equal_count_are_matched_by_order():
    image, _, items = source_image()
    translator = TranslatorStub(items)
    broadcast = invoke_mask(translator, "Image.unmask", {"input": image, "value": 9})
    assert [pixel.args[0].args[1] for _, pixel in broadcast.bands] == [9, 9]

    value = Image([("nir", Pixel("constant", (101,))),
                   ("red", Pixel("constant", (202,)))], {})
    ordered = invoke_mask(translator, "Image.unmask", {"input": image, "value": value})
    assert [name for name, _ in ordered.bands] == ["red", "nir"]
    assert [pixel.args[0].args[1] for _, pixel in ordered.bands] == [101, 202]

    replacement = Image([("fill", Pixel("band", (image.source, "red")))], {})
    broadcast_image = invoke_mask(translator, "Image.unmask", {"input": image, "value": replacement})
    assert [pixel.args[0].op for _, pixel in broadcast_image.bands] == ["unmask", "unmask"]
    assert all(pixel.args[0].args[1] == replacement.bands[0][1]
               for _, pixel in broadcast_image.bands)
    assert all(pixel.args[0].args[2] is True for _, pixel in broadcast_image.bands)


def test_same_footprint_preserves_clipped_geometry_and_pixel_fill_does_not_expand_it():
    clipped = rect(0, 0, 1, 1)
    image, _, items = source_image(footprint=clipped)
    result = invoke_mask(TranslatorStub(items), "Image.unmask", {"input": image, "value": 7})
    assert result.footprint == clipped and result.footprint_is_absolute
    assert all(pixel.op == "clip" and pixel.args[1] == clipped for _, pixel in result.bands)

    # Fill values are valid even where source pixels are masked; the separate
    # output footprint still prevents pixels outside the input clip appearing.
    actual, valid = independent_unmask(
        [0, np.nan, np.nan, 12, np.nan], [1, 1, 1, 0, 0], BIG,
        [1, 1, 1, 1, 1], True,
    )
    np.testing.assert_equal(actual, [0, BIG, BIG, np.nan, np.nan])
    np.testing.assert_equal(valid, [True, True, True, False, False])


def test_same_footprint_false_unions_source_geometries_but_keeps_clip_mask_distinct():
    clipped = rect(0, 0, 1, 1)
    image, _, items = source_image(footprint=clipped)
    fill_geometry = rect(2, 0, 3, 1)
    fill, fill_source, fill_items = source_image("fill", fill_geometry, ("other",))
    items["local"].update(fill_items["local"])
    translator = TranslatorStub(items)
    result = invoke_mask(translator, "Image.unmask", {
        "input": image, "value": fill, "sameFootprint": False,
    })
    assert result.footprint_is_absolute
    geometry = shape(result.footprint)
    assert geometry.bounds == (0.0, 0.0, 3.0, 1.0)
    assert geometry.area == pytest.approx(2.0)
    assert result.props == image.props and result.source is image.source
    outer_clip = result.bands[0][1]
    assert outer_clip.op == "clip" and outer_clip.args[1] == result.footprint
    assert outer_clip.args[0].op == "unmask"
    assert outer_clip.args[0].args[1].op == "clip"
    assert outer_clip.args[0].args[1].args[0] == fill.bands[0][1]
    assert outer_clip.args[0].args[2] is False

    data = [1, np.nan, np.nan, np.nan]
    data_footprint = [1, 1, 1, 0]
    fill_data = [7, np.nan, 99, 12]
    fill_footprint = [1, 1, 0, 1]
    same, same_valid = independent_unmask(data, data_footprint, fill_data, fill_footprint, True)
    union, union_valid = independent_unmask(data, data_footprint, fill_data, fill_footprint, False)
    np.testing.assert_equal(same, [1, np.nan, np.nan, np.nan])
    np.testing.assert_equal(same_valid, [True, True, True, False])
    np.testing.assert_equal(union, [1, np.nan, np.nan, 12])
    np.testing.assert_equal(union_valid, [True, True, True, True])


def test_global_constant_false_is_rejected_even_with_finite_request_region():
    image, _, items = source_image()
    translator = TranslatorStub(items, {"region": rect(0, 0, 2, 1), "scale": 10, "crs": "EPSG:32649"})
    with pytest.raises(UnsupportedEEError, match="global footprint is not supported"):
        invoke_mask(translator, "Image.unmask", {"input": image, "sameFootprint": False})
    assert translator.warnings == []

    with pytest.raises(UnsupportedEEError, match="global footprint is not supported"):
        invoke_mask(TranslatorStub(items), "Image.unmask", {
            "input": image, "value": 1, "sameFootprint": False,
        })

    constants = Image([("x", Pixel("constant", (1,)))], {})
    with pytest.raises(UnsupportedEEError, match="local raster grid"):
        invoke_mask(translator, "Image.unmask", {"input": constants, "sameFootprint": False})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_replacement_constants_fail(bad):
    image, _, items = source_image()
    with pytest.raises(UnsupportedEEError, match="must be finite"):
        invoke_mask(TranslatorStub(items), "Image.unmask", {"input": image, "value": bad})


@pytest.mark.parametrize("bad", [2**53 + 1, -(2**53 + 1), 10**400])
def test_integer_replacement_outside_exact_float64_range_fails_before_rounding(bad):
    image, _, items = source_image()
    with pytest.raises(UnsupportedEEError, match="exceeds exact Float64 precision"):
        invoke_mask(TranslatorStub(items), "Image.unmask", {"input": image, "value": bad})


def test_non_finite_or_inexact_literals_in_replacement_image_fail():
    image, _, items = source_image()
    for bad, message in [
        (float("nan"), "must be finite"),
        (2**53 + 1, "exceeds exact Float64 precision"),
    ]:
        replacement = Image([("fill", Pixel("add", (
            Pixel("band", (image.source, "red")), Pixel("constant", (bad,)),
        )))], {})
        with pytest.raises(UnsupportedEEError, match=message):
            invoke_mask(TranslatorStub(items), "Image.unmask", {
                "input": image, "value": replacement,
            })


@pytest.mark.parametrize("value", [2**53, -(2**53)])
def test_exact_float64_integer_boundary_is_preserved(value):
    image, _, items = source_image()
    result = invoke_mask(TranslatorStub(items), "Image.unmask", {"input": image, "value": value})
    assert all(pixel.args[0].args[1] == value for _, pixel in result.bands)


def test_clip_after_unmask_intersects_union_footprint_and_requested_pixels():
    input_geometry, replacement_geometry = box(0, 0, 2, 1), box(2, 0, 3, 1)
    union_geometry = input_geometry.union(replacement_geometry)
    after_clip = box(1, 0, 2.5, 1)
    actual = union_geometry.intersection(after_clip)
    assert actual.bounds == (1.0, 0.0, 2.5, 1.0)
    assert actual.area == pytest.approx(1.5)

    # The request clip is applied after filling, so a valid outside replacement
    # is retained only where both the union and the later clip cover the cell.
    values, valid = independent_unmask(
        [3, np.nan, np.nan, np.nan], [1, 1, 0, 0], [8, 8, 8, 8],
        [0, 0, 1, 1], False, request_region=[0, 1, 1, 0],
    )
    np.testing.assert_equal(values, [np.nan, np.nan, 8, np.nan])
    np.testing.assert_equal(valid, [False, True, True, False])


@pytest.mark.parametrize("bad", [0, 1, "false", [], {}])
def test_same_footprint_requires_boolean(bad):
    image, _, items = source_image()
    with pytest.raises(UnsupportedEEError, match="must be a boolean"):
        invoke_mask(TranslatorStub(items), "Image.unmask", {
            "input": image, "sameFootprint": bad,
        })


def test_empty_or_incompatible_bands_and_unknown_arguments_fail_closed():
    image, _, items = source_image()
    translator = TranslatorStub(items)
    with pytest.raises(UnsupportedEEError, match="requires input"):
        invoke_mask(translator, "Image.unmask", {})
    with pytest.raises(UnsupportedEEError, match="same band count"):
        invoke_mask(translator, "Image.unmask", {
            "input": image, "value": [1, 2, 3],
        })
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_mask(translator, "Image.unmask", {"input": image, "ignored": True})
    with pytest.raises(UnsupportedEEError, match="Unsupported Earth Engine mask"):
        invoke_mask(translator, "Image.updateMask", {})
    assert SUPPORTED_MASK_FUNCTIONS == frozenset({"Image.unmask"})
