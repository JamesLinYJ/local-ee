"""Keyed raster permutations compared with independent stable index sorting."""
from copy import deepcopy

import numpy as np
import pytest

from scripts.ee_python_api.offline import OfflineGuard
from test_ee_raster_array_accumulation import (
    ARRAY_BANDS, compile_raster, ee, first_image, local, matrix_labels,
    source_array, source_values, valid_samples,
)


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


def stable_reference(data, keys, axis):
    """Use Python's index sort, then NumPy take: no compare-exchange kernel."""
    permutation = sorted(range(len(keys)), key=lambda index: keys[index])
    return np.take(data, permutation, axis=axis)


def expected_samples(local, payload_bands, shape, key_bands, key_shape, axis):
    values = source_values(local, payload_bands, shape)
    keys = source_values(local, key_bands, key_shape)
    valid = valid_samples(local, [*payload_bands, *key_bands])
    output = np.full_like(values, np.nan)
    for sample in np.flatnonzero(valid):
        output[sample] = stable_reference(values[sample], keys[sample].reshape(-1), axis)
    return output.reshape((len(valid), -1)).T


@pytest.mark.parametrize("shape,key_shape,axis", [
    ((4,), (4,), 0), ((3, 2), (3, 1), 0),
    ((2, 3), (1, 3), 1), ((2, 2, 2), (1, 2, 1), 1),
])
def test_sdk_key_sort_moves_entire_slices_preserving_payload_and_masks(
        ee, local, shape, key_shape, axis):
    count, key_count = int(np.prod(shape)), int(np.prod(key_shape))
    payload_bands, key_bands = ARRAY_BANDS[:count], ARRAY_BANDS[16:16 + key_count]
    # Sample 0 has a tied key and negative values; sample 1 is reverse sorted.
    vectors = [[2, -1, -1, 4][:key_count], list(reversed(range(key_count)))]
    for sample, vector in enumerate(vectors):
        for band, value in zip(key_bands, vector):
            local["arrays"]["accum-scene"][band][sample] = value
    local["arrays"]["accum-scene"][key_bands[-1]][3] = np.nan
    before = deepcopy(local["arrays"])
    source = first_image(ee).set("sort_tag", "preserved")
    payload = source_array(ee, source, payload_bands, shape, "payload")
    keys = source_array(ee, source, key_bands, key_shape, "sort_keys")
    result, actual, names = compile_raster(
        ee, payload.arraySort(keys).arrayFlatten(matrix_labels(shape)), local,
    )
    expected = expected_samples(local, payload_bands, shape, key_bands, key_shape, axis)
    np.testing.assert_array_equal(actual, expected)
    assert result["bands"] == names
    assert result["properties"]["sort_tag"] == "preserved"
    assert result["source_item_ids"] == ["accum-scene"]
    assert np.isnan(actual[:, 3]).all()  # missing key masks every payload cell
    assert np.isnan(actual[:, 4]).all()  # outside polygon even though inside bbox
    for scene in before:
        for band in before[scene]:
            np.testing.assert_array_equal(local["arrays"][scene][band], before[scene][band])


@pytest.mark.parametrize("explicit_null", [False, True])
def test_default_or_null_keys_sort_the_values_and_keep_all_input_masks(ee, local, explicit_null):
    bands, shape = ARRAY_BANDS[:6], (6,)
    value = source_array(ee, first_image(ee), bands, shape)
    sorted_array = value.arraySort(None) if explicit_null else value.arraySort()
    result, actual, _ = compile_raster(ee, sorted_array.arrayFlatten(matrix_labels(shape)), local)
    expected = expected_samples(local, bands, shape, bands, shape, 0)
    np.testing.assert_array_equal(actual, expected)
    assert np.isnan(actual[:, 2]).all()  # a non-winning missing payload also invalidates output
    assert len(result["process_graph"]) <= 500


def test_float32_key_quantization_and_stable_ties_keep_original_payload(ee, local):
    data = local["arrays"]["accum-scene"]
    data["v16"][0], data["v17"][0] = 16777217.0, 16777216.0
    source = first_image(ee)
    payload = source_array(ee, source, ARRAY_BANDS[:2], (2,), "payload")
    keys = source_array(ee, source, ARRAY_BANDS[16:18], (2,), "keys")
    _, actual, _ = compile_raster(ee, payload.arraySort(keys).arrayFlatten([["a", "b"]]), local)
    assert data["v16"][0] > data["v17"][0]
    assert np.float32(data["v16"][0]) == np.float32(data["v17"][0])
    np.testing.assert_array_equal(actual[:, 0], [data["v00"][0], data["v01"][0]])


def test_array_sort_supports_downstream_slice_and_reduction(ee, local):
    bands, shape = ARRAY_BANDS[:4], (4,)
    payload = source_array(ee, first_image(ee), bands, shape)
    # A trimmed mean from the middle two ordered observations.
    trimmed = payload.arraySort().arraySlice(0, 1, 3)
    output = trimmed.arrayReduce(ee.Reducer.mean(), [0]).arrayGet([0])
    _, actual, names = compile_raster(ee, output, local)
    values = source_values(local, bands, shape)
    valid = valid_samples(local, bands)
    expected = np.full((1, len(valid)), np.nan)
    for sample in np.flatnonzero(valid):
        ordered = sorted(values[sample].tolist())
        expected[0, sample] = float(np.float32((ordered[1] + ordered[2]) / 2))
    np.testing.assert_array_equal(actual, expected)
    assert names == ["array"]
