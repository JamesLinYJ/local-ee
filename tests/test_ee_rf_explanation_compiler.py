"""Pinned SDK and compiler checks for lazy Smile RF explanation values."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from gee.ee_python_client import configure_local_ee
from gee.compat.earthengine.decoder import Translator
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.compat.earthengine import rf_explanation, rf_explanation_wire
from gee.graph import validate
from gee.rf_explanation_spec import decode_explanation_spec
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
EXTENT = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
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
        "cube:dimensions": {"bands": {"values": ["red", "nir"]}},
    }]
    items = {"sentinel-2-l2a": [{
        "id": "training-scene", "bbox": [0, 0, 2, 2],
        "geometry": EXTENT,
        "properties": {"system:index": "training-scene"},
    }]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def classifier(ee, trees=7, schema=("nir", "red")):
    examples = [
        {"label": 0, "nir": 0.2, "red": 0.1},
        {"label": 0, "nir": 0.3, "red": 0.2},
        {"label": 1, "nir": 0.8, "red": 0.7},
        {"label": 1, "nir": 0.9, "red": 0.6},
    ]
    features = ee.FeatureCollection([
        ee.Feature(None, {
            **row,
            **{name: row["nir"] + index / 100
               for index, name in enumerate(schema) if name not in row},
        })
        for row in examples
    ])
    model = ee.Classifier.smileRandomForest(numberOfTrees=trees).train(
        features=features, classProperty="label", inputProperties=list(schema),
    )
    return model


def compile_value(ee, local, value):
    return compile_expression(encode(ee, value), local[0], local[1])


def descriptor(result):
    assert result["kind"] == "runtime_explanation"
    assert result["bands"] == []
    spec = decode_explanation_spec(result["explanation_spec"])
    assert set(spec) == {"version", "schema", "trees", "view"} | (
        {"keys"} if "keys" in spec else set()
    )
    assert spec["version"] == 1
    graph = result["process_graph"]
    explain = [(key, node) for key, node in graph.items()
               if node["process_id"] == "local_ee_smile_rf_explain"]
    trainers = [(key, node) for key, node in graph.items()
                if node["process_id"] == "local_ee_train_smile_rf_rows"]
    assert len(explain) == len(trainers) == 1
    assert set(explain[0][1]["arguments"]) == {"model", "spec"}
    assert explain[0][1]["arguments"]["spec"] == result["explanation_spec"]
    assert explain[0][1]["arguments"]["model"] == {"from_node": trainers[0][0]}
    validate(graph)
    return spec


def test_explain_lowers_actual_trained_model_to_lazy_json_sink(ee, local):
    result = compile_value(ee, local, classifier(ee).explain())
    spec = descriptor(result)

    assert spec == {
        "version": 1, "schema": ["nir", "red"],
        "trees": 7, "view": "explanation",
    }
    trainer = next(node for node in result["process_graph"].values()
                   if node["process_id"] == "local_ee_train_smile_rf_rows")
    assert set(trainer["arguments"]) == {"rows", "spec"}


@pytest.mark.parametrize(("trees", "schema"), [
    (1, ("nir",)),
    (256, ("nir", "red")),
    (256, tuple(f"band_{index}" for index in range(8))),
])
def test_explain_accepts_training_boundaries(ee, local, trees, schema):
    spec = descriptor(compile_value(
        ee, local, classifier(ee, trees=trees, schema=schema).explain(),
    ))
    assert spec["trees"] == trees
    assert spec["schema"] == list(schema)


def test_large_valid_training_rows_remain_limited_by_existing_work_budget(ee, local):
    features = ee.FeatureCollection([
        ee.Feature(None, {"label": index % 2, "nir": (index % 100) / 100})
        for index in range(400)
    ])
    model = ee.Classifier.smileRandomForest(numberOfTrees=7).train(
        features=features, classProperty="label", inputProperties=["nir"],
    )

    with pytest.raises(UnsupportedEEError, match="Static Array operation exceeds the compilation work budget"):
        compile_value(ee, local, model.explain())


def test_dictionary_projections_are_lazy_and_metadata_reads_are_static(ee, local):
    model = classifier(ee)
    explanation = ee.Dictionary(model.explain())
    importance = ee.Dictionary(explanation.get("importance"))

    assert descriptor(compile_value(ee, local, explanation)) == {
        "version": 1, "schema": ["nir", "red"],
        "trees": 7, "view": "explanation",
    }
    assert descriptor(compile_value(ee, local, importance))["view"] == "importance"
    assert descriptor(compile_value(
        ee, local, ee.Number(importance.get("nir")),
    )) == {
        "version": 1, "schema": ["nir", "red"], "trees": 7,
        "view": "importance_value", "keys": ["nir"],
    }
    assert descriptor(compile_value(
        ee, local, ee.Number(explanation.get("numberOfTrees")),
    ))["view"] == "numberOfTrees"
    assert descriptor(compile_value(
        ee, local, ee.Number(explanation.get("outOfBagErrorEstimate")),
    ))["view"] == "outOfBagErrorEstimate"
    assert descriptor(compile_value(ee, local, explanation.values())) == {
        "version": 1, "schema": ["nir", "red"], "trees": 7,
        "view": "values", "keys": [
            "importance", "numberOfTrees", "outOfBagErrorEstimate",
        ],
    }
    assert descriptor(compile_value(ee, local, importance.values())) == {
        "version": 1, "schema": ["nir", "red"], "trees": 7,
        "view": "importance_values", "keys": ["nir", "red"],
    }
    assert compile_value(ee, local, explanation.keys())["value"] == [
        "importance", "numberOfTrees", "outOfBagErrorEstimate",
    ]
    assert compile_value(ee, local, explanation.contains("trees"))["value"] is False
    assert compile_value(
        ee, local, explanation.get("missing", 12),
    )["value"] == 12


def test_requested_dictionary_value_keys_keep_order_and_duplicates(ee, local):
    importance = ee.Dictionary(
        ee.Dictionary(classifier(ee).explain()).get("importance"),
    )
    keys = ["red", "nir", "red"]
    spec = descriptor(compile_value(ee, local, importance.values(keys=keys)))
    assert spec["view"] == "importance_values"
    assert spec["keys"] == keys


@pytest.mark.parametrize("factory", [
    lambda ee: ee.Classifier.smileRandomForest(numberOfTrees=3).explain(),
    lambda ee: ee.Classifier.minimumDistance().train(
        features=ee.FeatureCollection([
            ee.Feature(None, {"label": 0, "nir": 0.1}),
            ee.Feature(None, {"label": 1, "nir": 0.9}),
        ]), classProperty="label", inputProperties=["nir"],
    ).explain(),
])
def test_untrained_and_other_classifiers_cannot_explain(ee, local, factory):
    with pytest.raises(UnsupportedEEError, match="trained Smile RandomForest"):
        compile_value(ee, local, factory(ee))


@pytest.mark.parametrize("value_factory", [
    lambda ee: ee.Dictionary(ee.Classifier.smileRandomForest(3).train(
        features=ee.FeatureCollection([
            ee.Feature(None, {"label": 0, "nir": 0.1}),
            ee.Feature(None, {"label": 1, "nir": 0.9}),
        ]), classProperty="label", inputProperties=["nir"],
    ).explain()).set("numberOfTrees", 99),
    lambda ee: ee.Number(ee.Dictionary(classifier(ee).explain()).get(
        "numberOfTrees")).add(1),
    lambda ee: ee.List(ee.Dictionary(classifier(ee).explain()).values()).length(),
    lambda ee: ee.Algorithms.If(classifier(ee).explain(), 1, 0),
    lambda ee: ee.Dictionary({"nested": classifier(ee).explain()}),
    lambda ee: ee.Dictionary(classifier(ee).explain()).get("trees"),
])
def test_explanation_mutation_math_list_truth_container_and_tree_access_reject(
        ee, local, value_factory):
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, local, value_factory(ee))


@pytest.mark.parametrize("factory", [
    lambda ee: ee.Filter.eq("candidate", [classifier(ee).explain()]),
    lambda ee: ee.Filter.inList(leftField="candidate",
                                rightValue=[classifier(ee).explain()]),
    lambda ee: ee.Array([classifier(ee).explain()]),
    lambda ee: ee.Geometry.MultiPoint([classifier(ee).explain()]),
    lambda ee: ee.Feature(None, {"nested": [classifier(ee).explain()]}),
])
def test_nested_explanations_cannot_flow_through_generic_wrappers(
        ee, local, factory):
    with pytest.raises(
            UnsupportedEEError,
            match="Runtime RF explanations support only typed dictionary reads"):
        compile_value(ee, local, factory(ee))


def test_opaque_argument_scans_are_cycle_safe_and_charge_shared_dags():
    translator = SimpleNamespace(steps=0)
    cyclic = []
    cyclic.append(cyclic)

    assert not rf_explanation.contains_runtime_explanation(cyclic, translator)
    assert translator.steps == 2

    leaf = [0, 1]
    shared = [leaf, leaf]
    translator.steps = 0
    assert not rf_explanation.contains_runtime_explanation(shared, translator)
    assert translator.steps == 6


def test_opaque_argument_scan_does_not_mask_cyclic_metadata_error():
    translator = Translator([], {}, {})
    rf_explanation.mark_runtime_explanation_seen(translator)
    cyclic = {}
    cyclic["self"] = cyclic

    with pytest.raises(UnsupportedEEError, match="cyclic JSON"):
        translator.invoke("Element.set", {
            "object": {"type": "FeatureCollection", "features": []},
            "key": "bad", "value": cyclic,
        })


def test_dictionary_values_enforces_projection_key_limit(ee, local):
    explanation = ee.Dictionary(classifier(ee, schema=("nir",)).explain())
    importance = ee.Dictionary(explanation.get("importance"))
    assert descriptor(compile_value(
        ee, local, importance.values(keys=["nir"] * 64),
    ))["keys"] == ["nir"] * 64
    with pytest.raises(UnsupportedEEError, match="64 string keys"):
        compile_value(ee, local, importance.values(keys=["nir"] * 65))


def test_dictionary_missing_null_default_is_not_materialized_as_a_runtime_value(
        ee, local):
    explanation = ee.Dictionary(classifier(ee, schema=("nir",)).explain())
    with pytest.raises(UnsupportedEEError, match="does not contain key"):
        compile_value(ee, local, explanation.get("missing", None))


def test_dictionary_default_cannot_hide_an_explanation_in_a_container(ee, local):
    explanation = ee.Dictionary(classifier(ee, schema=("nir",)).explain())
    default = ee.List([explanation])
    with pytest.raises(UnsupportedEEError, match="cannot be nested in Dictionary defaults"):
        compile_value(ee, local, explanation.get("missing", default))


def test_spec_preflight_preserves_legitimate_unicode_and_duplicate_keys():
    schema = ("温度", "😀")
    keys = ["😀", "温度", "😀"]
    translator = SimpleNamespace(steps=0)
    classifier = SimpleNamespace(
        schema=schema,
        classifier=SimpleNamespace(number_of_trees=9),
    )

    spec = rf_explanation._prepare(
        translator, classifier, "importance_values", keys,
    )

    assert decode_explanation_spec(spec) == {
        "version": 1, "schema": list(schema), "trees": 9,
        "view": "importance_values", "keys": keys,
    }
    assert len(spec.encode("utf-8")) == rf_explanation_wire.explanation_spec_utf8_size(
        schema, 9, "importance_values", keys,
    )


def test_spec_preflight_rejects_astral_duplicate_key_overbudget_before_encode(
        monkeypatch):
    wide_name = "😀" * 256
    translator = SimpleNamespace(steps=0)
    classifier = SimpleNamespace(
        schema=(wide_name,),
        classifier=SimpleNamespace(number_of_trees=1),
    )

    def unexpected_encode(*_args, **_kwargs):
        pytest.fail("shared spec encoder ran before the UTF-8 size rejection")

    monkeypatch.setattr(rf_explanation, "prepare_explanation_spec", unexpected_encode)
    with pytest.raises(UnsupportedEEError, match="exceeds16384 UTF-8 bytes"):
        rf_explanation._prepare(
            translator, classifier, "importance_values", [wide_name] * 64,
        )
    assert translator.steps < 50_000


def test_unseen_translator_skips_runtime_explanation_scan(monkeypatch):
    def unexpected_scan(*_args, **_kwargs):
        pytest.fail("ordinary metadata invoked the opaque-explanation scanner")

    monkeypatch.setattr(
        rf_explanation, "contains_runtime_explanation", unexpected_scan,
    )
    translator = Translator([], {}, {})
    source = {"type": "FeatureCollection", "features": [], "properties": {}}

    result = translator.invoke("Element.set", {
        "object": source, "key": "nested", "value": {"items": [1, 2, 3]},
    })

    assert result["properties"] == {"nested": {"items": [1, 2, 3]}}
    assert translator._runtime_rf_explanation_seen is False


def test_opaque_explanation_scan_is_cycle_and_shared_dag_safe():
    translator = Translator([], {}, {})
    shared = [1]
    assert rf_explanation.contains_runtime_explanation(
        [shared, shared], translator,
    ) is False
    assert translator.steps == 5

    translator.steps = 0
    cycle = []
    cycle.append(cycle)
    assert rf_explanation.contains_runtime_explanation(cycle, translator) is False
    assert translator.steps == 2

    cycle.append(rf_explanation.RuntimeRFExplanation(None, "{}"))
    translator.steps = 0
    assert rf_explanation.contains_runtime_explanation(cycle, translator) is True
    assert translator.steps == 3

    translator = Translator([], {}, {})
    translator._runtime_rf_explanation_seen = True
    cyclic_metadata = {}
    cyclic_metadata["self"] = cyclic_metadata
    with pytest.raises(UnsupportedEEError, match="cyclic JSON"):
        translator.invoke("Element.set", {
            "object": {"type": "FeatureCollection", "features": [], "properties": {}},
            "key": "bad", "value": cyclic_metadata,
        })
