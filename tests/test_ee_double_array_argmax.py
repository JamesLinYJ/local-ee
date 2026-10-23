"""Pinned SDK and independent NumPy checks for Float32/Float64 raster argmax."""
import numpy as np
import pytest

from gee.compat.earthengine.array_core import MAX_ARRAY_WORK
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, Source, const
from gee.compat.earthengine.raster_array_core import RasterArrayImage
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from ee_float64_graph_reference import evaluate_float64_graph
from test_ee_double_array_solve import _ROW_NAMES, _first_image, ee, local


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


def _compile_raster(ee, value, local):
    encoded = ee.serializer.encode(value, for_cloud_api=False)
    result = compile_expression(encoded, local["catalog"], local["items"])
    assert result["kind"] == "image"
    validate(result["process_graph"])
    values, names, timed = evaluate_float64_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries=local["geometries"],
    )
    assert timed is False
    return result, values, names


def _include_all_grid_centers(local):
    geometry = {"type": "Polygon", "coordinates": [
        [[0, 0], [6, 0], [6, 1], [0, 1], [0, 0]],
    ]}
    local["geometry"] = geometry
    local["geometries"][local["item_id"]] = geometry
    item = local["items"]["sentinel-2-l2a"][0]
    item["bbox"] = [0, 0, 6, 1]
    item["geometry"] = geometry


def _set_columns(local, columns):
    arrays = local["arrays"][local["item_id"]]
    for band, values in columns.items():
        values = np.asarray(values, dtype=np.float64)
        assert values.shape == (len(local["grid"]),)
        arrays[band] = values


def _first_row_major_max(values):
    """Independent NumPy reference with explicit first-equal selection."""
    values = np.asarray(values, dtype=np.float64)
    maximum = np.max(values)
    first = int(np.flatnonzero(values.reshape(-1) == maximum)[0])
    return np.unravel_index(first, values.shape)


def test_double_argmax_compares_binary64_values_and_keeps_full_array_mask(ee, local):
    _include_all_grid_centers(local)
    maximum = np.finfo(np.float64).max
    subnormal = np.nextafter(np.float64(0), np.float64(1))
    low = np.asarray([
        2**40 + 0.25,
        np.nextafter(np.float64(1), np.float64(2)),
        -maximum,
        subnormal,
        -0.0,
        4.0,
    ])
    high = np.asarray([
        2**40 + 0.375,
        1.0,
        maximum,
        0.0,
        0.0,
        np.nan,
    ])
    _set_columns(local, {"y0": low, "y1": high})

    source = _first_image(ee).set("argmax_owner", "double-test")
    array = source.select(["y0", "y1"]).toArray().rename("double_pair").toDouble()
    result, actual, names = _compile_raster(
        ee, array.arrayArgmax().arrayFlatten([["winner"]]), local,
    )

    assert names == result["bands"] == ["winner"]
    assert result["properties"]["argmax_owner"] == "double-test"
    assert result["source_item_ids"] == [local["item_id"]]
    pairs = np.stack([low, high])
    expected = np.full((1, len(local["grid"])), np.nan, dtype=np.float64)
    for sample in range(expected.shape[1]):
        if np.isfinite(pairs[:, sample]).all():
            expected[0, sample] = _first_row_major_max(pairs[:, sample])[0]
    np.testing.assert_array_equal(actual, expected)
    assert actual[0, 0] == 1.0  # The Double inputs differ below Float32 precision.
    assert actual[0, 1] == 0.0  # One binary64 ULP decides this near-equal pair.
    assert actual[0, 2] == 1.0  # Both signs of the largest finite Double.
    assert actual[0, 3] == 0.0  # The smallest subnormal remains greater than zero.
    assert actual[0, 4] == 0.0  # Signed zeros compare equal; the first cell wins.
    assert np.isnan(actual[0, 5])  # One missing cell masks every output coordinate.
    assert np.equal(actual[np.isfinite(actual)], np.floor(actual[np.isfinite(actual)])).all()


def test_outer_double_cast_preserves_nested_float32_quantization(ee, local):
    _include_all_grid_centers(local)
    low = np.asarray([16777216.0, 2.0, -5.0, 0.0, -0.0, 7.0])
    high = np.asarray([16777217.0, 3.0, -4.0, 0.0, 0.0, 7.0])
    _set_columns(local, {"y0": low, "y1": high})

    image = _first_image(ee).select(["y0", "y1"]).toArray()
    nested = image.toFloat().toDouble()
    result, actual, names = _compile_raster(
        ee, nested.arrayArgmax().arrayFlatten([["winner"]]), local,
    )

    quantized = np.stack([low, high]).astype(np.float32).astype(np.float64)
    expected = np.asarray([[
        _first_row_major_max(quantized[:, sample])[0]
        for sample in range(quantized.shape[1])
    ]], dtype=np.float64)
    assert names == result["bands"] == ["winner"]
    np.testing.assert_array_equal(actual, expected)
    assert actual[0, 0] == 0.0  # The inner Float32 cast's tie survives outer toDouble().


