"""Strict arguments, shape limits, reducers and work preflight."""
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine import raster_array_accumulation as accumulation
from gee.compat.earthengine import raster_matrix_properties as matrix_properties
from gee.compat.earthengine.array_core import MAX_ARRAY_WORK
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, const
from gee.compat.earthengine.raster_array_core import RasterArrayImage, wrap_array_image
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_raster_array_accumulation import (
    ARRAY_BANDS,
    compile_raster,
    compile_value,
    encode,
    find_invocation,
    first_image,
    local,
    matrix_labels,
    source_array,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    from gee.ee_python_client import configure_local_ee

    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def compile_raw(value, local):
    return compile_expression(value, local["catalog"], local["items"])


@pytest.mark.parametrize("algorithm,expression,required", [
    ("Image.arrayAccum", "accum", {"input", "axis"}),
    ("Image.matrixFnorm", "norm", {"value"}),
])
def test_sdk_required_arguments_and_unknown_argument_rejection(ee, local, algorithm,
                                                               expression, required):
    image = first_image(ee)
    if expression == "accum":
        value = source_array(ee, image, ARRAY_BANDS[:6], (2, 3)).arrayAccum(1)
        value = value.arrayFlatten(matrix_labels((2, 3)))
    else:
        value = source_array(ee, image, ARRAY_BANDS[:4], (2, 2)).matrixFnorm()

    encoded = encode(ee, value)
    call = find_invocation(encoded, algorithm)
    assert call is not None
    assert set(call["arguments"]) == required

    missing = encode(ee, value)
    call = find_invocation(missing, algorithm)
    call["arguments"].pop("axis" if algorithm == "Image.arrayAccum" else "value")
    with pytest.raises(UnsupportedEEError):
        compile_raw(missing, local)

    unknown = encode(ee, value)
    find_invocation(unknown, algorithm)["arguments"]["ignored"] = 1
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_raw(unknown, local)


def test_array_accum_requires_typed_raster_array_and_top_level_float32(ee, local):
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, ee.Image.constant(1).arrayAccum(0), local)
    raw = {
        "type": "Invocation", "functionName": "Image.arrayAccum",
        "arguments": {"input": [[1, 2]], "axis": 0},
    }
    with pytest.raises(UnsupportedEEError):
        compile_raw(raw, local)

    uncast = first_image(ee).select(ARRAY_BANDS[:3]).toArray()
    uncast = uncast.arrayReshape(ee.Image.constant(ee.Array([3])), 1)
    with pytest.raises(UnsupportedEEError, match="explicit top-level toFloat"):
        compile_value(ee, uncast.arrayAccum(0), local)

    with pytest.raises(UnsupportedEEError):
        compile_value(ee, uncast.toDouble().arrayAccum(0), local)


@pytest.mark.parametrize("axis", [True, -1, 1.5, 2])
def test_array_accum_rejects_invalid_axis_values(ee, local, axis):
    source = source_array(ee, first_image(ee), ARRAY_BANDS[:6], (2, 3))
    flattened = source.arrayAccum(axis).arrayFlatten(matrix_labels((2, 3)))
    with pytest.raises(UnsupportedEEError, match="axis|integer"):
        compile_value(ee, flattened, local)


def test_array_accum_accepts_integral_float_axis_and_rank_one_input(ee, local):
    source = source_array(ee, first_image(ee), ARRAY_BANDS[:3], (3,), "rank_one")
    expression = source.arrayAccum(0.0).arrayFlatten([["a", "b", "c"]])
    result, actual, names = compile_raster(ee, expression, local)
    assert names == result["bands"] == ["a", "b", "c"]
    raw = np.stack([
        local["arrays"]["accum-scene"][band] for band in ARRAY_BANDS[:3]
    ], axis=1).astype(np.float32)
    expected = np.add.accumulate(raw, axis=1, dtype=np.float32).T.astype(np.float64)
    expected[:, 4] = np.nan
    np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize("reducer", ["mean", "count", "unweighted"])
def test_array_accum_rejects_unsupported_or_unweighted_reducers(ee, local, reducer):
    source = source_array(ee, first_image(ee), ARRAY_BANDS[:3], (3,))
    if reducer == "unweighted":
        value = source.arrayAccum(0, ee.Reducer.sum().unweighted())
        with pytest.raises(UnsupportedEEError):
            compile_value(ee, value.arrayFlatten([["a", "b", "c"]]), local)
    else:
        value = source.arrayAccum(0, getattr(ee.Reducer, reducer)())
        with pytest.raises(UnsupportedEEError, match="SUM, MIN, or MAX"):
            compile_value(ee, value.arrayFlatten([["a", "b", "c"]]), local)


