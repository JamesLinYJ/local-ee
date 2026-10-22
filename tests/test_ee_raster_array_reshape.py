"""Shape reinterpretation of fixed raster-array pixels via the pinned EE SDK."""
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_core import MAX_ARRAY_WORK
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, Source, const
from gee.compat.earthengine.raster_array_core import wrap_array_image
from gee.compat.earthengine.raster_array_reshape import invoke_raster_reshape
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
INPUT_NAMES = ["blue", "green", "red", "nir"]


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


@pytest.fixture
def local():
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 1], [0, 1], [0, 0]]]}
    bands = INPUT_NAMES + ["b4", "b5", "b6", "b7"]
    arrays = {"reshape-scene": {
        "blue": np.array([16777217., 2., 3., 4.]),
        "green": np.array([10., 20., 30., 40.]),
        "red": np.array([100., 200., np.nan, 400.]),
        "nir": np.array([1000., 2000., 3000., 4000.]),
        "b4": np.array([5., 6., 7., 8.]), "b5": np.array([9., 10., 11., 12.]),
        "b6": np.array([13., 14., 15., 16.]), "b7": np.array([17., 18., 19., 20.]),
    }}
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": bands}}}]
    items = {"sentinel-2-l2a": [{
        "id": "reshape-scene", "bbox": [0, 0, 4, 1], "geometry": geometry,
        "properties": {"system:index": "reshape-scene", "system:time_start": 1000},
    }]}
    return {"catalog": catalog, "items": items, "arrays": arrays,
            "grid": np.array([[x + 0.5, 0.5] for x in range(4)]),
            "geometry": geometry}


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_value(ee, value, local):
    return compile_expression(encode(ee, value), local["catalog"], local["items"])


def find_invocation(value, function_name):
    if isinstance(value, dict):
        if value.get("type") == "Invocation" and value.get("functionName") == function_name:
            return value
        for child in value.values():
            found = find_invocation(child, function_name)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for child in value:
            found = find_invocation(child, function_name)
            if found is not None:
                return found
    return None


def compile_and_evaluate(ee, value, local):
    result = compile_value(ee, value, local)
    values, names, timed = evaluate_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries={"reshape-scene": local["geometry"]},
    )
    assert timed is False
    return result, dict(zip(names, values))


def reshaped(ee, local, shape_values=(2, 2)):
    source = ee.Image("reshape-scene").set("reshape_tag", "kept")
    source_array = source.select(INPUT_NAMES).toFloat().toArray().rename(["features"])
    lengths = ee.Image.constant(ee.Array(list(shape_values)))
    return source_array.arrayReshape(lengths, len(shape_values))


def test_sdk_array_reshape_preserves_row_major_cells_float32_mask_metadata_and_source(ee, local):
    matrix = reshaped(ee, local)
    assert compile_value(ee, matrix.bandNames(), local)["value"] == ["features"]
    # Dictionary lookup and Image(...) wrapping preserve the typed array value.
    carried = ee.Image(ee.Dictionary({"array": matrix}).get("array"))
    flat = carried.arrayFlatten([["top", "bottom"], ["left", "right"]], separator="_")
    result, values = compile_and_evaluate(ee, flat, local)

    assert result["source_item_ids"] == ["reshape-scene"]
    assert result["properties"] == {
        "reshape_tag": "kept", "system:index": "reshape-scene",
        "system:time_start": 1000,
    }
    assert result["bands"] == ["top_left", "top_right", "bottom_left", "bottom_right"]
    # Independent row-major mapping from [blue,green,red,nir] to [[blue,green],[red,nir]].
    np.testing.assert_allclose(values["top_left"], [16777216., 2., np.nan, 4.], equal_nan=True)
    np.testing.assert_allclose(values["top_right"], [10., 20., np.nan, 40.], equal_nan=True)
    np.testing.assert_allclose(values["bottom_left"], [100., 200., np.nan, 400.], equal_nan=True)
    np.testing.assert_allclose(values["bottom_right"], [1000., 2000., np.nan, 4000.], equal_nan=True)


