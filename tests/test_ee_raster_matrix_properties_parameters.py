"""Strict raster matrix-property arguments, bounds and work preflight."""
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine import raster_matrix_properties as properties
from gee.compat.earthengine.array_core import MAX_ARRAY_WORK
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, const
from gee.compat.earthengine.raster_array_core import wrap_array_image
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_raster_matrix_properties import (
    COLUMN_BANDS,
    MATRIX4,
    MATRIX_BANDS,
    compile_raster,
    compile_value,
    encode,
    fraction_determinant,
    find_invocation,
    first_image,
    local,
    raster_matrix,
    valid_pixels,
)


ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = (
    "Image.matrixDiagonal",
    "Image.matrixToDiag",
    "Image.matrixTrace",
    "Image.matrixDeterminant",
)


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


def constant_array(ee, values, cast="float"):
    result = ee.Image.constant(ee.Array(values))
    if cast == "float":
        return result.toFloat()
    if cast == "double":
        return result.toDouble()
    return result


def expressions(ee):
    square = constant_array(ee, [[1, 2], [3, 4]])
    column = constant_array(ee, [[1], [2]])
    return {
        "Image.matrixDiagonal": square.matrixDiagonal().arrayFlatten(
            [["d0", "d1"], ["column"]]),
        "Image.matrixToDiag": column.matrixToDiag().arrayFlatten(
            [["r0", "r1"], ["c0", "c1"]]),
        "Image.matrixTrace": square.matrixTrace(),
        "Image.matrixDeterminant": square.matrixDeterminant(),
    }


def test_pinned_sdk_uses_required_value_only_and_dispatch_rejects_missing_or_unknown(ee, local):
    for name, expression in expressions(ee).items():
        encoded = encode(ee, expression)
        invocation = find_invocation(encoded, name)
        assert invocation is not None
        assert set(invocation["arguments"]) == {"value"}

        missing = encode(ee, expression)
        find_invocation(missing, name)["arguments"].pop("value")
        with pytest.raises(UnsupportedEEError):
            compile_expression(missing, local["catalog"], local["items"])

        unknown = encode(ee, expression)
        find_invocation(unknown, name)["arguments"]["unused"] = 1
        with pytest.raises(UnsupportedEEError):
            compile_expression(unknown, local["catalog"], local["items"])


@pytest.mark.parametrize("name", OPERATIONS)
def test_raw_list_and_ordinary_image_are_not_raster_array_inputs(ee, local, name):
    raw_list = {
        "type": "Invocation", "functionName": name,
        "arguments": {"value": [[1, 2], [3, 4]]},
    }
    with pytest.raises(UnsupportedEEError):
        compile_expression(raw_list, local["catalog"], local["items"])

    image = ee.Image.constant(1)
    expression = getattr(image, name.removeprefix("Image."))()
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, expression, local)


def test_matrix_diagonal_requires_rank_two_but_keeps_unfloated_input_cells(ee, local):
    vector = constant_array(ee, [1, 2, 3])
    with pytest.raises(UnsupportedEEError, match="rank-2"):
        compile_value(ee, vector.matrixDiagonal(), local)

    # Extraction itself preserves original cell expressions and does not
    # impose the explicit top-level Float32 contract of scalar reductions.
    uncast = ee.Image.constant(ee.Array([[1, 2], [3, 4]]))
    diagonal = uncast.matrixDiagonal()
    assert compile_value(ee, diagonal.bandNames(), local)["value"] == ["constant"]


@pytest.mark.parametrize("value", [
    [1, 2],
    [[1, 2], [3, 4]],
    [[1], [2], [3], [4], [5], [6], [7], [8], [9]],
])
def test_matrix_to_diag_rejects_noncolumn_or_more_than_eight_rows(ee, local, value):
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, constant_array(ee, value).matrixToDiag(), local)


@pytest.mark.parametrize("cast", [None, "double"])
def test_matrix_to_diag_requires_explicit_top_level_float32_cells(ee, local, cast):
    expected = "explicit top-level toFloat" if cast is None else None
    with pytest.raises(UnsupportedEEError, match=expected):
        compile_value(
            ee, constant_array(ee, [[1], [2]], cast=cast).matrixToDiag(), local,
        )


@pytest.mark.parametrize("operation", ["matrixTrace", "matrixDeterminant"])
def test_scalar_properties_reject_nonsquare_and_nonfloat32_inputs(ee, local, operation):
    rectangular = constant_array(ee, [[1, 2, 3], [4, 5, 6]])
    with pytest.raises(UnsupportedEEError, match="square"):
        compile_value(ee, getattr(rectangular, operation)(), local)

    square = [[1, 2], [3, 4]]
    for cast in (None, "double"):
        expected = "explicit top-level toFloat" if cast is None else None
        with pytest.raises(UnsupportedEEError, match=expected):
            compile_value(ee, getattr(constant_array(ee, square, cast), operation)(), local)


