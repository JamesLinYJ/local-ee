"""Strict argmax input contracts, exact bounds, and preflight controls."""
from copy import deepcopy

import numpy as np
import pytest

import gee.compat.earthengine.array_argmax as argmax_module
from gee.compat.earthengine.array_core import MAX_ARRAY_WORK, StaticArray
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, Source, const
from gee.compat.earthengine.raster_array_core import RasterArrayImage, wrap_array_image
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_argmax import flat_invocation
from test_ee_raster_array_accumulation import (
    ARRAY_BANDS, compile_raster, compile_value, ee, encode, first_image, local,
    source_array,
)


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


def static_compile(ee, value):
    return compile_value(ee, value, {"catalog": [], "items": {}})


def test_sdk_static_argmax_accepts_10000_cells_and_rejects_rank_or_cell_overflow(ee):
    values = list(range(10_000))
    assert static_compile(ee, ee.Array(values).argmax())["value"] == [9_999]

    nested_rank_nine = 1
    for _ in range(9):
        nested_rank_nine = [nested_rank_nine]
    with pytest.raises(UnsupportedEEError, match="rank exceeds 8"):
        static_compile(ee, ee.Array(nested_rank_nine).argmax())

    with pytest.raises(UnsupportedEEError, match="10000"):
        static_compile(ee, ee.Array(list(range(10_001))).argmax())


def test_static_argmax_rejects_inexact_integers_nonfinite_and_raw_lists(ee):
    with pytest.raises(UnsupportedEEError, match="exact Float64"):
        static_compile(ee, ee.Array([2**53 + 1]).argmax())
    for values in ([1.0, float("nan")], [float("inf"), 1.0]):
        with pytest.raises(UnsupportedEEError, match="finite"):
            static_compile(ee, ee.Array(values).argmax())

    # A Python list in an Array.argmax wire argument is still a list; only an
    # explicit typed ee.Array is a legal static array input.
    raw = {"type": "Invocation", "functionName": "Array.argmax",
           "arguments": {"array": [2, 9, 4]}}
    with pytest.raises(UnsupportedEEError, match="typed static ee.Array"):
        compile_expression(raw, [], {})


def test_sdk_array_argmax_requires_only_its_pinned_array_argument(ee):
    expression = deepcopy(encode(ee, ee.Array([1, 2]).argmax()))
    invocation = flat_invocation(expression, "Array.argmax")
    assert invocation is not None and set(invocation["arguments"]) == {"array"}

    missing = deepcopy(expression)
    flat_invocation(missing, "Array.argmax")["arguments"].pop("array")
    with pytest.raises(UnsupportedEEError, match="Array.argmax requires array"):
        compile_expression(missing, [], {})

    unknown = deepcopy(expression)
    flat_invocation(unknown, "Array.argmax")["arguments"]["ignored"] = 1
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(unknown, [], {})


def test_static_argmax_preserves_decoded_array_dtype_and_readonly_values(ee):
    expression = encode(ee, ee.Array([[2.0, 8.0], [8.0, 1.0]]))
    value = Translator([], {}, {}).evaluate(expression)
    assert isinstance(value, StaticArray)
    before = value.data.copy()
    dtype = value.data.dtype
    assert value.data.flags.writeable is False

    result = argmax_module.invoke_static_argmax(
        Translator([], {}, None), "Array.argmax", {"array": value},
    )
    assert result == [0, 1]
    assert value.data.dtype == dtype
    assert value.data.flags.writeable is False
    np.testing.assert_array_equal(value.data, before)


def test_argmax_handlers_reject_non_dictionary_raw_arguments():
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="arguments must be a dictionary"):
        argmax_module.invoke_static_argmax(translator, "Array.argmax", None)
    with pytest.raises(UnsupportedEEError, match="arguments must be a dictionary"):
        argmax_module.invoke_raster_argmax(translator, "Image.arrayArgmax", [])


def test_sdk_raster_array_argmax_requires_its_pinned_image_argument(ee, local):
    source = source_array(ee, first_image(ee), ARRAY_BANDS[:2], (2,), "pair")
    flattened = source.arrayArgmax().arrayFlatten([["index"]])
    expression = encode(ee, flattened)
    invocation = flat_invocation(expression, "Image.arrayArgmax")
    assert invocation is not None and set(invocation["arguments"]) == {"image"}

    missing = deepcopy(expression)
    flat_invocation(missing, "Image.arrayArgmax")["arguments"].pop("image")
    with pytest.raises(UnsupportedEEError, match="Image.arrayArgmax requires image"):
        compile_expression(missing, local["catalog"], local["items"])

    unknown = deepcopy(expression)
    flat_invocation(unknown, "Image.arrayArgmax")["arguments"]["unused"] = True
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(unknown, local["catalog"], local["items"])


def test_raster_argmax_requires_float32_single_array_not_double_or_bundle(ee, local):
    image = first_image(ee).select(ARRAY_BANDS[:2])
    uncast = image.toArray().arrayArgmax().arrayFlatten([["index"]])
    with pytest.raises(UnsupportedEEError, match="explicit top-level toFloat"):
        compile_value(ee, uncast, local)

    double = image.toArray().toDouble().arrayArgmax().arrayFlatten([["index"]])
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, double, local)

    bundle = (ee.ImageCollection("sentinel-2-l2a").select(ARRAY_BANDS[:2])
              .toArrayPerBand().arrayArgmax())
    with pytest.raises(UnsupportedEEError, match="array bundle"):
        compile_value(ee, bundle, local)

    raw_list = {"type": "Invocation", "functionName": "Image.arrayArgmax",
                "arguments": {"image": [1, 2]}}
    with pytest.raises(UnsupportedEEError, match="RasterArrayImage"):
        compile_expression(raw_list, local["catalog"], local["items"])


