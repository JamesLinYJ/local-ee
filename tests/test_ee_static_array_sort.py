"""Bounded static Array.sort semantics and official SDK serialization."""
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine import array_sort
from gee.compat.earthengine.array_core import StaticArray, wrap_array
from gee.compat.earthengine.array_values import invoke_array
from gee.compat.earthengine.decoder import Translator
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


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


def typed(values, dtype=None):
    return wrap_array(np.asarray(values, dtype=dtype))


def invoke(array, keys=None, translator=None):
    arguments = {"array": array}
    if keys is not None:
        arguments["keys"] = keys
    return array_sort.invoke_static_sort(
        translator or Translator([], {}, None), "Array.sort", arguments,
    )


def sort_indices(keys):
    """Independent stable Python reference for a single key axis."""
    return sorted(range(len(keys)), key=lambda index: keys[index])


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def test_static_sort_uses_values_as_default_keys_and_stable_ascending_order():
    values = [5, 2, 2, -1, 9, 2]
    result = invoke(typed(values))
    expected = [values[index] for index in sort_indices(values)]
    assert result.to_value() == expected
    assert result.data.dtype == np.asarray(values).dtype

    with pytest.raises(UnsupportedEEError, match="one sort axis"):
        invoke(typed([[4, 1], [3, 2]]))


@pytest.mark.parametrize("values,keys,axis,expected", [
    (
        [[101, 102], [201, 202], [301, 302]],
        [[3], [1], [2]], 0,
        [[201, 202], [301, 302], [101, 102]],
    ),
    (
        [[11, 12, 13], [21, 22, 23]],
        [[20, 10, 30]], 1,
        [[12, 11, 13], [22, 21, 23]],
    ),
])
def test_external_keys_reorder_complete_rows_or_columns(values, keys, axis, expected):
    payload = typed(values, np.int16)
    key_array = typed(keys, np.float64)
    before = payload.data.copy()

    result = invoke(payload, key_array)

    assert array_sort.sort_axis(payload.data.shape, key_array.data.shape) == axis
    if axis == 0:
        order = sort_indices([row[0] for row in keys])
        reference = [values[index] for index in order]
    else:
        order = sort_indices(keys[0])
        reference = [[row[index] for index in order] for row in values]
    assert result.to_value() == expected == reference
    assert result.data.dtype == np.int16
    np.testing.assert_array_equal(payload.data, before)
    assert payload.data.flags.writeable is False
    assert result.data.flags.writeable is False
    assert not np.shares_memory(result.data, payload.data)


def test_duplicate_external_keys_keep_payloads_in_original_order():
    # Distinct payloads make stable local tie ordering directly observable.
    values = typed([[10], [20], [30], [40]])
    keys = typed([[3], [1], [1], [2]])
    result = invoke(values, keys)
    assert result.to_value() == [[20], [30], [40], [10]]


def test_scalar_and_single_cell_arrays_are_identity_values():
    scalar = typed(7)
    assert invoke(scalar).to_value() == 7
    singleton = typed([[8]])
    assert invoke(singleton, typed([[3]])).to_value() == [[8]]


def test_typed_empty_array_sorts_without_losing_its_shape_or_dtype():
    payload = typed(np.empty((0, 3), dtype=np.int16))
    keys = typed(np.empty((0, 1), dtype=np.float64))
    result = invoke(payload, keys)
    assert result.data.shape == (0, 3)
    assert result.data.dtype == np.int16
    assert result.data.flags.writeable is False
    assert not np.shares_memory(result.data, payload.data)

    empty_default = typed(np.empty((0, 1), dtype=np.float64))
    assert invoke(empty_default).data.shape == (0, 1)


def test_exact_integer_domain_and_finite_real_values_are_preserved():
    integers = [-(2**53), -3, 0, 2**53]
    result = invoke(typed(integers, np.int64))
    assert result.to_value() == sorted(integers)
    assert result.data.dtype == np.int64
    uint_boundary = StaticArray(np.asarray([2**53], dtype=np.uint64))
    assert invoke(uint_boundary).to_value() == [2**53]

    for invalid in (
        StaticArray(np.asarray([2**53 + 1], dtype=np.int64)),
        StaticArray(np.asarray([2**53 + 1], dtype=np.uint64)),
        StaticArray(np.asarray([1.0, np.nan])),
        StaticArray(np.asarray([1.0, np.inf])),
        StaticArray(np.asarray(["x"])),
    ):
        with pytest.raises(UnsupportedEEError, match="finite|exact Float64"):
            invoke(invalid)

    for invalid_key in (
        StaticArray(np.asarray([np.nan, 1.0])),
        StaticArray(np.asarray([np.inf, 1.0])),
        StaticArray(np.asarray([2**53 + 1, 0], dtype=np.int64)),
    ):
        with pytest.raises(UnsupportedEEError, match="finite|exact Float64"):
            invoke(typed([10, 20]), invalid_key)