@pytest.mark.parametrize("shape_values,dimensions,expected", [
    ((2, -1), 2, [2, 2]),
    ((-1,), 1, [4]),
    ((4,), 1, [4]),
])
def test_array_reshape_inferred_dimensions_and_flattening_are_independent_of_factorization(
    ee, local, shape_values, dimensions, expected
):
    source = ee.Image("reshape-scene").select(INPUT_NAMES).toFloat().toArray()
    lengths = ee.Image.constant(ee.Array(list(shape_values)))
    value = source.arrayReshape(lengths, dimensions)
    labels = [[f"axis{axis}_{index}" for index in range(size)]
              for axis, size in enumerate(expected)]
    flat = value.arrayFlatten(labels, separator="_")
    result, values = compile_and_evaluate(ee, flat, local)
    expected_names = [
        "_".join(labels[axis][coordinate] for axis, coordinate in enumerate(index))
        for index in np.ndindex(*expected)
    ]
    assert result["bands"] == expected_names
    # The first sample exercises Float32 conversion before the shape operation.
    assert values[expected_names[0]][0] == 16777216.
    assert np.isnan(np.asarray(list(values.values()))[:, 2]).all()


def test_rank_eight_singleton_shape_is_valid_and_lengths_can_be_constant_expressions(ee, local):
    source = ee.Image("reshape-scene").select(["blue"]).toArray()
    base_lengths = ee.Image.constant(ee.Array([1] * 8))
    lengths = base_lengths.multiply(ee.Image.constant(ee.Array([1] * 8)))
    eight_axes = source.arrayReshape(lengths, 8)
    lengths_flat = eight_axes.arrayLengths().arrayFlatten([[
        f"axis_{index}" for index in range(8)
    ]])
    result, values = compile_and_evaluate(ee, lengths_flat, local)
    assert result["bands"] == [f"axis_{index}" for index in range(8)]
    for band in result["bands"]:
        np.testing.assert_allclose(values[band], [1., 1., 1., 1.])


def test_eight_by_eight_cell_shape_is_a_supported_boundary(ee, local):
    source = ee.Image("reshape-scene").select(INPUT_NAMES + ["b4", "b5", "b6", "b7"])
    column = source.toArray().toArray(axis=1)
    row = ee.Image.constant(ee.Array([[1] * 8]))
    cube = column.matrixMultiply(row)
    lengths = ee.Image.constant(ee.Array([8, 8]))
    shaped = cube.arrayReshape(lengths, 2)
    shape_bands = shaped.arrayLengths().arrayFlatten([["rows", "columns"]])
    result, values = compile_and_evaluate(ee, shape_bands, local)
    assert result["bands"] == ["rows", "columns"]
    np.testing.assert_allclose(values["rows"], [8., 8., np.nan, 8.], equal_nan=True)
    np.testing.assert_allclose(values["columns"], [8., 8., np.nan, 8.], equal_nan=True)
    oversized = cube.arrayReshape(ee.Image.constant(ee.Array([64, 2])), 2)
    with pytest.raises(UnsupportedEEError, match="64 cells"):
        compile_value(ee, oversized, local)


def test_reshape_lengths_must_be_static_unmasked_rank_one_and_match_dimensions(ee, local):
    source = ee.Image("reshape-scene").select(INPUT_NAMES).toArray()
    dynamic = ee.Image("reshape-scene").select(["blue", "green"]).toArray()
    bad_shapes = [
        (dynamic, 2),
        (ee.Image.constant(ee.Array([[2, 2]])), 2),
        (ee.Image.constant(ee.Array([2, 2])), 1),
        (ee.Image.constant(ee.Array([2, 2])), 0),
        (ee.Image.constant(ee.Array([2, 2])), 9),
    ]
    for lengths, dimensions in bad_shapes:
        with pytest.raises(UnsupportedEEError):
            compile_value(ee, source.arrayReshape(lengths, dimensions), local)

    # Integer-valued numeric dimensions follow the shared Integer policy;
    # bool is a distinct wire type even though Python treats it as an int.
    accepted_float = source.arrayReshape(ee.Image.constant(ee.Array([2, 2])), 2.0)
    assert compile_value(ee, accepted_float.bandNames(), local)["value"] == ["array"]
    for dimensions in (True, 1.5):
        with pytest.raises(UnsupportedEEError):
            compile_value(ee, source.arrayReshape(ee.Image.constant(ee.Array([2, 2])), dimensions), local)


