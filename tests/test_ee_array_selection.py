"""Pinned SDK serialization and bounded static Array selection semantics."""
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine import array_selection
from gee.compat.earthengine.array_core import StaticArray, wrap_array
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


def invoke(name, arguments, translator=None):
    return array_selection.invoke_array_selection(
        translator or Translator([], {}, None), name, arguments,
    )


def encoded(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def invocation(expression, name):
    if isinstance(expression, dict) and expression.get("functionName") == name:
        return expression
    scope = expression.get("scope", []) if isinstance(expression, dict) else []
    matches = [
        node for _, node in scope
        if isinstance(node, dict) and node.get("functionName") == name
    ]
    assert len(matches) == 1
    return matches[0]


def resolve_sdk_value(expression, value):
    if isinstance(value, list):
        return [resolve_sdk_value(expression, item) for item in value]
    if not isinstance(value, dict) or value.get("type") != "ValueRef":
        return value
    scope = dict(expression["scope"])
    node = scope[value["value"]]
    if isinstance(node, dict) and node.get("functionName") == "Array":
        values = resolve_sdk_value(expression, node["arguments"]["values"])
        return wrap_array(np.asarray(values))
    return resolve_sdk_value(expression, node)


def evaluate_sdk_selection(ee, value, name):
    expression = encoded(ee, value)
    call = invocation(expression, name)
    arguments = {
        key: resolve_sdk_value(expression, item)
        for key, item in call["arguments"].items()
    }
    return invoke(name, arguments)


def expected_bits(value):
    if value < 0:
        encoded_value = value & ((1 << 64) - 1)
        width = 64
    else:
        width = max(1, value.bit_length())
        encoded_value = value
    return [
        (encoded_value >> shift) & 1
        for shift in range(width - 1, -1, -1)
    ]


def test_pinned_sdk_serializes_all_three_array_selection_algorithms(ee):
    bits = encoded(ee, ee.Array.bitsToArray(5))
    assert bits == {
        "type": "Invocation",
        "functionName": "Array.bitsToArray",
        "arguments": {"input": 5},
    }
    assert evaluate_sdk_selection(ee, ee.Array.bitsToArray(5), "Array.bitsToArray").to_value() == [1, 0, 1]

    cut_value = ee.Array([[0, 1, 2], [3, 4, 5]]).cut([-1, 1])
    cut = encoded(ee, cut_value)
    cut_call = invocation(cut, "Array.cut")
    assert set(cut_call["arguments"]) == {"array", "position"}
    cut_scope = dict(cut["scope"])
    assert cut_scope[cut_call["arguments"]["position"]["value"]] == [-1, 1]
    assert evaluate_sdk_selection(ee, cut_value, "Array.cut").to_value() == [[1], [4]]

    mask_value = ee.Array([1, 2, 3, 4]).mask(ee.Array([0, 1, 0, 1]))
    mask = encoded(ee, mask_value)
    mask_call = invocation(mask, "Array.mask")
    assert set(mask_call["arguments"]) == {"input", "mask"}
    mask_scope = dict(mask["scope"])
    for key in ("input", "mask"):
        reference = mask_call["arguments"][key]
        assert mask_scope[reference["value"]]["functionName"] == "Array"
    assert evaluate_sdk_selection(ee, mask_value, "Array.mask").to_value() == [2, 4]


@pytest.mark.parametrize("value", [0, 1, 5, 0xFF, 2**53, -1, -2, -(2**53)])
def test_bits_to_array_has_msb_first_zero_and_signed_negative_policy(value):
    result = invoke("Array.bitsToArray", {"input": value})
    assert result.to_value() == expected_bits(value)
    assert result.data.shape == (len(expected_bits(value)),)
    assert result.data.dtype == np.int64
    assert result.data.flags.writeable is False


@pytest.mark.parametrize("value", [
    True, False, 1.5, float("nan"), float("inf"), 2**53 + 1, -(2**53 + 1),
    [1], None,
])
def test_bits_to_array_rejects_non_integer_boolean_dynamic_or_inexact_inputs(value):
    with pytest.raises(UnsupportedEEError):
        invoke("Array.bitsToArray", {"input": value})


def test_bits_to_array_rejects_dynamic_sdk_numbers_and_malformed_arguments(ee):
    dynamic_number = ee.Number(1).add(2)
    with pytest.raises(UnsupportedEEError, match="finite integer Number"):
        invoke("Array.bitsToArray", {"input": dynamic_number})
    for arguments in ({}, {"input": 1, "extra": 2}, None):
        with pytest.raises(UnsupportedEEError):
            invoke("Array.bitsToArray", arguments)


def test_bits_to_array_precharges_before_output_allocation(monkeypatch):
    translator = Translator([], {}, None)
    translator.steps = 50_000

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Array.bitsToArray allocated before work preflight")

    monkeypatch.setattr(array_selection.np, "asarray", forbidden)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke("Array.bitsToArray", {"input": 5}, translator)
    assert translator.steps == 50_000


def test_cut_keeps_selected_axes_and_singletons_without_changing_dtype():
    source = typed([[0, 1, 2], [3, 4, 5]], np.int16)
    first = invoke("Array.cut", {"array": source, "position": [-1, 1]})
    second = invoke("Array.cut", {"array": source, "position": [1, -1]})
    whole = invoke("Array.cut", {"array": source, "position": [-1, -1]})

    assert first.to_value() == [[1], [4]]
    assert first.data.shape == (2, 1)
    assert second.to_value() == [[3, 4, 5]]
    assert second.data.shape == (1, 3)
    assert whole.to_value() == [[0, 1, 2], [3, 4, 5]]
    for result in (first, second, whole):
        assert result.data.dtype == np.int16
        assert result.data.flags.writeable is False
        assert not np.shares_memory(source.data, result.data)


def test_cut_handles_scalar_zero_axes_empty_shapes_and_rank_eight():
    scalar = typed(7, np.int16)
    scalar_result = invoke("Array.cut", {"array": scalar, "position": []})
    assert scalar_result.to_value() == 7
    assert scalar_result.data.shape == ()
    assert scalar_result.data.dtype == np.int16

    empty = typed(np.empty((0, 3), dtype=np.int16))
    empty_result = invoke("Array.cut", {"array": empty, "position": [-1, 1]})
    assert empty_result.to_value() == []
    assert empty_result.data.shape == (0, 1)
    assert empty_result.data.dtype == np.int16

    rank_eight = typed(np.asarray([9], dtype=np.int8).reshape((1,) * 8))
    rank_eight_result = invoke(
        "Array.cut", {"array": rank_eight, "position": [-1] * 8}
    )
    assert rank_eight_result.data.shape == (1,) * 8
    assert rank_eight_result.to_value() == rank_eight.to_value()


@pytest.mark.parametrize("positions", [
    None, (), [0], [0, 0, 0], [True, -1], [0.5, -1], [-2, -1], [2, -1],
])
def test_cut_rejects_malformed_boolean_negative_and_out_of_range_positions(positions):
    with pytest.raises(UnsupportedEEError):
        invoke("Array.cut", {"array": typed([[1, 2], [3, 4]]), "position": positions})


def test_cut_rejects_untyped_arrays_inexact_inputs_and_unknown_arguments():
    for arguments in (
        {"array": [[1, 2]], "position": [-1, -1]},
        {"array": typed([1, 2]), "position": [-1], "extra": 3},
    ):
        with pytest.raises(UnsupportedEEError):
            invoke("Array.cut", arguments)

    for invalid in (
        StaticArray(np.asarray([2**53 + 1], dtype=np.int64)),
        StaticArray(np.asarray([np.nan], dtype=np.float64)),
        StaticArray(np.ones((1,) * 9, dtype=np.int8)),
        StaticArray(np.ones((10_001,), dtype=np.int8)),
    ):
        with pytest.raises(UnsupportedEEError):
            invoke("Array.cut", {"array": invalid, "position": [-1] * invalid.data.ndim})


def test_cut_rejects_missing_arguments_and_dynamic_sdk_values(ee):
    dynamic_array = ee.Array([1, 2]).add(ee.Array([3, 4]))
    dynamic_position = ee.List([0])
    for arguments in (
        {}, {"array": typed([1, 2])}, {"position": [0]}, None,
        {"array": dynamic_array, "position": [-1]},
        {"array": typed([1, 2]), "position": dynamic_position},
    ):
        with pytest.raises(UnsupportedEEError):
            invoke("Array.cut", arguments)


def test_cut_precharges_before_value_scans_and_array_copy(monkeypatch):
    source = typed([1, 2, 3])
    translator = Translator([], {}, None)
    translator.steps = 49_999

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Array.cut scanned values before work preflight")

    monkeypatch.setattr(array_selection, "_validate_values", forbidden)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke("Array.cut", {"array": source, "position": [1]}, translator)
    assert translator.steps == 49_999


def test_mask_uses_nonzero_values_and_preserves_shape_dtype_and_readonly_ownership():
    source = typed([0, 1, 2, 3], np.int16)
    mask = typed([0, 4, -1, 1.2], np.float64)
    result = invoke("Array.mask", {"input": source, "mask": mask})
    assert result.to_value() == [1, 2, 3]
    assert result.data.shape == (3,)
    assert result.data.dtype == np.int16
    assert result.data.flags.writeable is False
    assert not np.shares_memory(result.data, source.data)

    row = invoke(
        "Array.mask",
        {"input": typed([[1, 2, 3, 4]], np.int8),
         "mask": typed([[1, 0, 1, 1]], np.int8)},
    )
    assert row.to_value() == [[1, 3, 4]]
    assert row.data.shape == (1, 3)
    assert row.data.dtype == np.int8

    column = invoke(
        "Array.mask",
        {"input": typed([[1], [2], [3], [4]], np.int16),
         "mask": typed([[1], [0], [1], [1]], np.int8)},
    )
    assert column.to_value() == [[1], [3], [4]]
    assert column.data.shape == (3, 1)
    assert column.data.dtype == np.int16


def test_mask_all_zero_and_typed_empty_inputs_preserve_documented_empty_shapes():
    row = invoke(
        "Array.mask",
        {"input": typed([[1, 2, 3, 4]]), "mask": typed([[0, 0, 0, 0]])},
    )
    assert row.to_value() == [[]]
    assert row.data.shape == (1, 0)

    singleton = invoke(
        "Array.mask", {"input": typed([1]), "mask": typed([0])}
    )
    assert singleton.to_value() == []
    assert singleton.data.shape == (0,)

    empty = typed(np.empty((0, 3), dtype=np.int16))
    empty_result = invoke("Array.mask", {"input": empty, "mask": typed(np.empty((0, 3)))})
    assert empty_result.data.shape == (0, 3)
    assert empty_result.data.dtype == np.int16
    assert empty_result.data.flags.writeable is False


def test_mask_supports_rank_eight_single_varying_axis_and_rejects_rank_or_cell_overflow():
    shape = (1, 1, 1, 3, 1, 1, 1, 1)
    source = typed(np.asarray([1, 2, 3], dtype=np.int16).reshape(shape))
    mask = typed(np.asarray([1, 0, 1], dtype=np.int8).reshape(shape))
    result = invoke("Array.mask", {"input": source, "mask": mask})
    assert result.data.shape == (1, 1, 1, 2, 1, 1, 1, 1)
    expected = np.asarray([1, 3], dtype=np.int16).reshape(result.data.shape)
    np.testing.assert_array_equal(result.data, expected)
    assert result.data.dtype == np.int16

    too_ranked = StaticArray(np.ones((1,) * 9, dtype=np.int8))
    with pytest.raises(UnsupportedEEError, match="rank exceeds 8"):
        invoke("Array.mask", {"input": too_ranked, "mask": too_ranked})

    too_large = StaticArray(np.ones((10_001,), dtype=np.int8))
    with pytest.raises(UnsupportedEEError, match="10000"):
        invoke("Array.mask", {"input": too_large, "mask": too_large})


@pytest.mark.parametrize("arguments", [
    {"input": typed([1, 2, 3]), "mask": typed([[1, 0, 1]])},
    {"input": typed([[1, 2, 3], [4, 5, 6]]),
     "mask": typed([[1, 0, 1], [1, 0, 1]])},
    {"input": typed([[1]]), "mask": typed([[1]])},
    {"input": [[1, 2]], "mask": typed([[1, 0]])},
    {"input": typed([1, 2]), "mask": [1, 0]},
    {"input": typed([1, 2]), "mask": typed([1, 0]), "extra": 1},
])
def test_mask_rejects_undocumented_broadcast_ambiguous_or_untyped_shapes(arguments):
    with pytest.raises(UnsupportedEEError):
        invoke("Array.mask", arguments)


def test_mask_rejects_nonfinite_boolean_and_inexact_arrays():
    valid = typed([1, 2])
    invalid_masks = (
        StaticArray(np.asarray([1, np.nan], dtype=np.float64)),
        StaticArray(np.asarray([1, np.inf], dtype=np.float64)),
        StaticArray(np.asarray([2**53 + 1, 0], dtype=np.int64)),
        StaticArray(np.asarray([True, False], dtype=np.bool_)),
    )
    for invalid in invalid_masks:
        with pytest.raises(UnsupportedEEError):
            invoke("Array.mask", {"input": valid, "mask": invalid})


def test_mask_rejects_missing_arguments_and_dynamic_sdk_arrays(ee):
    dynamic_array = ee.Array([1, 2]).add(ee.Array([3, 4]))
    static = typed([1, 2])
    for arguments in (
        {}, {"input": static}, {"mask": static}, None,
        {"input": dynamic_array, "mask": static},
        {"input": static, "mask": dynamic_array},
    ):
        with pytest.raises(UnsupportedEEError):
            invoke("Array.mask", arguments)


def test_mask_precharges_worst_case_output_before_scanning_or_copy(monkeypatch):
    source = typed(np.arange(5_000, dtype=np.int32))
    mask = typed(np.ones(5_000, dtype=np.int8))
    translator = Translator([], {}, None)
    translator.steps = 25_000

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Array.mask scanned values before work preflight")

    monkeypatch.setattr(array_selection, "_validate_values", forbidden)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke("Array.mask", {"input": source, "mask": mask}, translator)
    assert translator.steps == 25_000


def test_unknown_selection_function_is_rejected():
    with pytest.raises(UnsupportedEEError, match="Unsupported static Array selection"):
        invoke("Array.unknown", {})