def test_array_accum_rejects_missing_axis_and_unrecognized_raw_arguments(local):
    for arguments in (
        {"input": []},
        {"axis": 0},
        {"input": [], "axis": 0, "extra": True},
    ):
        with pytest.raises(UnsupportedEEError):
            compile_raw({"type": "Invocation", "functionName": "Image.arrayAccum",
                         "arguments": arguments}, local)


@pytest.mark.parametrize("kind", ["rank1", "rank3", "ordinary", "raw-list"])
def test_matrix_fnorm_requires_rank_two_typed_array(ee, local, kind):
    image = first_image(ee)
    if kind == "rank1":
        value = source_array(ee, image, ARRAY_BANDS[:2], (2,)).matrixFnorm()
    elif kind == "rank3":
        value = source_array(ee, image, ARRAY_BANDS[:8], (2, 2, 2)).matrixFnorm()
    elif kind == "ordinary":
        value = ee.Image.constant(1).matrixFnorm()
    else:
        value = {
            "type": "Invocation", "functionName": "Image.matrixFnorm",
            "arguments": {"value": [[1, 2], [3, 4]]},
        }
    with pytest.raises(UnsupportedEEError):
        compile_raw(value, local) if isinstance(value, dict) else compile_value(ee, value, local)


def test_matrix_fnorm_requires_explicit_top_level_float32_cells(ee, local):
    uncast = first_image(ee).select(ARRAY_BANDS[:4]).toArray()
    uncast = uncast.arrayReshape(ee.Image.constant(ee.Array([2, 2])), 2)
    with pytest.raises(UnsupportedEEError, match="explicit top-level toFloat"):
        compile_value(ee, uncast.matrixFnorm(), local)
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, uncast.toDouble().matrixFnorm(), local)


def test_sparse_eight_by_eight_accumulation_respects_the_real_500_node_cap(ee, local):
    image = first_image(ee)
    source = source_array(ee, image, ARRAY_BANDS, (8, 8), "large_array")
    labels = [[f"r{row}" for row in range(8)], [f"c{column}" for column in range(8)]]
    expression = source.arrayAccum(0).arrayFlatten(labels, separator="_")
    with pytest.raises(UnsupportedEEError, match="500 nodes"):
        compile_value(ee, expression, local)


@pytest.mark.parametrize("operation", ["Image.arrayAccum", "Image.matrixFnorm"])
def test_work_budget_preflight_happens_before_output_wrapper(monkeypatch, operation):
    from gee.compat.earthengine import raster_array_accumulation as accumulation_module
    from gee.compat.earthengine import raster_matrix_properties as matrix_module

    pixel = Pixel("to_float", (const(1.0),))
    if operation == "Image.arrayAccum":
        value = wrap_array_image(Image([], {}), (2,), (pixel, pixel), const(True), "preflight")
        module = accumulation_module
        monkeypatch.setattr(module, "wrap_array_image",
                            lambda *_a, **_k: pytest.fail("array wrapper ran before preflight"))
        arguments = {"input": value, "axis": 0}
        invoke = module.invoke_raster_accumulation
    else:
        value = wrap_array_image(Image([], {}), (1, 1), (pixel,), const(True), "preflight")
        module = matrix_module
        monkeypatch.setattr(module, "masked_scalar",
                            lambda *_a, **_k: pytest.fail("scalar wrapper ran before preflight"))
        arguments = {"value": value}
        invoke = module.invoke_raster_matrix_property

    translator = Translator([], {}, {})
    translator.steps = MAX_ARRAY_WORK - 1
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke(translator, operation, arguments)
    assert translator.steps == MAX_ARRAY_WORK - 1


def test_invalid_manually_constructed_overrank_and_overcell_arrays_are_rejected():
    from gee.compat.earthengine.raster_array_accumulation import invoke_raster_accumulation

    pixel = Pixel("to_float", (const(1.0),))
    overrank = RasterArrayImage(Image([], {}), (1,) * 9, (pixel,) * 9, const(True), "rank9")
    with pytest.raises(UnsupportedEEError, match="rank exceeds 8"):
        invoke_raster_accumulation(
            Translator([], {}, {}), "Image.arrayAccum", {"input": overrank, "axis": 0},
        )

    overcells = RasterArrayImage(Image([], {}), (9, 8), (pixel,) * 72, const(True), "cells72")
    with pytest.raises(UnsupportedEEError, match="64 cells"):
        invoke_raster_accumulation(
            Translator([], {}, {}), "Image.arrayAccum", {"input": overcells, "axis": 0},
        )
