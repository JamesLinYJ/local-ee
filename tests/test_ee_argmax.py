"""Static and fixed-shape raster argmax through pinned SDK serialization."""
from copy import deepcopy

import numpy as np
import pytest

from gee.ee_translate import UnsupportedEEError
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_raster_array_accumulation import (
    ARRAY_BANDS, compile_raster, compile_value, ee, encode, first_image, local,
    source_array, valid_samples,
)


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


def static_result(ee, value):
    return compile_value(ee, value, {"catalog": [], "items": {}})["value"]


def first_row_major_coordinate(values):
    """Independent lexicographic reference, including exact first-tie choice."""
    array = np.asarray(values)
    flattened = array.reshape(-1).tolist()
    maximum = max(flattened)
    flat_index = next(index for index, value in enumerate(flattened) if value == maximum)
    return list(np.unravel_index(flat_index, array.shape))


def flat_invocation(expression, function_name):
    if isinstance(expression, dict):
        if (expression.get("type") == "Invocation"
                and expression.get("functionName") == function_name):
            return expression
        for child in expression.values():
            found = flat_invocation(child, function_name)
            if found is not None:
                return found
    elif isinstance(expression, (list, tuple)):
        for child in expression:
            found = flat_invocation(child, function_name)
            if found is not None:
                return found
    return None


@pytest.mark.parametrize("values", [
    [4, 9, 9, -2],
    [[-9, -3], [-3, -8]],
    [[[0, -1], [1, 0]], [[2, 2], [2, -10]]],
    [[[0, 0], [0, 0]], [[0, 0], [0, 0]]],
])
def test_static_sdk_argmax_uses_first_row_major_maximum(ee, values):
    result = static_result(ee, ee.Array(values).argmax())
    assert result == first_row_major_coordinate(values)
    assert all(type(index) is int for index in result)


def test_static_argmax_keeps_binary64_precision_and_exact_integer_domain(ee):
    wide_values = [1e100, 1e200, 1e150]
    assert static_result(ee, ee.Array(wide_values).argmax()) == [1]

    edge_values = [-(2**53), -(2**53) + 1, 2**53 - 1, 2**53]
    assert static_result(ee, ee.Array(edge_values).argmax()) == [3]


def test_static_argmax_returns_empty_rank0_and_typed_empty_results(ee):
    assert static_result(ee, ee.Array(17).argmax()) == []
    typed_empty = ee.Array([7, 3]).slice(0, 0, 0)
    assert static_result(ee, typed_empty.argmax()) is None


def test_static_argmax_scans_rank_eight_row_major_values(ee):
    values = np.arange(256, dtype=np.int64).reshape((2,) * 8).tolist()
    assert static_result(ee, ee.Array(values).argmax()) == [1] * 8


def set_sample_values(local, bands, sample, values):
    for band, value in zip(bands, values):
        local["arrays"]["accum-scene"][band][sample] = value


def test_raster_argmax_rank3_matches_independent_coordinates_and_keeps_mask(
        ee, local):
    bands = ARRAY_BANDS[:8]
    # A row-major tie, an all-negative vector, a missing non-winner, and an
    # all-zero tie. The missing cell at flat index 5 must still mask every
    # coordinate even though flat index 0 would otherwise win.
    vectors = [
        [5, 9, 9, -1, -2, -3, -4, -5],
        [-8, -7, -6, -5, -4, -3, -1, -2],
        [100, 0, 0, 0, 0, np.nan, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
    ]
    for sample, vector in enumerate(vectors):
        set_sample_values(local, bands, sample, vector)

    before = deepcopy(local["arrays"]["accum-scene"])
    source = first_image(ee).set("argmax_tag", "kept")
    value = source_array(ee, source, bands, (2, 2, 2), "cube")
    result, actual, names = compile_raster(
        ee,
        value.arrayArgmax().arrayFlatten([["axis0", "axis1", "axis2"]]),
        local,
    )

    assert names == result["bands"] == ["axis0", "axis1", "axis2"]
    assert result["properties"]["argmax_tag"] == "kept"
    assert result["source_item_ids"] == ["accum-scene"]
    values = np.stack([local["arrays"]["accum-scene"][band] for band in bands], axis=1)
    values = values.astype(np.float32).astype(np.float64).reshape((5, 2, 2, 2))
    valid = valid_samples(local, bands)
    expected = np.full((3, 5), np.nan, dtype=np.float64)
    for sample in np.flatnonzero(valid):
        expected[:, sample] = first_row_major_coordinate(values[sample])
    np.testing.assert_array_equal(actual, expected)
    assert actual[:, 0].tolist() == [0.0, 0.0, 1.0]
    assert actual[:, 1].tolist() == [1.0, 1.0, 0.0]
    assert np.isnan(actual[:, 2]).all()
    assert actual[:, 3].tolist() == [0.0, 0.0, 0.0]
    for band in before:
        np.testing.assert_array_equal(
            local["arrays"]["accum-scene"][band], before[band],
        )


def test_raster_float32_input_quantization_changes_tie_to_first(ee, local):
    bands = ARRAY_BANDS[:2]
    set_sample_values(local, bands, 0, [16777216.0, 16777217.0])
    source = source_array(ee, first_image(ee), bands, (2,), "pair")
    result, actual, names = compile_raster(
        ee, source.arrayArgmax().arrayFlatten([["winner"]]), local,
    )

    original = np.asarray([16777216.0, 16777217.0], dtype=np.float64)
    quantized = original.astype(np.float32)
    assert int(np.argmax(original)) == 1
    assert quantized[0] == quantized[1]
    assert first_row_major_coordinate(quantized) == [0]
    assert names == result["bands"] == ["winner"]
    assert actual[0, 0] == 0.0
    assert float(actual[0, 0]).is_integer()
