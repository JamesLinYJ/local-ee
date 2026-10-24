"""Official addBands parameters, source identity and bounded merging."""
from __future__ import annotations

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, const
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


@pytest.fixture
def context():
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path="vendor/earthengine-js/algorithms.json",
        )
        metadata, items, _ = synthetic_inputs()
        yield ee, [metadata], items
    assert guard.evidence()["attempt_count"] == 0


def decode(context, value):
    ee, catalog, items = context
    translator = Translator(catalog, items, {})
    return translator.evaluate(ee.serializer.encode(value, for_cloud_api=False))


@pytest.mark.parametrize("overwrite", ["false", "true", 0, 1, [], {}])
def test_non_boolean_overwrite_is_not_coerced(context, overwrite):
    ee, _, _ = context
    image = ee.Image("scene-a").select("red")
    with pytest.raises(UnsupportedEEError, match="overwrite must be a boolean"):
        decode(context, image.addBands(image, overwrite=overwrite))


@pytest.mark.parametrize("overwrite,expected", [
    (None, ["red", "nir", "red_1"]),
    (False, ["red", "nir", "red_1"]), (True, ["red", "nir"]),
])
def test_default_suffix_and_overwrite_keep_existing_band_order(context, overwrite, expected):
    ee, _, _ = context
    image = ee.Image("scene-a").select(["red", "nir"]).set("title", "first")
    extra = image.select("red").multiply(2).set("title", "second")
    result = decode(context, image.addBands(extra, overwrite=overwrite))
    assert [name for name, _ in result.bands] == expected
    assert result.props["title"] == "first"
    if overwrite:
        assert result.bands[0][1] == decode(context, extra).bands[0][1]


def test_empty_names_cannot_supply_a_source_or_make_global_constant_exportable(context):
    ee, catalog, items = context
    image = ee.Image(7).set("title", "constant")
    value = image.addBands(ee.Image("scene-a"), names=[])
    result = decode(context, value)
    assert result.source is None
    assert [name for name, _ in result.bands] == ["constant"]
    assert result.props["title"] == "constant"
    with pytest.raises(UnsupportedEEError):
        compile_expression(ee.serializer.encode(value, for_cloud_api=False), catalog, items)


def test_suffix_search_respects_existing_names_and_order():
    translator = Translator([], {}, {})
    left = Image([(name, const(index)) for index, name in enumerate(["x", "x_1", "x_3"])], {})
    right = Image([("x", const(7)), ("x_1", const(8))], {})
    result = translator.invoke("Image.addBands", {"dstImg": left, "srcImg": right})
    assert [name for name, _ in result.bands] == ["x", "x_1", "x_3", "x_2", "x_1_1"]
    assert [name for name, _ in left.bands] == ["x", "x_1", "x_3"]


def test_large_merge_and_collisions_consume_the_shared_budget():
    translator = Translator([], {}, {})
    bands = [(f"b{index}", const(index)) for index in range(100)]
    image = Image(bands, {"title": "first"})
    result = translator.invoke("Image.addBands", {"dstImg": image, "srcImg": image})
    assert len(result.bands) == 200
    assert [name for name, _ in result.bands[100:]] == [f"b{index}_1" for index in range(100)]
    assert translator.steps > 1000
    result.props["title"] = "changed"
    assert image.props == {"title": "first"}


def test_exhausted_budget_rejects_before_mutating_inputs():
    translator = Translator([], {}, {})
    translator.steps = 49_999
    image = Image([("x", const(1))], {})
    with pytest.raises(UnsupportedEEError, match="compilation work budget"):
        translator.invoke("Image.addBands", {"dstImg": image, "srcImg": image})
    assert translator.steps == 49_999
    assert image.bands == [("x", const(1))]


def test_oversize_band_input_rejects_before_scanning():
    translator = Translator([], {}, {})
    image = Image([(str(index), const(index)) for index in range(10_001)], {})
    with pytest.raises(UnsupportedEEError, match="at most10000"):
        translator.invoke("Image.addBands", {"dstImg": image, "srcImg": image})
    assert translator.steps == 0