def test_raster_argmax_rejects_rank_zero_and_accepts_rank_eight(ee, local):
    rank_zero = ee.Image.constant(ee.Array(4)).toFloat().arrayArgmax()
    with pytest.raises(UnsupportedEEError, match="rank-1..8"):
        compile_value(ee, rank_zero, local)

    singleton = source_array(ee, first_image(ee), [ARRAY_BANDS[0]], (1,) * 8, "eight")
    flattened = singleton.arrayArgmax().arrayFlatten([[
        f"axis_{axis}" for axis in range(8)
    ]])
    result, actual, names = compile_raster(ee, flattened, local)
    assert names == result["bands"] == [f"axis_{axis}" for axis in range(8)]
    np.testing.assert_array_equal(actual[:, :4], np.zeros((8, 4)))
    assert result["source_item_ids"] == ["accum-scene"]


def test_raster_argmax_64_cell_boundary_returns_exact_float32_coordinate(ee, local):
    # Sixty-three literal cells plus one raster cell exercise the legal 64-cell
    # shape without building a dense 64-band graph that exceeds the shared cap.
    local["arrays"]["accum-scene"][ARRAY_BANDS[63]][:4] = [100.0, -1.0, np.nan, 0.0]
    literal = ee.Image.constant(ee.Array([0.0] * 63)).toFloat().set("argmax_tag", "literal-left")
    dynamic = source_array(ee, first_image(ee), [ARRAY_BANDS[63]], (1,), "dynamic")
    value = literal.arrayCat(dynamic, 0)
    result, actual, names = compile_raster(
        ee, value.arrayArgmax().arrayFlatten([["index"]]), local,
    )
    assert names == result["bands"] == ["index"]
    assert result["properties"]["argmax_tag"] == "literal-left"
    assert result["source_item_ids"] == ["accum-scene"]
    np.testing.assert_allclose(
        actual[0], [63.0, 0.0, np.nan, 0.0, np.nan], equal_nan=True,
    )
    assert all(float(value).is_integer() for value in actual[0, :2])


def test_raster_argmax_shape_limits_reject_rank_nine_and_more_than_64_cells():
    source = Source("sentinel-2-l2a", ("sample",), ("v00",))
    image = Image([], {}, source)
    cells = tuple(Pixel("to_float", (const(float(index)),)) for index in range(65))
    too_wide = RasterArrayImage(image, (65,), cells, const(True), "array")
    with pytest.raises(UnsupportedEEError, match="64"):
        Translator([], {}, {}).invoke("Image.arrayArgmax", {"image": too_wide})

    rank_nine = RasterArrayImage(
        image, (1,) * 9, (Pixel("to_float", (const(1.0),)),), const(True), "array",
    )
    with pytest.raises(UnsupportedEEError, match="rank exceeds 8"):
        Translator([], {}, {}).invoke("Image.arrayArgmax", {"image": rank_nine})


def test_static_argmax_precharges_before_reading_values(monkeypatch):
    class NoScan:
        ndim = 1
        size = 2
        dtype = np.dtype(np.float64)

        @property
        def flat(self):
            raise AssertionError("Static Array scanned before work preflight")

    monkeypatch.setattr(argmax_module, "require_array", lambda value: NoScan())
    translator = Translator([], {}, None)
    translator.steps = MAX_ARRAY_WORK
    with pytest.raises(UnsupportedEEError, match="work budget"):
        argmax_module.invoke_static_argmax(
            translator, "Array.argmax", {"array": StaticArray(np.asarray([1.0, 2.0]))},
        )
    assert translator.steps == MAX_ARRAY_WORK


def test_raster_argmax_precharges_before_cell_scan_and_output_wrapper(monkeypatch):
    class NoScanTuple(tuple):
        def __iter__(self):
            raise AssertionError("Raster cells scanned before work preflight")

    image = Image([], {"tag": "preflight"}, Source("sentinel-2-l2a", ("sample",), ("v00",)))
    pixel = Pixel("to_float", (const(1.0),))
    array = RasterArrayImage(image, (2,), NoScanTuple((pixel, pixel)), const(True), "array")

    def no_wrap(*args, **kwargs):
        raise AssertionError("Raster output wrapper ran before work preflight")

    monkeypatch.setattr(argmax_module, "wrap_array_image", no_wrap)
    translator = Translator([], {}, None)
    translator.steps = MAX_ARRAY_WORK
    with pytest.raises(UnsupportedEEError, match="work budget"):
        argmax_module.invoke_raster_argmax(
            translator, "Image.arrayArgmax", {"image": array},
        )
    assert translator.steps == MAX_ARRAY_WORK


def test_dense_dynamic_64_cell_array_argmax_respects_500_node_cap(ee, local):
    source = source_array(ee, first_image(ee), ARRAY_BANDS[:64], (64,), "wide")
    output = source.arrayArgmax().arrayFlatten([["index"]])
    with pytest.raises(UnsupportedEEError, match="500"):
        compile_raster(ee, output, local)
