"""Collection-level metadata on bounded inline FeatureCollections."""
from pathlib import Path

import pytest

from gee.compat.earthengine import collection_metadata
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import (
    Function, Image, ImageSequence, Pixel, SampledFeatures, UnsupportedEEError,
)
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.table_graph import has_table_node, table_input_graph, validate_table_graph
from gee.table_values import columns, render_csv


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def compile_sdk(ee, value):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    result = compile_expression(expression, [], {})
    return result.get("value", result)


def collection(features=(), properties=None):
    value = {"type": "FeatureCollection", "features": list(features)}
    if properties is not None:
        value["properties"] = properties
    return value


def feature(properties=None):
    return {"type": "Feature", "geometry": None, "properties": properties or {}}


def test_element_metadata_methods_use_collection_properties_only(ee):
    source = ee.FeatureCollection([ee.Feature(None, {"band_order": ["wrong"]})]).setMulti({
        "band_order": ["nir", "red"],
        "nested": {"group": "collection", "values": [1, None]},
    })
    assert compile_sdk(ee, source.get("band_order")) == ["nir", "red"]
    assert compile_sdk(ee, source.propertyNames()) == ["band_order", "nested"]

    updated = source.set("tag", {"name": "local", "count": 2})
    updated = updated.setMulti({"band_order": ["red"], "active": True})
    output = compile_sdk(ee, updated)
    assert output["properties"] == {
        "band_order": ["red"],
        "nested": {"group": "collection", "values": [1, None]},
        "tag": {"name": "local", "count": 2},
        "active": True,
    }
    assert output["features"][0]["properties"] == {"band_order": ["wrong"]}


def test_copy_properties_reads_collection_metadata_and_keeps_default_system_filter(ee):
    source = ee.FeatureCollection([]).setMulti({
        "keep": {"nested": [1, 2]},
        "omit": "excluded",
        "system:time_start": 123,
    })
    destination = ee.FeatureCollection([ee.Feature(None, {"row": 7})]).set("own", "yes")

    copied = destination.copyProperties(source, properties=["keep", "missing"])
    assert compile_sdk(ee, copied)["properties"] == {
        "own": "yes", "keep": {"nested": [1, 2]},
    }
    excluded = destination.copyProperties(source, exclude=["omit"])
    assert compile_sdk(ee, excluded)["properties"] == {
        "own": "yes", "keep": {"nested": [1, 2]},
    }
    with pytest.raises(UnsupportedEEError, match="inline FeatureCollection source and destination"):
        compile_sdk(ee, destination.copyProperties(ee.Feature(None, {"keep": 1})))


def test_row_preserving_operations_keep_collection_properties_including_empty_results(ee):
    declared = {"band_order": ["nir", "red"], "origin": {"version": 2}}
    source = ee.FeatureCollection(ee.FeatureCollection([
        ee.Feature(None, {"row": "a", "keep": True}),
        ee.Feature(None, {"row": "b", "keep": False}),
    ]).setMulti(declared))
    expressions = [
        source.randomColumn("random", seed=13, rowKeys=["row"]),
        source.filter(ee.Filter.eq("keep", True)),
        source.limit(1),
        source.map(lambda item: item.set("mapped", True)),
        source.filter(ee.Filter.eq("keep", "absent")),
        source.limit(0),
        ee.FeatureCollection(ee.FeatureCollection([]).setMulti(declared)).map(
            lambda item: item.set("mapped", True)
        ),
    ]
    outputs = [compile_sdk(ee, expression) for expression in expressions]
    assert all(output["properties"] == declared for output in outputs)
    assert len(outputs[0]["features"]) == 2
    assert len(outputs[1]["features"]) == 1
    assert len(outputs[2]["features"]) == 1
    assert all(row["properties"]["mapped"] is True for row in outputs[3]["features"])
    assert outputs[4]["features"] == outputs[5]["features"] == outputs[6]["features"] == []