@pytest.mark.parametrize("arguments,match", [
    (None, "arguments must be a dictionary"),
    ({}, "requires array"),
    ({"array": [1, 2]}, "static ee.Array"),
    ({"array": typed([2, 1]), "keys": [2, 1]}, "static ee.Array"),
    ({"array": typed([2, 1]), "ignored": 1}, "Unsupported algorithm arguments"),
])
def test_sort_rejects_malformed_or_untyped_arguments(arguments, match):
    with pytest.raises(UnsupportedEEError, match=match):
        array_sort.invoke_static_sort(
            Translator([], {}, None), "Array.sort", arguments,
        )


def test_static_sort_rejects_unknown_function_names():
    with pytest.raises(UnsupportedEEError, match="Unsupported static Array operation"):
        array_sort.invoke_static_sort(Translator([], {}, None), "Array.unknown", {})


@pytest.mark.parametrize("payload_shape,key_shape,match", [
    ((2, 3), (3,), "same rank"),
    ((2, 3), (2, 3), "one sort axis"),
    ((2, 3), (1, 1), "identify a sort axis"),
    ((2, 3), (4, 1), "must match"),
    ((0, 3), (0, 2), "one sort axis"),
    ((0, 3), (0, 3), "one sort axis"),
    ((3, 0), (0, 1), "must match"),
])
def test_sort_rejects_ambiguous_or_incompatible_key_shapes(
        payload_shape, key_shape, match):
    payload = typed(np.arange(np.prod(payload_shape)).reshape(payload_shape))
    keys = typed(np.arange(np.prod(key_shape)).reshape(key_shape))
    with pytest.raises(UnsupportedEEError, match=match):
        invoke(payload, keys)


def test_sort_accepts_rank_eight_and_rejects_rank_cell_or_work_overflow():
    rank_eight_values = np.asarray([2, 1]).reshape((2,) + (1,) * 7)
    rank_eight_result = invoke(typed(rank_eight_values))
    assert rank_eight_result.data.shape == (2,) + (1,) * 7
    assert rank_eight_result.data.reshape(-1).tolist() == [1, 2]

    rank_nine_shape = (1,) * 9
    rank_nine = StaticArray(np.ones(rank_nine_shape))
    with pytest.raises(UnsupportedEEError, match="rank <= 8"):
        invoke(rank_nine)

    too_many = StaticArray(np.ones((10_001,)))
    with pytest.raises(UnsupportedEEError, match="10000 cells"):
        invoke(too_many)

    at_cell_limit = typed(np.arange(10_000))
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke(at_cell_limit)


def test_sort_precharges_shared_work_before_scanning_or_allocating(monkeypatch):
    payload = typed([3, 1, 2])
    translator = Translator([], {}, None)
    translator.steps = 49_999

    def forbidden(*args, **kwargs):
        raise AssertionError("sort executed before shared-work preflight")

    monkeypatch.setattr(array_sort.np, "argsort", forbidden)
    monkeypatch.setattr(array_sort.np, "take", forbidden)
    monkeypatch.setattr(array_sort, "_validate_values", forbidden)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke(payload, translator=translator)
    assert translator.steps == 49_999


def test_sort_result_remains_a_typed_static_array_for_downstream_operations():
    result = invoke(typed([[3, 1], [1, 3]]), typed([[2], [1]]))
    translator = Translator([], {}, None)
    lengths = invoke_array(translator, "Array.length", {"array": result})
    listed = invoke_array(translator, "Array.toList", {"array": result})
    assert lengths.to_value() == [2, 2]
    assert listed == [[1, 3], [3, 1]]


def test_official_sdk_serializes_and_evaluates_static_array_sort(ee):
    source = ee.Array([[101, 102], [201, 202], [301, 302]])
    keys = ee.Array([[3], [1], [2]])
    expression = encode(ee, source.sort(keys=keys))
    invocations = [
        node for _, node in expression["scope"]
        if isinstance(node, dict) and node.get("functionName") == "Array.sort"
    ]
    assert len(invocations) == 1
    assert set(invocations[0]["arguments"]) == {"array", "keys"}

    value = Translator([], {}, None).evaluate(expression)
    assert isinstance(value, StaticArray)
    assert value.to_value() == [[201, 202], [301, 302], [101, 102]]


def test_official_sdk_omits_default_keys_and_keeps_typed_empty_sort(ee):
    expression = encode(ee, ee.Array([3, 1, 2]).sort())
    invocation = next(
        node for _, node in expression["scope"]
        if isinstance(node, dict) and node.get("functionName") == "Array.sort"
    )
    assert set(invocation["arguments"]) == {"array"}
    result = Translator([], {}, None).evaluate(expression)
    assert isinstance(result, StaticArray)
    assert result.to_value() == [1, 2, 3]

    empty = ee.Array([7, 3]).slice(0, 0, 0).sort()
    empty_result = Translator([], {}, None).evaluate(encode(ee, empty))
    assert isinstance(empty_result, StaticArray)
    assert empty_result.data.shape == (0,)
