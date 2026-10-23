"""Pinned-SDK compiler coverage for actual Smile RandomForest graphs."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from gee.smile_rf_spec import decode_rf_rows, decode_rf_spec
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
EXTENT = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
}
ROI = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
}


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield guard
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
    catalog = [{
        "id": "sentinel-2-l2a",
        "cube:dimensions": {"bands": {"values": ["red", "nir", "extra"]}},
    }]
    items = {"sentinel-2-l2a": [
        {
            "id": "training-scene", "bbox": [0, 0, 2, 2], "geometry": EXTENT,
            "properties": {"system:index": "training-scene", "kind": "training"},
        },
        {
            "id": "target-a", "bbox": [0, 0, 2, 2], "geometry": EXTENT,
            "properties": {"system:index": "target-a", "kind": "target"},
        },
        {
            "id": "target-b", "bbox": [0, 0, 2, 2], "geometry": EXTENT,
            "properties": {"system:index": "target-b", "kind": "target"},
        },
    ]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def rf(ee, **changes):
    parameters = {
        "numberOfTrees": 7,
        "variablesPerSplit": 1,
        "minLeafPopulation": 1,
        "bagFraction": 0.75,
        "maxNodes": 9,
        "seed": -17,
    }
    parameters.update(changes)
    return ee.Classifier.smileRandomForest(**parameters)


def literal_features(ee):
    return ee.FeatureCollection([
        ee.Feature(None, {"label": 0, "nir": 0.2, "red": 0.1}),
        ee.Feature(None, {"label": 0, "nir": 0.3, "red": 0.2}),
        ee.Feature(None, {"label": 1, "nir": 0.8, "red": 0.7}),
        ee.Feature(None, {"label": 1, "nir": 0.9, "red": 0.6}),
    ])


def sample_regions(ee):
    regions = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([0.5, 0.5]), {"label": 0}),
        ee.Feature(ee.Geometry.Point([1.5, 1.5]), {"label": 1}),
    ])
    return ee.Image("training-scene").select(["red", "nir"]).sampleRegions(
        collection=regions, properties=["label"], geometries=False,
        scale=10, projection=ee.Projection("EPSG:32610"),
    ).limit(10)


def process_nodes(result, process_id):
    return [(key, node) for key, node in result["process_graph"].items()
            if node["process_id"] == process_id]


def serialized_function_names(value):
    names, pending = [], [value]
    while pending:
        current = pending.pop()
        if type(current) is dict:
            if type(current.get("functionName")) is str:
                names.append(current["functionName"])
            pending.extend(current.values())
        elif type(current) is list:
            pending.extend(current)
        elif type(current) is tuple:
            pending.extend(current)
    return names


def test_official_sdk_serializes_and_compiler_builds_static_rows_to_rf_classification(ee, local):
    classifier = rf(ee).setOutputMode("CLASSIFICATION").train(
        features=literal_features(ee), classProperty="label",
        inputProperties=["nir", "red"],
    )
    assert compile_expression(
        encode(ee, classifier.schema()), local[0], local[1],
    )["value"] == ["nir", "red"]
    expression = encode(
        ee, ee.Image("target-a").select(["extra", "red", "nir"]).classify(
            classifier, outputName="landcover",
        ),
    )
    assert "Image.classify" in serialized_function_names(expression)
    result = compile_expression(expression, local[0], local[1])

    assert result["kind"] == "image"
    assert result["bands"] == ["landcover"]
    assert result["source_item_ids"] == ["target-a"]
    trainers = process_nodes(result, "local_ee_train_smile_rf_rows")
    predictors = process_nodes(result, "local_ee_smile_rf")
    assert len(trainers) == len(predictors) == 1
    trainer_id, trainer = trainers[0]
    _, predictor = predictors[0]
    assert set(trainer["arguments"]) == {"rows", "spec"}
    spec = decode_rf_spec(trainer["arguments"]["spec"])
    assert {key: spec[key] for key in (
        "number_of_trees", "variables_per_split", "min_leaf_population",
        "bag_fraction", "max_nodes", "seed",
    )} == {
        "number_of_trees": 7, "variables_per_split": 1,
        "min_leaf_population": 1, "bag_fraction": 0.75,
        "max_nodes": 9, "seed": -17,
    }
    assert spec["schema"] == ["nir", "red"]
    assert spec["class_property"] == "label"
    assert decode_rf_rows(trainer["arguments"]["rows"], spec)["rows"] == [
        [0, [0.2, 0.1]], [0, [0.3, 0.2]],
        [1, [0.8, 0.7]], [1, [0.9, 0.6]],
    ]
    assert predictor["arguments"]["model"] == {"from_node": trainer_id}
    validate(result["process_graph"])


def test_static_sdk_rows_normalize_integral_float_labels_and_allow_label_input(ee, local):
    features = ee.FeatureCollection([
        ee.Feature(None, {"label": 0.0, "nir": 0.1}),
        ee.Feature(None, {"label": 0.0, "nir": 0.2}),
        ee.Feature(None, {"label": 1.0, "nir": 0.8}),
        ee.Feature(None, {"label": 1.0, "nir": 0.9}),
    ])
    classifier = rf(ee).train(
        features=features, classProperty="label", inputProperties=["nir"],
    )
    expression = encode(ee, ee.Image("target-a").select("nir").classify(classifier))
    result = compile_expression(expression, local[0], local[1])
    trainer = process_nodes(result, "local_ee_train_smile_rf_rows")[0][1]
    spec = decode_rf_spec(trainer["arguments"]["spec"])

    assert spec["schema"] == ["nir"]
    assert decode_rf_rows(trainer["arguments"]["rows"], spec)["rows"] == [
        [0, [0.1]], [0, [0.2]], [1, [0.8]], [1, [0.9]],
    ]
    validate(result["process_graph"])

    label_as_input = rf(ee).train(
        features=features, classProperty="label", inputProperties=["label"],
    )
    assert compile_expression(
        encode(ee, label_as_input.schema()), local[0], local[1],
    )["value"] == ["label"]


def test_classification_keeps_explicit_float64_input_on_the_native_rf_path(ee, local):
    classifier = rf(ee).train(
        features=literal_features(ee), classProperty="label",
        inputProperties=["nir", "red"],
    )
    image = ee.Image("target-a").select(["red", "nir"]).toDouble().classify(classifier)
    result = compile_expression(encode(ee, image), local[0], local[1])

    assert any(node["process_id"] == "local_ee_to_double"
               for node in result["process_graph"].values())
    assert len(process_nodes(result, "local_ee_smile_rf")) == 1
    validate(result["process_graph"])


def test_fixed_sample_grid_and_source_survive_mapped_target_classification(ee, local):
    classifier = rf(ee).train(
        features=sample_regions(ee), classProperty="label",
        inputProperties=["nir", "red"],
    )
    target = ee.ImageCollection("sentinel-2-l2a").filter(
        ee.Filter.eq("kind", "target"),
    ).map(lambda image: image.select(["extra", "nir", "red"]).classify(
        classifier, outputName="landcover",
    ))
    result = compile_expression(
        encode(ee, target), local[0], local[1],
        options={"region": ROI, "scale": 2, "crs": "EPSG:3857"},
    )

    assert result["kind"] == "collection"
    assert result["bands"] == ["landcover"]
    assert set(result["source_item_ids"]) == {"training-scene", "target-a", "target-b"}
    samplers = process_nodes(result, "local_ee_sample_regions")
    operations = process_nodes(result, "local_ee_sample_table_op")
    trainers = process_nodes(result, "local_ee_train_smile_rf_samples")
    predictors = process_nodes(result, "local_ee_smile_rf")
    assert len(samplers) == len(operations) == len(trainers) == len(predictors) == 1
    sampler_id, sampler = samplers[0]
    operation_id, operation = operations[0]
    trainer_id, trainer = trainers[0]
    _, predictor = predictors[0]
    assert operation["arguments"]["data"] == {"from_node": sampler_id}
    assert trainer["arguments"]["data"] == {"from_node": operation_id}
    assert predictor["arguments"]["model"] == {"from_node": trainer_id}
    spec = decode_rf_spec(trainer["arguments"]["spec"])
    assert spec["schema"] == ["nir", "red"]
    assert spec["class_property"] == "label"
    assert sampler["arguments"]["spec"]

    loads = [node["arguments"] for node in result["process_graph"].values()
             if node["process_id"] == "load_collection"]
    by_ids = {tuple(load["_gee_item_ids"]): load for load in loads}
    assert by_ids[("training-scene",)]["bands"] == ["red", "nir"]
    assert by_ids[("training-scene",)]["spatial_extent"] == {
        "west": 0, "south": 0, "east": 2, "north": 2,
    }
    assert by_ids[("target-a", "target-b")]["bands"] == ["red", "nir"]
    assert by_ids[("target-a", "target-b")]["spatial_extent"] == {
        "west": 0, "south": 0, "east": 1, "north": 1,
    }
    grids = [node["arguments"] for node in result["process_graph"].values()
             if node["process_id"] == "resample_spatial"]
    assert any(grid.get("resolution") == 10 and grid.get("projection") == 32610
               for grid in grids)
    assert any(grid.get("resolution") == 2 and grid.get("projection") == 3857
               for grid in grids)
    validate(result["process_graph"])


@pytest.mark.parametrize("parameters", [
    {"numberOfTrees": 0},
    {"numberOfTrees": 257},
    {"numberOfTrees": 2, "variablesPerSplit": 0},
    {"numberOfTrees": 2, "minLeafPopulation": 0},
    {"numberOfTrees": 2, "bagFraction": 0},
    {"numberOfTrees": 2, "bagFraction": 1.01},
    {"numberOfTrees": 2, "maxNodes": 1},
    {"numberOfTrees": 2, "seed": 2**31},
])
def test_constructor_rejects_out_of_contract_parameters(ee, local, parameters):
    classifier = ee.Classifier.smileRandomForest(**parameters)
    value = encode(ee, classifier.schema())
    with pytest.raises(UnsupportedEEError):
        compile_expression(value, local[0], local[1])


@pytest.mark.parametrize("changes", [
    {"subsampling": 0.5},
    {"subsamplingSeed": 2},
])
def test_train_rejects_unimplemented_subsampling(ee, local, changes):
    args = {
        "features": literal_features(ee), "classProperty": "label",
        "inputProperties": ["nir", "red"], **changes,
    }
    classifier = rf(ee).train(**args)
    with pytest.raises(UnsupportedEEError, match="subsampling"):
        compile_expression(encode(ee, classifier.schema()), local[0], local[1])


def test_unsupported_rf_modes_and_result_consumers_remain_rejected(ee, local):
    classifier = rf(ee).train(
        features=literal_features(ee), classProperty="label",
        inputProperties=["nir", "red"],
    )
    for value in (
        rf(ee).setOutputMode("PROBABILITY").schema(),
        rf(ee),
        ee.Image("target-a").classify(rf(ee)),
        classifier,
        classifier.confusionMatrix(),
        classifier.explain(),
    ):
        with pytest.raises(UnsupportedEEError):
            compile_expression(encode(ee, value), local[0], local[1])


@pytest.mark.parametrize("features", [
    [],
    [{"label": 0, "nir": 0.1}],
    [{"label": 0, "nir": 0.1}, {"label": 0, "nir": 0.2}],
    [
        {"label": 0, "nir": 0.1},
        {"label": 2, "nir": 0.9},
    ],
    [
        {"label": 0, "nir": 0.1},
        {"label": 1, "nir": float("inf")},
    ],
    [
        {"label": 0, "nir": 0.1},
        {"label": 1, "nir": sys.float_info.max},
    ],
])
def test_static_rf_rows_reject_invalid_row_count_classes_and_values(ee, local, features):
    collection = ee.FeatureCollection([
        ee.Feature(None, values) for values in features
    ])
    classifier = rf(ee).train(
        features=collection, classProperty="label", inputProperties=["nir"],
    )
    with pytest.raises(UnsupportedEEError):
        compile_expression(encode(ee, classifier.schema()), local[0], local[1])


def test_rf_optional_input_properties_overload_requires_preserved_collection_metadata(ee, local):
    # earthengine-api 1.7.49's GeoJSON FeatureCollection constructor keeps only
    # `features`; collection-level `properties.band_order` is not serialized.
    collection_geojson = {
        "type": "FeatureCollection",
        "properties": {"band_order": ["nir"]},
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {"label": 0, "nir": 0.2, "red": 0.1,
                               "swir": 0.3, "green": 0.4},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1, 1]},
                "properties": {"label": 1, "nir": 0.8, "red": 0.7,
                               "swir": 0.6, "green": 0.5},
            },
        ],
    }
    collection = ee.FeatureCollection(collection_geojson)
    encoded_collection = encode(ee, collection)
    assert "band_order" not in str(encoded_collection)

    classifier = rf(ee).train(features=collection, classProperty="label")
    with pytest.raises(UnsupportedEEError, match="Classifier.train requires inputProperties"):
        compile_expression(encode(ee, classifier.schema()), local[0], local[1])

    # Explicit collection metadata survives serialization and now authorizes
    # the documented optional-input overload without guessing row fields.
    with_collection_metadata = ee.FeatureCollection([
        ee.Feature(None, {"label": 0, "nir": 0.2}),
        ee.Feature(None, {"label": 1, "nir": 0.8}),
    ]).set("band_order", ["nir"])
    metadata_expression = encode(ee, rf(ee).train(
        features=with_collection_metadata, classProperty="label",
    ).schema())
    assert "Element.set" in serialized_function_names(metadata_expression)
    assert compile_expression(metadata_expression, local[0], local[1])["value"] == ["nir"]

    # Legacy sampleRegions v1 has no declared collection band_order metadata.
    sampled_classifier = rf(ee).train(
        features=sample_regions(ee), classProperty="label",
    )
    with pytest.raises(UnsupportedEEError, match="Classifier.train requires inputProperties"):
        compile_expression(encode(ee, sampled_classifier.schema()), local[0], local[1])