def test_static_minimum_distance_classification_preserves_collection_properties(ee):
    training = ee.FeatureCollection([
        ee.Feature(None, {"label": 0, "x": 0}),
        ee.Feature(None, {"label": 1, "x": 10}),
    ])
    classifier = ee.Classifier.minimumDistance().train(
        features=training, classProperty="label", inputProperties=["x"],
    )
    source = ee.FeatureCollection(ee.FeatureCollection([
        ee.Feature(None, {"x": 1}),
    ]).set("origin", {"name": "validation"}))
    output = compile_sdk(ee, source.classify(classifier, "predicted"))
    assert output["properties"] == {"origin": {"name": "validation"}}
    assert output["features"][0]["properties"]["predicted"] == 0


def test_map_to_images_stays_an_image_sequence(ee):
    source = collection([feature({"row": 1})], {"tag": "table"})
    image = Image([("constant", Pixel("constant", (5,)))], {})
    function = Function(["item"], image, {})
    result = Translator([], {}, {}).invoke("Collection.map", {
        "collection": source, "baseAlgorithm": function, "dropNulls": False,
    })
    assert isinstance(result, ImageSequence)
    assert result.images == [image]


def test_collection_metadata_copies_are_immutable_and_budgeted():
    source = collection([feature({"row": 1})], {"nested": {"values": [1]}})
    translator = Translator([], {}, {})
    result = translator.invoke("Element.set", {
        "object": source, "key": "added", "value": {"values": [2]},
    })
    assert result is not source
    assert result["features"] is not source["features"]
    assert result["properties"] is not source["properties"]
    assert result["properties"]["nested"] is not source["properties"]["nested"]
    result["properties"]["nested"]["values"].append(9)
    result["features"].clear()
    assert source["properties"] == {"nested": {"values": [1]}}
    assert len(source["features"]) == 1

    translator.steps = 49999
    with pytest.raises(UnsupportedEEError, match="50000-step compilation work budget"):
        translator.invoke("Element.setMulti", {
            "object": source, "properties": {"new": "value"},
        })
    assert source["properties"] == {"nested": {"values": [1]}}


def test_collection_metadata_get_returns_an_owned_nested_value():
    source = collection(properties={"nested": {"values": [1]}})
    translator = Translator([], {}, {})

    result = translator.invoke("Element.get", {
        "object": source, "property": "nested",
    })
    result["values"].append(2)

    assert result is not source["properties"]["nested"]
    assert source["properties"]["nested"] == {"values": [1]}


def test_metadata_get_reserves_nested_copy_before_deepcopy(monkeypatch):
    source = collection(properties={"nested": [1]})
    copied_ids = []
    original_deepcopy = collection_metadata.copy.deepcopy

    def deepcopy(value, *args, **kwargs):
        copied_ids.append(id(value))
        return original_deepcopy(value, *args, **kwargs)

    monkeypatch.setattr(collection_metadata.copy, "deepcopy", deepcopy)
    translator = Translator([], {}, {})
    translator.steps = 49970

    with pytest.raises(UnsupportedEEError, match="50000-step compilation work budget"):
        translator.invoke("Element.get", {
            "object": source, "property": "nested",
        })

    assert copied_ids == []
    assert source["properties"] == {"nested": [1]}


