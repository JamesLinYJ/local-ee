"""Declared-schema resolution for inline and sampled classifier training."""
from __future__ import annotations

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, SampledFeatures, UnsupportedEEError
from gee.compat.earthengine.minimum_distance import invoke_classifier as invoke_minimum_distance
from gee.compat.earthengine.smile_rf import invoke_classifier as invoke_smile_rf
from gee.compat.earthengine.training_schema import resolve_input_properties
from gee.image_sampling_spec import prepare_image_sample_spec
from gee.random_column_spec import prepare_random_column_spec
from gee.sampling_spec import prepare_sampling_spec
from gee.smile_rf_spec import decode_rf_spec


POINT = {"type": "Point", "coordinates": [0.5, 0.5]}


def translator():
    return Translator([], {}, {})


def inline_collection(order=("nir", "label", "red")):
    rows = [
        (0, 0.1, 0.2), (0, 0.2, 0.3),
        (1, 0.8, 0.7), (1, 0.9, 0.8),
    ]
    return {
        "type": "FeatureCollection",
        "properties": {"band_order": list(order)},
        "features": [
            {"type": "Feature", "geometry": None, "properties": {
                "label": label, "nir": nir, "red": red,
            }}
            for label, nir, red in rows
        ],
    }


def train_minimum_distance(features, **overrides):
    arguments = {
        "classifier": invoke_minimum_distance(
            translator(), "Classifier.minimumDistance", {},
        ),
        "features": features,
        "classProperty": "label",
    }
    arguments.update(overrides)
    return invoke_minimum_distance(translator(), "Classifier.train", arguments)


def train_smile_rf(features, **overrides):
    arguments = {
        "classifier": invoke_smile_rf(
            translator(), "Classifier.smileRandomForest", {"numberOfTrees": 3},
        ),
        "features": features,
        "classProperty": "label",
    }
    arguments.update(overrides)
    return invoke_smile_rf(translator(), "Classifier.train", arguments)


@pytest.mark.parametrize("mode", ["omitted", "null"])
def test_both_trainers_resolve_exact_inline_order_without_dropping_class_property(mode):
    features = inline_collection()
    overrides = {} if mode == "omitted" else {"inputProperties": None}

    minimum_distance = train_minimum_distance(features, **overrides)
    random_forest = train_smile_rf(features, **overrides)

    expected = ("nir", "label", "red")
    assert minimum_distance.schema == expected
    assert random_forest.schema == expected
    spec = decode_rf_spec(random_forest.training_spec)
    assert spec["schema"] == list(expected)
    assert spec["class_property"] == "label"


def test_explicit_schema_overrides_malformed_metadata_and_empty_is_not_auto():
    features = inline_collection()
    features["properties"]["band_order"] = "not a list"
    assert train_minimum_distance(features, inputProperties=["red"]).schema == ("red",)
    assert train_smile_rf(features, inputProperties=["red"]).schema == ("red",)

    empty = []
    assert resolve_input_properties(translator(), object(), empty) is empty
    with pytest.raises(UnsupportedEEError, match="inputProperties"):
        train_minimum_distance(features, inputProperties=[])
    with pytest.raises(UnsupportedEEError, match="inputProperties"):
        train_smile_rf(features, inputProperties=[])


@pytest.mark.parametrize("metadata", [
    {},
    {"band_order": None},
    {"band_order": ()},
    {"band_order": []},
    {"band_order": ["nir"] * 9},
    {"band_order": ["nir", "nir"]},
    {"band_order": ["nir.with.dot"]},
    {"band_order": ["nir\0band"]},
    {"band_order": ["system:index"]},
    {"band_order": [".geo"]},
    {"band_order": ["x" * 257]},
    {"band_order": [chr(0xD800)]},
    {"band_order": [1]},
])
def test_inline_automatic_schema_rejects_missing_or_invalid_declarations(metadata):
    collection = {"type": "FeatureCollection", "features": [], "properties": metadata}
    with pytest.raises(UnsupportedEEError, match="Automatic|band_order"):
        resolve_input_properties(translator(), collection, None)


def test_inline_auto_requires_actual_metadata_dictionary_but_never_reads_rows():
    with pytest.raises(UnsupportedEEError, match="metadata must be a dictionary"):
        resolve_input_properties(translator(), {
            "type": "FeatureCollection", "features": [], "properties": None,
        }, None)
    collection = {
        "type": "FeatureCollection", "features": [],
        "properties": {"band_order": ["red", "nir"]},
    }
    result = resolve_input_properties(translator(), collection, None)
    assert result == ["red", "nir"]
    assert result is not collection["properties"]["band_order"]
    result.reverse()
    assert collection["properties"]["band_order"] == ["red", "nir"]


def test_sampled_v2_uses_origin_band_order_after_random_column_overwrite():
    spec = prepare_image_sample_spec(
        POINT,
        ["red", "nir"], factor=1,
    )
    operation = prepare_random_column_spec(
        column_name="red", seed=19, row_keys=["system:index"],
    )
    sampled = SampledFeatures(Image([], {}), spec, (operation,))

    assert resolve_input_properties(translator(), sampled, None) == ["red", "nir"]


def test_sampled_v1_requires_explicit_schema_and_explicit_bypasses_metadata():
    regions = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": POINT, "properties": {"label": 1}}
    ]}
    sampled = SampledFeatures(
        Image([], {}), prepare_sampling_spec(
            regions, ["nir", "red"], properties=["label"],
        ),
    )
    with pytest.raises(UnsupportedEEError, match="SampleRegions v1.*requires inputProperties"):
        resolve_input_properties(translator(), sampled, None)

    with pytest.raises(UnsupportedEEError, match="SampleRegions v1.*requires inputProperties"):
        train_minimum_distance(sampled)
    with pytest.raises(UnsupportedEEError, match="SampleRegions v1.*requires inputProperties"):
        train_smile_rf(sampled)

    explicit = ["red"]
    assert resolve_input_properties(translator(), sampled, explicit) is explicit
    assert train_minimum_distance(sampled, inputProperties=explicit).schema == ("red",)
    assert train_smile_rf(sampled, inputProperties=explicit).schema == ("red",)


def test_automatic_schema_precharges_scans_before_validation_copy_work():
    compiler = translator()
    compiler.steps = 49_998
    collection = {
        "type": "FeatureCollection", "features": [],
        "properties": {"band_order": ["nir"]},
    }
    with pytest.raises(UnsupportedEEError, match="Static Array operation.*budget"):
        resolve_input_properties(compiler, collection, None)
    assert compiler.steps == 49_999
