"""Strict array-sort arguments, shape/dtype boundaries and resource controls."""
from dataclasses import replace

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, Source, const
from gee.compat.earthengine.raster_array_core import wrap_array_image
from gee.compat.earthengine import raster_array_sort
from gee.compat.earthengine.raster_array_sort import invoke_raster_sort
from gee.ee_translate import UnsupportedEEError
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_raster_array_accumulation import (
    ARRAY_BANDS, compile_raster, compile_value, ee, first_image, local,
    matrix_labels, source_array,
)


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


def fixed(shape=(3,), *, dtype="to_float"):
    cells = tuple(Pixel(dtype, (const(index),)) for index in range(int(np.prod(shape))))
    return wrap_array_image(Image([], {"tag": "input"}), shape, cells, const(True), "data")


def cast_array(*casts):
    cells = tuple(Pixel(cast, (const(index),)) for index, cast in enumerate(casts))
    return wrap_array_image(Image([], {"tag": "input"}), (len(cells),), cells,
                            const(True), "data")


def invoke(args, translator=None):
    return invoke_raster_sort(translator or Translator([], {}, {}), "Image.arraySort", args)


@pytest.mark.parametrize("args,match", [
    ({}, "requires image"), ({"image": None}, "RasterArrayImage"),
    ({"image": [1, 2]}, "RasterArrayImage"),
    ({"image": fixed(), "axis": 0}, "Unsupported algorithm arguments"),
    ({"image": fixed(), "keys": Image([], {})}, "RasterArrayImage"),
    ({"image": fixed(()), "keys": fixed(())}, "rank-1..8"),
    ({"image": fixed((2, 3))}, "one non-singleton axis"),
    ({"image": fixed((3,)), "keys": fixed((1, 3))}, "matching rank"),
    ({"image": fixed((2, 3)), "keys": fixed((1, 2))}, "key length"),
    ({"image": fixed((2, 3)), "keys": fixed((1, 1))}, "one non-singleton axis"),
    ({"image": cast_array("to_float", "to_double")}, "uniform explicit cast"),
    ({"image": fixed(), "keys": cast_array("to_float", "to_double", "to_float")},
     "uniform explicit cast"),
])
def test_invalid_inputs_fail_explicitly(args, match):
    with pytest.raises(UnsupportedEEError, match=match):
        invoke(args)


@pytest.mark.parametrize("shape", [(1,), (1, 1), (1,) * 8])
def test_single_cell_identity_preserves_layout_name_metadata_and_input(shape):
    value = fixed(shape)
    result = invoke({"image": value})
    assert result.cells == value.cells
    assert result.shape == shape and result.name == value.name
    assert result.image.props == {"tag": "input"}
    assert result.mask == value.mask
    assert value.image.props == {"tag": "input"}


def test_value_and_key_casts_are_uniform_independently_and_survive_selection():
    footprint = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    value = wrap_array_image(
        Image([], {"tag": "payload"}, Source("payload", ("scene-p",), ("p0", "p1")),
              footprint=footprint, footprint_is_absolute=True),
        (2,), tuple(Pixel("to_double", (const(index),)) for index in range(2)),
        const(True), "payload-array",
    )
    keys = wrap_array_image(
        Image([], {"tag": "keys"}, Source("keys", ("scene-k",), ("k0", "k1"))),
        (2,), tuple(Pixel("to_float", (const(index),)) for index in range(2)),
        const(True), "key-array",
    )
    result = invoke({"image": value, "keys": keys})

    assert result.shape == value.shape
    assert result.name == value.name == "payload-array"
    assert result.mask == value.mask == keys.mask
    assert result.image.props == value.image.props == {"tag": "payload"}
    assert result.image.source == value.image.source
    assert result.image.footprint == footprint and result.image.footprint_is_absolute
    assert [cell.op for cell in result.cells] == ["to_double", "to_double"]
    first_selection = result.cells[0].args[0]
    second_selection = result.cells[1].args[0]
    assert first_selection.op == second_selection.op == "if"
    condition = first_selection.args[0]
    assert condition.op == "gt" and condition.boolean
    assert condition.args == keys.cells
    assert first_selection.args[1:] == (value.cells[1], value.cells[0])
    assert second_selection.args[1:] == (value.cells[0], value.cells[1])


def test_rank_eight_and_64_cells_remain_inside_the_existing_work_cap():
    shape = (2, 2, 2, 2, 2, 2, 1, 1)
    value = fixed(shape)
    keys = fixed((2, 1, 1, 1, 1, 1, 1, 1), dtype="to_double")
    translator = Translator([], {}, {})

    result = invoke({"image": value, "keys": keys}, translator)

    assert result.shape == shape
    assert len(result.cells) == 64
    assert 0 < translator.steps < 50_000


@pytest.mark.parametrize("corrupt", [
    lambda array: replace(array, cells=(const(1),)),
    lambda array: replace(array, cells=tuple(const(1) for _ in array.cells)),
    lambda array: replace(array, mask=const(4)),
    lambda array: replace(array, image=None),
    lambda array: replace(array, name=3),
])
def test_malformed_internal_array_is_rejected(corrupt):
    with pytest.raises(UnsupportedEEError):
        invoke({"image": corrupt(fixed())})


def test_work_budget_is_checked_before_cast_scans_or_sort_dag_construction(monkeypatch):
    translator = Translator([], {}, {})
    translator.steps = 49_999
    value = fixed((64,))
    original_cells = value.cells

    def forbidden(*args, **kwargs):
        raise AssertionError("sort scanned casts or built its DAG before precharge")

    monkeypatch.setattr(raster_array_sort, "require_cast_cells", forbidden)
    with pytest.raises(UnsupportedEEError, match="work|budget|limit"):
        invoke({"image": value}, translator)
    assert value.cells is original_cells


def test_original_process_graph_limit_still_rejects_large_dynamic_sort(ee, local):
    value = source_array(ee, first_image(ee), ARRAY_BANDS[:16], (16,))
    with pytest.raises(UnsupportedEEError, match="500|node|limit"):
        compile_value(ee, value.arraySort().arrayFlatten(matrix_labels((16,))), local)


def test_scalar_image_and_multiple_array_bands_do_not_get_coerced_to_one_array(ee, local):
    with pytest.raises(UnsupportedEEError, match="RasterArrayImage"):
        compile_value(ee, first_image(ee).arraySort(), local)
    left = source_array(ee, first_image(ee), ARRAY_BANDS[:2], (2,), "left")
    right = source_array(ee, first_image(ee), ARRAY_BANDS[2:4], (2,), "right")
    with pytest.raises(UnsupportedEEError, match="array|Array"):
        compile_value(ee, left.addBands(right).arraySort(), local)


def test_explicit_key_clip_masks_payload_without_replacing_payload_properties(ee, local):
    source = first_image(ee).set("owner", "payload")
    payload = source_array(ee, source, ARRAY_BANDS[:3], (3,))
    roi = ee.Geometry.Rectangle([0, 0, 1, 1], proj="EPSG:4326", geodesic=False)
    key_source = first_image(ee).clip(roi).set("owner", "keys")
    keys = source_array(ee, key_source, ARRAY_BANDS[16:19], (3,))
    result, actual, _ = compile_raster(
        ee, payload.arraySort(keys).arrayFlatten([["a", "b", "c"]]), local,
    )
    assert result["properties"]["owner"] == "payload"
    assert np.isfinite(actual[:, 0]).all()
    assert np.isnan(actual[:, 1:]).all()