@pytest.mark.parametrize("kind", ["list", "string"])
def test_metadata_scan_reserves_budget_before_large_iteration_or_copy(monkeypatch, kind):
    payload = list(range(100)) if kind == "list" else "x" * 1000
    iterated_container_ids = []
    iterated_string_ids = []
    copied_ids = []
    original_container_iterator = collection_metadata._iter_json_container
    original_string_iterator = collection_metadata._string_characters
    original_deepcopy = collection_metadata.copy.deepcopy

    def container_iterator(value):
        iterated_container_ids.append(id(value))
        return original_container_iterator(value)

    def string_iterator(value):
        iterated_string_ids.append(id(value))
        return original_string_iterator(value)

    def deepcopy(value, *args, **kwargs):
        copied_ids.append(id(value))
        return original_deepcopy(value, *args, **kwargs)

    monkeypatch.setattr(collection_metadata, "_iter_json_container", container_iterator)
    monkeypatch.setattr(collection_metadata, "_string_characters", string_iterator)
    monkeypatch.setattr(collection_metadata.copy, "deepcopy", deepcopy)
    translator = Translator([], {}, {})
    translator.steps = 49980

    with pytest.raises(UnsupportedEEError, match="50000-step compilation work budget"):
        translator.invoke("Element.setMulti", {
            "object": collection(), "properties": {"blob": payload},
        })

    if kind == "list":
        assert id(payload) not in iterated_container_ids
    else:
        assert id(payload) not in iterated_string_ids
    assert copied_ids == []


@pytest.mark.parametrize("invalid", [float("nan"), Function([], 1, {}), object()])
def test_collection_metadata_rejects_non_json_values(invalid):
    translator = Translator([], {}, {})
    with pytest.raises(UnsupportedEEError, match="finite JSON values only|numbers must be finite"):
        translator.invoke("Element.set", {
            "object": collection(), "key": "bad", "value": invalid,
        })


def test_collection_metadata_rejects_cycles_unknown_arguments_and_sampled_mutations():
    translator = Translator([], {}, {})
    cyclic = {}
    cyclic["self"] = cyclic
    with pytest.raises(UnsupportedEEError, match="cyclic JSON"):
        translator.invoke("Element.set", {
            "object": collection(), "key": "bad", "value": cyclic,
        })
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        translator.invoke("Element.set", {
            "object": collection(), "key": "x", "value": 1, "ignored": True,
        })

    sampled = SampledFeatures(Image([], {}), "{}")
    with pytest.raises(UnsupportedEEError, match="read-only"):
        translator.invoke("Element.set", {"object": sampled, "key": "x", "value": 1})
    with pytest.raises(UnsupportedEEError, match="copyProperties is unsupported"):
        translator.invoke("Element.copyProperties", {
            "destination": sampled, "source": sampled,
        })


def test_collection_metadata_is_opaque_to_literal_csv_graph_detection(ee):
    source = ee.FeatureCollection([
        ee.Feature(None, {"system:index": "row-1", "value": 9}),
    ]).setMulti({
        "process_id": "local_ee_table",
        "from_node": "gee_table",
        "process_graph": {"fake": {"process_id": "save_result"}},
    })
    data = compile_sdk(ee, source)
    assert columns(data) == ["system:index", "value", ".geo"]
    assert render_csv(data, ["system:index", "value"]) == "system:index,value\r\nrow-1,9\r\n"

    input_graph = table_input_graph(data, ["system:index", "value"])
    graph = {
        "gee_table": {**input_graph["gee_table"], "result": False},
        "save": {
            "process_id": "save_result",
            "arguments": {"data": {"from_node": "gee_table"}, "format": "CSV"},
            "result": True,
        },
    }
    assert has_table_node(graph)
    copied, selected = validate_table_graph(graph)
    assert copied["properties"] == data["properties"]
    assert selected == ["system:index", "value"]


def test_feature_and_image_metadata_routes_remain_unchanged(ee):
    translator = Translator([], {}, {})
    feature_value = feature({"row": 1})
    updated_feature = translator.invoke("Element.set", {
        "object": feature_value, "key": "tag", "value": "feature",
    })
    assert updated_feature["properties"] == {"row": 1, "tag": "feature"}

    image = Image([("constant", Pixel("constant", (2,)))], {"tag": "image"})
    assert translator.invoke("Image.get", {"image": image, "property": "tag"}) == "image"
    updated_image = translator.invoke("Element.set", {
        "object": image, "key": "tag", "value": "changed",
    })
    assert updated_image.props["tag"] == "changed"