def test_double_argmax_rank_three_matches_numpy_and_preserves_metadata_and_mask(ee, local):
    _include_all_grid_centers(local)
    cases = [
        [-1, 4, 0, 2, 3, 1, 10, 10],
        [3, 10, 2, 10, 4, 5, 9, 0],
        [-8, -7, -6, -5, -4, -3, -2, -1],
        [-4, -4, -3, -2, -1, -8, -5, -6],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [1, 2, 3, 4, 5, 6, 7, np.nan],
    ]
    _set_columns(local, {
        band: [case[index] for case in cases]
        for index, band in enumerate(_ROW_NAMES)
    })

    source = _first_image(ee).set("array_owner", "rank-three-double")
    array = source.select(list(_ROW_NAMES)).toArray().arrayReshape(
        ee.Image.constant(ee.Array([2, 2, 2])), 3,
    ).toDouble()
    output = array.arrayArgmax().arrayFlatten([["axis0", "axis1", "axis2"]])
    result, actual, names = _compile_raster(ee, output, local)

    expected = np.full((3, len(cases)), np.nan, dtype=np.float64)
    for sample, values in enumerate(cases):
        if np.isfinite(values).all():
            expected[:, sample] = _first_row_major_max(
                np.asarray(values).reshape((2, 2, 2)),
            )
    assert names == result["bands"] == ["axis0", "axis1", "axis2"]
    assert result["properties"]["array_owner"] == "rank-three-double"
    assert result["source_item_ids"] == [local["item_id"]]
    np.testing.assert_array_equal(actual, expected)
    assert actual[:, 0].tolist() == [1.0, 1.0, 0.0]  # First of two row-major ties.
    assert actual[:, 1].tolist() == [0.0, 0.0, 1.0]
    assert actual[:, 2].tolist() == [1.0, 1.0, 1.0]  # All-negative input.
    assert actual[:, 3].tolist() == [1.0, 0.0, 0.0]
    assert actual[:, 4].tolist() == [0.0, 0.0, 0.0]
    assert np.isnan(actual[:, 5]).all()


def test_double_argmax_accepts_rank_eight_singleton_coordinates(ee, local):
    source = _first_image(ee).select(["y0"]).toArray().arrayReshape(
        ee.Image.constant(ee.Array([1] * 8)), 8,
    ).toDouble()
    labels = [f"axis{axis}" for axis in range(8)]
    result, actual, names = _compile_raster(
        ee, source.arrayArgmax().arrayFlatten([labels]), local,
    )
    assert names == result["bands"] == labels
    np.testing.assert_array_equal(actual[:, :5], np.zeros((8, 5)))
    assert result["source_item_ids"] == [local["item_id"]]


def _direct_array(cells, shape, name="array"):
    image = Image([], {}, Source("sentinel-2-l2a", ("sample",), ("v00",)))
    return RasterArrayImage(image, shape, cells, const(True), name)


def test_double_argmax_rejects_mixed_or_malformed_top_casts():
    mixed = _direct_array((
        Pixel("to_double", (const(1.0),)),
        Pixel("to_float", (const(2.0),)),
    ), (2,))
    with pytest.raises(UnsupportedEEError, match="one uniform explicit cast"):
        Translator([], {}, {}).invoke("Image.arrayArgmax", {"image": mixed})

    malformed = _direct_array((Pixel("to_double", (const(1.0), const(2.0))),), (1,))
    with pytest.raises(UnsupportedEEError, match="explicit top-level"):
        Translator([], {}, {}).invoke("Image.arrayArgmax", {"image": malformed})


def test_double_argmax_accepts_64_cells_within_shared_work_budget():
    cells = tuple(
        Pixel("to_double", (const(float(index)),)) for index in range(64)
    )
    translator = Translator([], {}, None)
    result = translator.invoke(
        "Image.arrayArgmax", {
            "image": _direct_array(cells, (64,), name="preserved-double-array"),
        },
    )
    assert result.shape == (1,)
    assert result.name == "preserved-double-array"
    assert translator.steps < MAX_ARRAY_WORK
    assert result.cells[0].op == "to_float"


def test_double_argmax_precharges_work_before_scanning_casts(monkeypatch):
    class NoScanTuple(tuple):
        def __iter__(self):
            raise AssertionError("Double cast cells scanned before work preflight")

    cells = NoScanTuple((Pixel("to_double", (const(1.0),)),) * 2)
    translator = Translator([], {}, None)
    translator.steps = MAX_ARRAY_WORK
    with pytest.raises(UnsupportedEEError, match="work budget"):
        translator.invoke(
            "Image.arrayArgmax", {"image": _direct_array(cells, (2,))},
        )
    assert translator.steps == MAX_ARRAY_WORK


def test_double_argmax_dense_dynamic_graph_keeps_500_node_cap(ee, local):
    bands = [f"argmax_{index:02d}" for index in range(64)]
    local["catalog"][0]["cube:dimensions"]["bands"]["values"].extend(bands)
    arrays = local["arrays"][local["item_id"]]
    for index, band in enumerate(bands):
        arrays[band] = np.full(len(local["grid"]), float(index))
    source = _first_image(ee).select(bands).toArray().toDouble()
    output = source.arrayArgmax().arrayFlatten([["winner"]])
    with pytest.raises(UnsupportedEEError, match="500"):
        _compile_raster(ee, output, local)