def test_matrix_determinant_caps_square_size_at_four(ee, local):
    five_by_five = constant_array(ee, np.eye(5).tolist())
    with pytest.raises(UnsupportedEEError, match="size 1 through 4"):
        compile_value(ee, five_by_five.matrixDeterminant(), local)


def test_matrix_to_diag_supports_eight_rows_and_keeps_shared_mask(ee, local):
    column = raster_matrix(ee, first_image(ee), COLUMN_BANDS, (8, 1), "wide_column")
    flattened = column.matrixToDiag().arrayFlatten(
        [[f"r{row}" for row in range(8)], [f"c{column}" for column in range(8)]],
        separator="_",
    )
    result, actual, names = compile_raster(ee, flattened, local)

    expected_names = [f"r{row}_c{column}" for row in range(8) for column in range(8)]
    assert names == result["bands"] == expected_names
    raw = np.stack([
        local["arrays"]["matrix-properties-scene"][name] for name in COLUMN_BANDS
    ]).astype(np.float32).astype(np.float64)
    expected = np.zeros((64, raw.shape[1]), dtype=np.float64)
    for index in range(8):
        expected[index * 8 + index] = raw[index]
    expected[:, ~valid_pixels(local, COLUMN_BANDS)] = np.nan
    np.testing.assert_array_equal(actual, expected)


def test_matrix_trace_accepts_the_eight_by_eight_limit(ee, local):
    matrix = constant_array(ee, np.eye(8).tolist())
    materialized = matrix.matrixTrace().add(first_image(ee).select(["m00"]).multiply(0))
    _, actual, _ = compile_raster(ee, materialized, local)
    np.testing.assert_array_equal(actual[0, :4], np.full(4, 8.0))
    assert np.isnan(actual[0, 4])


def test_negative_one_by_one_and_singular_two_by_two_determinants(ee, local):
    negative = raster_matrix(ee, first_image(ee), [COLUMN_BANDS[2]], (1, 1), "negative")
    result, actual, names = compile_raster(ee, negative.matrixDeterminant(), local)
    assert names == result["bands"] == ["negative"]
    expected = local["arrays"]["matrix-properties-scene"][COLUMN_BANDS[2]]
    expected = expected.astype(np.float32).astype(np.float64)
    expected[~valid_pixels(local, [COLUMN_BANDS[2]])] = np.nan
    np.testing.assert_array_equal(actual[0], expected)

    repeated_column = (
        first_image(ee).select(["m00", "m10"]).toArray().toArray(axis=1)
        .matrixMultiply(ee.Image.constant(ee.Array([[1, 1]]))).toFloat()
    )
    determinant_result, determinant, _ = compile_raster(
        ee, repeated_column.matrixDeterminant(), local,
    )
    assert determinant_result["bands"] == ["array"]
    np.testing.assert_array_equal(determinant[0, :4], np.zeros(4))
    assert np.isnan(determinant[0, 4])


def test_float32_finite_inputs_can_overflow_constant_compile_and_be_rejected(ee, local):
    source = first_image(ee).select(["m00"])
    huge = constant_array(ee, [[2e38, 0], [0, 2e38]])
    for operation in ("matrixTrace", "matrixDeterminant"):
        expression = getattr(huge, operation)().add(source.multiply(0))
        with pytest.raises(UnsupportedEEError):
            compile_value(ee, expression, local)


def test_dense_dynamic_four_by_four_determinant_respects_real_graph_cap(ee, local):
    matrix = raster_matrix(ee, first_image(ee), MATRIX_BANDS, (4, 4), "dense4")
    with pytest.raises(UnsupportedEEError, match="500 nodes"):
        compile_value(ee, matrix.matrixDeterminant(), local)

    # The same supported shape with literal cells folds to a small constant
    # result once placed on a raster grid; the graph cap is about the dynamic
    # expansion, not a smaller matrix-size limit.
    literal = constant_array(ee, MATRIX4.tolist()).matrixDeterminant()
    materialized = literal.add(first_image(ee).select(["m00"]).multiply(0))
    _, actual, _ = compile_raster(ee, materialized, local)
    np.testing.assert_array_equal(
        actual[0, :4], np.full(4, float(fraction_determinant(MATRIX4))),
    )
    assert np.isnan(actual[0, 4])


@pytest.mark.parametrize("name", OPERATIONS)
def test_shared_work_preflight_precedes_result_wrapper_creation(monkeypatch, name):
    import gee.compat.earthengine.raster_matrix_properties as core

    def forbidden(*_args, **_kwargs):
        raise AssertionError("output wrapper was constructed before work preflight")

    monkeypatch.setattr(core, "wrap_array_image", forbidden)
    monkeypatch.setattr(core, "masked_scalar", forbidden)
    value = wrap_array_image(
        Image([], {}), (1, 1), (Pixel("to_float", (const(1.0),)),), const(True), "preflight",
    )
    translator = Translator([], {}, {})
    translator.steps = MAX_ARRAY_WORK - 1
    with pytest.raises(UnsupportedEEError, match="work budget"):
        properties.invoke_raster_matrix_property(translator, name, {"value": value})
    assert translator.steps == MAX_ARRAY_WORK - 1
