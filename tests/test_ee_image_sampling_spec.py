"""Versioned sample options stay bounded data; v1 remains a separate contract."""
from __future__ import annotations

import copy

import pytest

from ee_sampling_contract_helpers import POINT, _sample_text
from gee.image_sampling_spec import (
    allows_null_samples, decode_image_sample_spec, grid_random,
    is_image_sample, prepare_image_sample_spec, sample_collection_properties,
    validate_image_sample_spec,
)
from gee.sampling_spec import decode_sampling_spec, encode_spec, sampling_columns


def spec(**options):
    return decode_sampling_spec(prepare_image_sample_spec(POINT, ["nir", "red"], **options))


def test_image_sample_defaults_exact_schema_and_sdk_integer_normalization():
    value = spec(num_pixels=7.0, seed=-2.0)
    assert value["version"] == 2 and is_image_sample(value)
    assert value["regions"] == {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": POINT, "properties": {}}]}
    assert value["properties"] == []
    assert value["image_sample"] == {
        "algorithm": "splitmix64-grid-v1", "factor": None,
        "num_pixels": 7, "seed": -2, "drop_nulls": True}
    assert type(value["image_sample"]["seed"]) is int
    assert sampling_columns(value) == ["system:index", "nir", "red", ".geo"]
    assert decode_image_sample_spec(encode_spec(value)) == value
    assert not allows_null_samples(value)
    metadata = sample_collection_properties(value)
    metadata["band_order"].reverse()
    assert value["bands"] == ["nir", "red"]
    old = decode_sampling_spec(_sample_text())
    assert not is_image_sample(old) and not allows_null_samples(old)
    assert sample_collection_properties(old) == {}
    with pytest.raises(ValueError):
        decode_image_sample_spec(encode_spec(old))


@pytest.mark.parametrize("kwargs", [
    {"factor": 0}, {"factor": -1}, {"factor": 1.001}, {"factor": True},
    {"factor": float("nan")}, {"factor": float("inf")}, {"factor": 10**400},
    {"factor": 1, "num_pixels": 0}, {"factor": .5, "num_pixels": 3},
    {"num_pixels": -1}, {"num_pixels": 1001}, {"num_pixels": True},
    {"num_pixels": 1.5}, {"seed": True}, {"seed": 2**31},
    {"seed": -(2**31) - 1}, {"seed": .25}, {"drop_nulls": 0},
    {"geometries": 1}, {"grid": {"scale": 1, "crs": "EPSG:4326"}},
])
def test_image_sample_rejects_invalid_options_before_any_pixels(kwargs):
    with pytest.raises(ValueError):
        spec(**kwargs)


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(version=True),
    lambda s: s.update(version=2.0),
    lambda s: s.update(extra="from_node"),
    lambda s: s["image_sample"].update(extra=True),
    lambda s: s["image_sample"].pop("factor"),
    lambda s: s["image_sample"].update(algorithm="other"),
    lambda s: s["image_sample"].update(seed=1.0),
    lambda s: s["image_sample"].update(num_pixels=3.0),
    lambda s: s["regions"]["features"].append(copy.deepcopy(s["regions"]["features"][0])),
    lambda s: s["regions"].update(features=[]),
    lambda s: s["regions"]["features"][0].update(id="copied"),
    lambda s: s["regions"]["features"][0]["properties"].update(label=1),
    lambda s: s.update(bands=["red", "red"]),
    lambda s: s.update(properties=["label"]),
])
def test_strict_wire_decoder_does_not_accept_prepare_only_coercions(mutation):
    value = spec()
    mutation(value)
    with pytest.raises(ValueError):
        decode_sampling_spec(encode_spec(value))


def test_wire_is_canonical_duplicate_free_and_bounded():
    text = encode_spec(spec())
    for invalid in (text + " ", text[:-1] + ',"version":2}',
                    text.replace('"factor":null', '"factor":NaN')):
        with pytest.raises(ValueError):
            decode_sampling_spec(invalid)
    with pytest.raises(ValueError, match="1 MB"):
        validate_image_sample_spec({**spec(), "bands": ["x" * 1_000_001]})
    assert spec(num_pixels=0)["image_sample"]["num_pixels"] == 0
    assert spec(num_pixels=1000, seed=-(2**31))["image_sample"]["seed"] == -(2**31)
    assert spec(factor=1, seed=2**31 - 1)["image_sample"]["factor"] == 1


def test_hash_matches_independently_spelled_unsigned_reference_and_global_indices():
    def reference(seed, column, row):
        modulus = 2**64

        def scramble(x):
            x %= modulus
            x = ((x ^ (x // 2**30)) * 13787848793156543929) % modulus
            x = ((x ^ (x // 2**27)) * 10723151780598845931) % modulus
            return x ^ (x // 2**31)

        h = scramble((seed % modulus) ^ scramble(column + 11400714819323198485)
                     ^ scramble(row + 15111065706836454659))
        return (h // 2**11) / 2**53

    values = []
    for seed in (-(2**31), -1, 0, 1, 2**31 - 1):
        for col, row in ((0, 0), (1, 2), (255, 256), (2**32, 2**53)):
            actual = grid_random(seed, col, row)
            assert actual == reference(seed, col, row)
            assert 0 <= actual < 1
            values.append(actual)
    assert len(set(values)) == len(values)
    for args in ((True, 0, 0), (0, -1, 0), (0, 0, 2**53 + 1)):
        with pytest.raises(ValueError):
            grid_random(*args)
