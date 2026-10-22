"""Smile RF API compilation, lineage, scale, mask, and raw-separation controls."""
import importlib.util
import json
from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from gee.sampling_spec import decode_sampling_spec
from gee.smile_rf_spec import decode_rf_rows, decode_rf_spec
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "examples/31_GEE_python_smile_random_forest.py"
FIXTURE_PATH = ROOT / "tests/fixtures/ee-smile-rf-workflow-v1.json"
RF_ROWS = "local_ee_train_smile_rf_rows"
RF_SAMPLES = "local_ee_train_smile_rf_samples"
RF_CLASSIFY = "local_ee_smile_rf"
SAMPLE = "local_ee_sample_regions"
SAMPLE_OP = "local_ee_sample_table_op"


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text())


def example_module():
    spec = importlib.util.spec_from_file_location("smile_rf_example", EXAMPLE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def local_metadata(data):
    catalog = [{
        "id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": data["catalog_bands"]}},
    }]
    items = {data["collection_id"]: [{
        key: row[key] for key in ("id", "bbox", "geometry", "properties")
    } for row in data["items"]]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_value(ee, value, local, options=None):
    return compile_expression(encode(ee, value), local[0], local[1], options=options)


def nodes(graph, process_id):
    return [(key, node) for key, node in graph.items()
            if node["process_id"] == process_id]


def _params(spec):
    return {name: spec[name] for name in (
        "number_of_trees", "variables_per_split", "min_leaf_population",
        "bag_fraction", "max_nodes", "seed",
    )}


def test_static_and_sampled_rf_trainers_compile_to_their_distinct_processes():
    data = load_fixture()
    module = example_module()
    catalog, items = local_metadata(data)
    with OfflineGuard() as guard:
        ee = make_ee()
        targets = ee.ImageCollection(data["collection_id"])
        static = module.build_static_workflow(
            ee, targets, data["static_training_features"], data["example_parameters"],
        )
        sampled = module.build_sampled_workflow(
            ee, targets, ee.Image(data["training_scene_id"]),
            data["training_regions"], data, data["example_parameters"],
        )
        static_map = compile_value(ee, static["classified"], (catalog, items))
        sampled_map = compile_value(ee, sampled["classified"], (catalog, items))
        sampled_table = compile_value(ee, sampled["samples"], (catalog, items))
    assert guard.evidence()["attempt_count"] == 0

    for descriptor in (static_map, sampled_map, sampled_table):
        validate(descriptor.get("process_graph", {}))
    assert static_map["bands"] == sampled_map["bands"] == [data["output_name"]]
    assert static_map["source_item_ids"] == ["smile-rf-target-scene"]
    assert sampled_map["source_item_ids"] == [
        "smile-rf-target-scene", data["training_scene_id"],
    ]
    assert sampled_table["kind"] == "sample_table"

    static_graph = static_map["process_graph"]
    static_trainers = nodes(static_graph, RF_ROWS)
    assert len(static_trainers) == 1
    assert nodes(static_graph, RF_SAMPLES) == []
    static_id, static_trainer = static_trainers[0]
    assert set(static_trainer["arguments"]) == {"rows", "spec"}
    static_spec = decode_rf_spec(static_trainer["arguments"]["spec"])
    assert _params(static_spec) == data["example_parameters"]
    assert static_spec["class_property"] == data["class_property"]
    assert static_spec["schema"] == data["input_properties"]
    static_rows = decode_rf_rows(static_trainer["arguments"]["rows"], static_spec)["rows"]
    expected_rows = [[feature["properties"][data["class_property"]],
                      [feature["properties"][name] for name in data["input_properties"]]]
                     for feature in data["static_training_features"]]
    assert static_rows == expected_rows

    sampled_graph = sampled_map["process_graph"]
    sampled_trainers = nodes(sampled_graph, RF_SAMPLES)
    assert len(sampled_trainers) == 1
    assert nodes(sampled_graph, RF_ROWS) == []
    sampled_id, sampled_trainer = sampled_trainers[0]
    sampled_spec = decode_rf_spec(sampled_trainer["arguments"]["spec"])
    assert _params(sampled_spec) == data["example_parameters"]
    assert sampled_spec["schema"] == data["input_properties"]
    assert sampled_trainer["arguments"]["data"]["from_node"]
    sampler_nodes = nodes(sampled_graph, SAMPLE)
    operation_nodes = nodes(sampled_graph, SAMPLE_OP)
    assert len(sampler_nodes) == 1 and len(operation_nodes) == 3
    sampler_id, sampler = sampler_nodes[0]
    sample_wire = decode_sampling_spec(sampler["arguments"]["spec"])
    assert sample_wire["bands"] == [data["class_property"], *data["input_properties"]]
    assert sample_wire["properties"] == data["sample_properties"]
    assert sample_wire["grid"] == {"scale": data["training_scale"], "crs": None}
    assert sample_wire["regions"]["features"] == data["training_regions"]
    assert operation_nodes[0][1]["arguments"]["data"] == {"from_node": sampler_id}
    assert operation_nodes[0][1]["arguments"]["spec"]
    assert operation_nodes[1][1]["arguments"]["data"] == {"from_node": operation_nodes[0][0]}
    assert operation_nodes[2][1]["arguments"]["data"] == {"from_node": operation_nodes[1][0]}
    assert sampled_trainer["arguments"]["data"] == {"from_node": operation_nodes[2][0]}
    filter_specs = [json.loads(node["arguments"]["spec"]) for _, node in operation_nodes]
    assert [spec["operation"] for spec in filter_specs] == ["filter", "filter", "limit"]
    assert filter_specs[0]["predicate"]["name"] == "notNull"
    assert filter_specs[2]["count"] == data["sample_filter"]["limit"]

    for graph, trainer_id in ((static_graph, static_id), (sampled_graph, sampled_id)):
        predictors = nodes(graph, RF_CLASSIFY)
        assert len(predictors) == 1
        assert predictors[0][1]["arguments"]["model"] == {"from_node": trainer_id}


def test_target_export_scale_does_not_change_fixed_sample_training_source_or_grid():
    data = load_fixture()
    module = example_module()
    catalog, items = local_metadata(data)
    with OfflineGuard() as guard:
        ee = make_ee()
        outputs = module.build_sampled_workflow(
            ee, ee.ImageCollection(data["collection_id"]),
            ee.Image(data["training_scene_id"]), data["training_regions"], data,
        )
        at_declared_scale = compile_value(
            ee, outputs["classified"], (catalog, items),
            options={"region": data["target_export_region"],
                     "scale": data["target_export_scale"]},
        )
        at_other_scale = compile_value(
            ee, outputs["classified"], (catalog, items),
            options={"region": data["target_export_region"],
                     "scale": data["target_export_scale"] * 2},
        )
    assert guard.evidence()["attempt_count"] == 0
    assert at_declared_scale["process_graph"] != at_other_scale["process_graph"]
    first = nodes(at_declared_scale["process_graph"], RF_SAMPLES)
    second = nodes(at_other_scale["process_graph"], RF_SAMPLES)
    assert len(first) == len(second) == 1
    assert first[0][1]["arguments"] == second[0][1]["arguments"]
    sample_node = nodes(at_declared_scale["process_graph"], SAMPLE)[0][1]
    wire = decode_sampling_spec(sample_node["arguments"]["spec"])
    assert wire["grid"]["scale"] == data["training_scale"]
    assert at_declared_scale["source_item_ids"] == [
        "smile-rf-target-scene", data["training_scene_id"],
    ]


def test_parameter_changes_are_preserved_and_invalid_classifier_api_is_rejected():
    data = load_fixture()
    module = example_module()
    catalog, items = local_metadata(data)
    with OfflineGuard() as guard:
        ee = make_ee()
        targets = ee.ImageCollection(data["collection_id"])
        first = module.build_static_workflow(
            ee, targets, data["static_training_features"], data["example_parameters"],
        )
        second = module.build_static_workflow(
            ee, targets, data["static_training_features"], data["alternate_parameters"],
        )
        first_map = compile_value(ee, first["classified"], (catalog, items))
        second_map = compile_value(ee, second["classified"], (catalog, items))
        bad_classifier = ee.Classifier.smileRandomForest(
            0, 2, 1, 0.75, 15, 42,
        ).train(
            features=ee.FeatureCollection(data["static_training_features"]),
            classProperty=data["class_property"], inputProperties=data["input_properties"],
        )
        invalid = ee.ImageCollection(data["collection_id"]).filter(
            ee.Filter.eq("role", "target"),
        ).map(lambda image: ee.Image(image).select(data["input_properties"]).classify(
            bad_classifier, data["output_name"],
        ))
        with pytest.raises(UnsupportedEEError, match="number_of_trees"):
            compile_value(ee, invalid, (catalog, items))
    assert guard.evidence()["attempt_count"] == 0
    first_spec = decode_rf_spec(nodes(first_map["process_graph"], RF_ROWS)[0][1]["arguments"]["spec"])
    second_spec = decode_rf_spec(nodes(second_map["process_graph"], RF_ROWS)[0][1]["arguments"]["spec"])
    assert _params(first_spec) == data["example_parameters"]
    assert _params(second_spec) == data["alternate_parameters"]
    assert first_spec != second_spec


def test_static_training_rejects_aggregate_tree_row_feature_leaf_work_over_budget():
    data = load_fixture()
    catalog, items = local_metadata(data)
    schema = [f"feature_{index}" for index in range(8)]
    with OfflineGuard() as guard:
        ee = make_ee()
        features = ee.FeatureCollection([
            ee.Feature(None, {
                data["class_property"]: row % 2,
                **{name: float(row % 2) for name in schema},
            })
            for row in range(1_000)
        ])
        classifier = ee.Classifier.smileRandomForest(
            126, 8, 1, 1.0, None, 0,
        ).train(
            features=features,
            classProperty=data["class_property"],
            inputProperties=schema,
        )
        expression = ee.Image.constant([0.0] * len(schema)).rename(schema).classify(
            classifier, data["output_name"],
        )
        with pytest.raises(UnsupportedEEError, match="1000000000 training-work budget"):
            compile_value(ee, expression, (catalog, items))
    assert guard.evidence()["attempt_count"] == 0


def test_fixture_raw_ranges_are_separable_without_claiming_fitted_rf_predictions():
    data = load_fixture()
    training = data["items"][0]["pixel_values"]
    target = data["items"][1]["pixel_values"]
    for band in data["input_properties"]:
        class_zero = [value for label, value in zip(training[data["class_property"]], training[band]) if label == 0]
        class_one = [value for label, value in zip(training[data["class_property"]], training[band]) if label == 1]
        assert [min(class_zero), max(class_zero)] == data["raw_separation_oracle"]["class_0_ranges"][band]
        assert [min(class_one), max(class_one)] == data["raw_separation_oracle"]["class_1_ranges"][band]
        assert max(class_zero) < min(class_one)
    separated = data["raw_separation_oracle"]["unambiguous_target_pixel_indices"]
    masked = data["raw_separation_oracle"]["selected_band_nodata_pixel_indices"]
    ambiguous = data["raw_separation_oracle"]["ambiguous_gap_target_pixel_indices"]
    assert all(target[name][index] is not None for name in data["input_properties"] for index in separated)
    assert all(any(target[name][index] is None for name in data["input_properties"]) for index in masked)
    assert all(all(target[name][index] is not None for name in data["input_properties"]) for index in ambiguous)
    # This is a raw data range/mask contract only. It does not compute any RF
    # tree, classify a pixel, or serve as Smile JVM / Earth Engine evidence.


def test_raw_point_samples_have_the_declared_notnull_filter_and_limit_order():
    data = load_fixture()
    source = next(item for item in data["items"]
                  if item["id"] == data["training_scene_id"])
    rows = []
    columns = data["grid"]["shape_rows_columns"][1]
    for region in data["training_regions"]:
        x, y = region["geometry"]["coordinates"]
        col = int(x)
        row = 0 if y > 1 else 1
        pixel = row * columns + col
        properties = dict(region["properties"])
        properties.update({name: source["pixel_values"][name][pixel]
                           for name in [data["class_property"], *data["input_properties"]]})
        rows.append(properties)
    required = data["sample_filter"]["not_null"]
    non_null = [row for row in rows if all(row.get(key) is not None for key in required)]
    eligible = [row for row in non_null if row["keep"] is True and row["site"] != "drop"]
    limited = eligible[:data["sample_filter"]["limit"]]
    assert (len(rows), len(non_null), len(eligible), len(limited)) == (8, 7, 5, 4)
    assert [row["site"] for row in limited] == [
        "keep-0a", "keep-0b", "keep-1a", "keep-1b",
    ]
    assert [row[data["class_property"]] for row in limited] == [0, 0, 1, 1]


def test_example_compiles_both_map_and_export_paths_without_submitting_tasks():
    module = example_module()
    with OfflineGuard() as guard:
        summary = module._compile_fixture_summary(make_ee(), ROOT)
    assert guard.evidence()["attempt_count"] == 0
    assert summary["fixture"] == "local-ee-synthetic-smile-rf-workflow/v1"
    assert summary["submitted"] is False
    assert set(summary["descriptors"]) == {
        "static_map", "static_image_export", "static_table_export",
        "sampled_samples", "sampled_map", "sampled_image_export", "sampled_table_export",
    }
    assert summary["descriptors"]["static_map"]["bands"] == ["rf_class"]
    assert summary["descriptors"]["sampled_map"]["bands"] == ["rf_class"]
    assert summary["descriptors"]["sampled_samples"]["kind"] == "sample_table"
    assert summary["target_export_scale"] == load_fixture()["target_export_scale"]