@pytest.mark.parametrize("shape_values,dimensions", [
    ((0, 4), 2), ((65,), 1), ((3, 2), 2), ((-1, -1), 2),
    ((3, -1), 2), ((-1, 3), 2), ((1.5, 2.5), 2),
])
def test_reshape_rejects_zero_invalid_inferred_and_noninteger_lengths(ee, local, shape_values, dimensions):
    source = ee.Image("reshape-scene").select(INPUT_NAMES).toArray()
    lengths = ee.Image.constant(ee.Array(list(shape_values)))
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, source.arrayReshape(lengths, dimensions), local)


def test_reshape_requires_typed_array_inputs_and_rejects_public_array_json(ee, local):
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, ee.Image("reshape-scene").arrayReshape(
            ee.Image.constant(ee.Array([4])), 1), local)

    value = reshaped(ee, local)
    with pytest.raises(UnsupportedEEError, match="direct array raster export"):
        compile_value(ee, value, local)
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, ee.Image("reshape-scene").select(INPUT_NAMES).toArray()
                      .arrayReshape(ee.Array([2, 2]), 2), local)


def test_pinned_array_reshape_signature_and_required_arguments(ee, local):
    value = reshaped(ee, local).arrayFlatten([["top", "bottom"], ["left", "right"]])
    encoded = encode(ee, value)
    call = find_invocation(encoded, "Image.arrayReshape")
    assert call is not None
    assert set(call["arguments"]) == {"image", "lengths", "dimensions"}

    for arguments in (
        {"image": [], "lengths": []},
        {"image": [], "dimensions": 2},
        {"lengths": [], "dimensions": 2},
    ):
        with pytest.raises(UnsupportedEEError):
            compile_expression({"type": "Invocation", "functionName": "Image.arrayReshape",
                                "arguments": arguments}, local["catalog"], local["items"])

    call["arguments"]["extra"] = 0
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(encoded, local["catalog"], local["items"])


def test_masked_length_pixels_are_rejected_and_work_is_preflighted_before_output_wrapper(monkeypatch):
    from gee.compat.earthengine import raster_array_reshape as reshape_module

    source = Image([], {"tag": "source"})
    input_array = wrap_array_image(source, (4,), tuple(const(i) for i in range(4)), const(True), "input")
    dynamic_mask = Pixel("band", (Source("local", ("scene",), ("mask",)), "mask"), True)
    lengths = wrap_array_image(source, (2,), (const(2), const(2)), dynamic_mask, "shape")
    translator = Translator([], {}, {})
    with pytest.raises(UnsupportedEEError, match="unmasked array mask"):
        invoke_raster_reshape(translator, "Image.arrayReshape", {
            "image": input_array, "lengths": lengths, "dimensions": 2,
        })

    monkeypatch.setattr(reshape_module, "wrap_array_image",
                        lambda *args, **kwargs: pytest.fail("output wrapper ran before work preflight"))
    lengths = wrap_array_image(source, (2,), (const(2), const(2)), const(True), "shape")
    translator.steps = MAX_ARRAY_WORK - 1
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_raster_reshape(translator, "Image.arrayReshape", {
            "image": input_array, "lengths": lengths, "dimensions": 2,
        })
    assert translator.steps == MAX_ARRAY_WORK
