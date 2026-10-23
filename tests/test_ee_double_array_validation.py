"""Precision errors and unchanged budget boundaries for Double arrays."""
import numpy as np
import pytest

from gee.compat.earthengine.array_core import MAX_ARRAY_WORK
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, const
from gee.compat.earthengine.raster_array_accumulation import invoke_raster_accumulation
from gee.compat.earthengine.raster_array_core import wrap_array_image
from gee.ee_translate import UnsupportedEEError
from ee_float64_graph_reference import evaluate_float64_graph
from test_ee_double_array_properties import (
    ee, local, offline_only, MATRIX_BANDS, ACCUM_BANDS,
    source_array, compile_value,
)


def test_double_array_rejects_float32_overflow_before_double_arithmetic(ee, local):
    source = ee.ImageCollection("sentinel-2-l2a").first()
    matrix = source_array(
        ee, source, MATRIX_BANDS, (2, 2), "overflowed",
        precision="float_then_double",
    )
    result = compile_value(ee, matrix.matrixTrace(), local)
    processes = {node["process_id"] for node in result["process_graph"].values()}
    assert "local_ee_to_float" in processes
    assert "local_ee_to_double" in processes
    assert "local_ee_integer_values" in processes

    scene = "double-array-scene"
    source_arrays = local["arrays"][scene]
    arrays = {scene: dict(source_arrays)}
    for band, value in zip(MATRIX_BANDS, (1e20, 2e20, 3e20, -1e20)):
        values = np.array(arrays[scene][band], copy=True)
        values[1] = value
        arrays[scene][band] = values
    overflowing = np.array(arrays[scene]["m00"], copy=True)
    overflowing[0] = 1e308
    arrays[scene]["m00"] = overflowing
    with pytest.warns(RuntimeWarning, match="overflow encountered in cast"):
        with pytest.raises(ValueError, match="valid infinity"):
            evaluate_float64_graph(
                result, arrays, grid=local["grid"],
                source_geometries={scene: local["geometry"]},
            )


def test_double_array_cast_validation_and_existing_work_cap():
    cells = tuple(Pixel("to_double", (const(index + 1),)) for index in range(2))
    array = wrap_array_image(Image([], {}), (2,), cells, const(True), "array")
    translator = Translator([], {}, {})
    translator.steps = MAX_ARRAY_WORK - 20
    invoke_raster_accumulation(
        translator, "Image.arrayAccum", {"input": array, "axis": 0},
    )
    assert translator.steps == MAX_ARRAY_WORK

    rejected = Translator([], {}, {})
    rejected.steps = MAX_ARRAY_WORK - 19
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_raster_accumulation(
            rejected, "Image.arrayAccum", {"input": array, "axis": 0},
        )
    assert rejected.steps == MAX_ARRAY_WORK - 19


def test_double_matrix_ops_reject_untyped_and_mixed_precision_cells(ee, local):
    image = ee.ImageCollection("sentinel-2-l2a").first()
    untyped = source_array(ee, image, MATRIX_BANDS, (2, 2), "untyped", "uncast")
    with pytest.raises(UnsupportedEEError, match=r"explicit top-level toFloat\(\) or toDouble"):
        compile_value(ee, untyped.matrixFnorm(), local)

    mixed_image = image.select("m00").toDouble().addBands(
        image.select("m11").toFloat(),
    )
    mixed = mixed_image.toArray().arrayReshape(
        ee.Image.constant(ee.Array([2, 1])), 2,
    )
    with pytest.raises(UnsupportedEEError, match="one uniform explicit cast"):
        compile_value(ee, mixed.matrixToDiag(), local)


def test_double_array_accum_keeps_axis_reducer_and_shape_rejections(ee, local):
    image = ee.ImageCollection("sentinel-2-l2a").first()
    array = source_array(ee, image, ACCUM_BANDS, (3,), "input")
    with pytest.raises(UnsupportedEEError, match="axis"):
        compile_value(ee, array.arrayAccum(1), local)
    with pytest.raises(UnsupportedEEError, match="SUM, MIN, or MAX"):
        compile_value(ee, array.arrayAccum(0, ee.Reducer.mean()), local)
