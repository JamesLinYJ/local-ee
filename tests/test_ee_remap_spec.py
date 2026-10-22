"""Canonical numeric remap wire and finite-value boundaries."""
from __future__ import annotations

import json

import pytest

from gee.remap_spec import MAX_ENTRIES, decode_remap_spec, prepare_remap_spec
from gee.sampling_spec import MAX_BYTES, encode_spec


def _spec(from_values, to_values, default=None):
    return encode_spec({
        "version": 1,
        "from": from_values,
        "to": to_values,
        "default": default,
    })


def test_remap_preparation_is_canonical_and_does_not_mutate_input_lists():
    source = [0, 1.5, 2**53]
    target = [9.0, -3, 0]
    source_before, target_before = source.copy(), target.copy()

    text = prepare_remap_spec(source, target, default=0)
    spec = decode_remap_spec(text)

    assert text == encode_spec(json.loads(text))
    assert spec == {
        "version": 1,
        "from": source_before,
        "to": target_before,
        "default": 0,
    }
    assert source == source_before
    assert target == target_before


def test_remap_accepts_empty_pairs_and_the_256_entry_boundary():
    empty = decode_remap_spec(prepare_remap_spec([], [], default=None))
    assert empty == {"version": 1, "from": [], "to": [], "default": None}

    source = list(range(MAX_ENTRIES))
    # Target values need not be unique; duplicate outputs are a real remap.
    target = [7] * MAX_ENTRIES
    decoded = decode_remap_spec(prepare_remap_spec(source, target))
    assert len(decoded["from"]) == MAX_ENTRIES
    assert decoded["to"] == target

    with pytest.raises(ValueError, match="0..256"):
        prepare_remap_spec(source + [MAX_ENTRIES], target + [7])


@pytest.mark.parametrize("source", [
    [0, -0.0],
    [1, 1.0],
    [-0.0, 0.0],
])
def test_remap_rejects_numerically_duplicate_source_keys(source):
    with pytest.raises(ValueError, match="numerically unique"):
        prepare_remap_spec(source, list(range(len(source))))


@pytest.mark.parametrize("from_values, to_values", [
    ([1], []),
    (None, []),
    ((), ()),
    ([True], [1]),
    ([1], [False]),
    ([[]], [1]),
    ([{}], [1]),
])
def test_remap_requires_equal_length_lists_of_numeric_scalars(from_values, to_values):
    with pytest.raises(ValueError):
        prepare_remap_spec(from_values, to_values)


@pytest.mark.parametrize("value", [
    True,
    False,
    None,
    float("nan"),
    float("inf"),
    float("-inf"),
    2**53 + 1,
    -(2**53 + 1),
    "1",
    [1],
    {"value": 1},
])
def test_remap_rejects_non_numeric_or_nonfinite_from_to_values(value):
    with pytest.raises(ValueError, match="finite numbers"):
        prepare_remap_spec([value], [1])


@pytest.mark.parametrize("default", [
    True,
    False,
    float("nan"),
    float("inf"),
    2**53 + 1,
    "1",
    [1],
    {"value": 1},
])
def test_remap_rejects_invalid_defaults(default):
    with pytest.raises(ValueError, match="finite numbers"):
        prepare_remap_spec([1], [2], default=default)


def test_remap_accepts_finite_float64_and_exact_integer_endpoints():
    text = prepare_remap_spec(
        [-2**53, 2**53, 1.0e300],
        [-(1.0e300), 1.0e300, -1.0e300],
        default=-0.0,
    )
    decoded = decode_remap_spec(text)
    assert decoded["from"] == [-2**53, 2**53, 1.0e300]
    assert decoded["default"] == -0.0


@pytest.mark.parametrize("spec, message", [
    ({"version": True, "from": [], "to": [], "default": None}, "version1"),
    ({"version": 2, "from": [], "to": [], "default": None}, "version1"),
    ({"version": 1, "from": [], "to": []}, "version1"),
    ({"version": 1, "from": [], "to": [], "default": None, "extra": 1}, "version1"),
])
def test_remap_decoder_requires_exact_versioned_fields(spec, message):
    with pytest.raises(ValueError, match=message):
        decode_remap_spec(encode_spec(spec))


def test_remap_decoder_rejects_duplicate_keys_noncanonical_json_and_nonfinite_tokens():
    text = prepare_remap_spec([1], [2])
    with pytest.raises(ValueError, match="Duplicate specification key"):
        decode_remap_spec(text[:-1] + ',"version":1}')
    with pytest.raises(ValueError, match="canonical"):
        decode_remap_spec(text + " ")
    with pytest.raises(ValueError, match="finite JSON"):
        decode_remap_spec(text.replace('"from":[1]', '"from":[NaN]'))


def test_remap_decoder_rejects_wrong_input_types_and_oversized_json():
    for value in (None, {}, [1], 3):
        with pytest.raises(ValueError):
            decode_remap_spec(value)
    with pytest.raises(ValueError, match="bounded"):
        decode_remap_spec(" " * (MAX_BYTES + 1))
