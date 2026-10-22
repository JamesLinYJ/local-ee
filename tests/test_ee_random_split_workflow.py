"""Independent split reference and offline sample-to-RF graph checks."""
import importlib.util
import json
import shutil

import pytest

from ee_random_split_parity import javascript_expressions, semantic_wire
from ee_random_split_workflow_helpers import (
    ROOT, class_counts, independent_draw, load_fixtures, local_metadata,
    reference_split,
)
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard


EXAMPLE_PATH = ROOT / "examples/34_GEE_python_random_split.py"
MODES = ("image_sample_v2", "sample_regions_v1")
SAMPLE = "local_ee_sample_regions"
SAMPLE_OP = "local_ee_sample_table_op"
RF_SAMPLES = "local_ee_train_smile_rf_samples"
RF_CLASSIFY = "local_ee_smile_rf_classify_samples"
ERROR_MATRIX = "local_ee_error_matrix"
ACCESSOR = "local_ee_confusion_value"


def _module():
    spec = importlib.util.spec_from_file_location("random_split_example", EXAMPLE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def _encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def _compile(ee, value, metadata, options=None):
    return compile_expression(_encode(ee, value), *metadata, options=options)


def _nodes(graph, process_id):
    return [(key, node) for key, node in graph.items()
            if node["process_id"] == process_id]


def _feature_ids(features, mode):
    return [feature["properties"].get("cell_id", feature["id"]) for feature in features]


def _feature_collection(ee, rows):
    features = []
    for index, row in enumerate(rows):
        feature = {**row, "geometry": {
            "type": "Point", "coordinates": [float(index), 0.0],
        }}
        features.append(feature)
    return ee.FeatureCollection({"type": "FeatureCollection", "features": features})


def test_independent_grid_hash_reference_forms_disjoint_exhaustive_split():
    config, source = load_fixtures()
    reference = config["reference"]
    for mode in MODES:
        expected = (reference if mode == "image_sample_v2"
                    else config["sample_regions_reference"])
        candidates, complete, training, validation = reference_split(config, source, mode)
        expected_candidate_count = (expected["raw_grid_rows"] if mode == "image_sample_v2"
                                    else expected["candidate_rows"])
        assert len(candidates) == expected_candidate_count
        assert len(complete) == expected["complete_rows"]
        training_ids, validation_ids = set(_feature_ids(training, mode)), set(_feature_ids(validation, mode))
        assert training_ids == set(expected["training_ids"])
        assert validation_ids == set(expected["validation_ids"])
        assert training_ids.isdisjoint(validation_ids)
        assert training_ids | validation_ids == set(_feature_ids(complete, mode))
        assert class_counts(training, config["class_property"]) == expected["training_class_counts"]
        assert class_counts(validation, config["class_property"]) == expected["validation_class_counts"]

    # The default index key falls back to Feature.id; numbers, bools and strings
    # use distinct tagged frames, while signed zero has one numeric encoding.
    assert independent_draw({"id": "same", "properties": {}}, 0) == \
        independent_draw({"id": "same", "properties": {}}, 0, ["system:index"])
    assert independent_draw({"id": "n", "properties": {"key": True}}, 2, ["key"]) != \
        independent_draw({"id": "n", "properties": {"key": 1}}, 2, ["key"])
    assert independent_draw({"id": "z", "properties": {"key": -0.0}}, 2, ["key"]) == \
        independent_draw({"id": "z", "properties": {"key": 0.0}}, 2, ["key"])


def test_example_compiles_sample_random_split_rf_map_csv_and_geotiff_graphs():
    config, source = load_fixtures()
    metadata = local_metadata(source)
    module = _module()
    compiled = {}
    captured_maps = []
    with OfflineGuard() as guard:
        ee = _ee()
        original_send = ee.Map._send
        ee.Map._send = lambda payload: captured_maps.append(payload) or {"job_id": "wave29-map"}
        try:
            for mode in MODES:
                workflow = module.build_workflow(ee, config, source, mode)
                expressions = {
                    key: workflow[key] for key in (
                        "candidates", "randomized", "complete", "training", "validation",
                        "predictions", "classified",
                    )
                }
                expressions["training_matrix_array"] = workflow["training_matrix"].array()
                expressions.update({
                    f"validation_{name}": value
                    for name, value in workflow["validation_values"].items()
                })
                if mode == "image_sample_v2":
                    expressions["band_order"] = workflow["band_order"]
                    expressions["property_names"] = workflow["property_names"]
                compiled[mode] = {
                    key: _compile(ee, value, metadata)
                    for key, value in expressions.items()
                }
                tasks = module.build_workbench_outputs(
                    ee, workflow, config, source, mode, map_facade=ee.Map,
                )
                from gee.ee_python_exports import local_options

                table_request = local_options(
                    ee, "export_table", tasks["table_task"].config.copy(),
                    lambda value: _encode(ee, value),
                )
                compiled[mode]["csv"] = _compile(
                    ee, table_request["expression"], metadata,
                )
                image_request = local_options(
                    ee, "export_image", tasks["image_task"].config.copy(),
                    lambda value: _encode(ee, value),
                )
                image_options = {key: value for key, value in image_request["options"].items()
                                 if key in {"region", "scale", "crs", "maxPixels"}}
                compiled[mode]["geotiff"] = compile_expression(
                    _encode(ee, image_request["expression"]), *metadata,
                    options=image_options,
                )
                assert tasks["table_task"].state == ee.batch.Task.State.UNSUBMITTED
                assert tasks["image_task"].state == ee.batch.Task.State.UNSUBMITTED
        finally:
            ee.Map._send = original_send
    assert guard.evidence()["attempt_count"] == 0
    assert len(captured_maps) == len(MODES)

    for mode, descriptors in compiled.items():
        for descriptor in descriptors.values():
            if "process_graph" in descriptor:
                validate(descriptor["process_graph"])
        graph = descriptors["predictions"]["process_graph"]
        assert descriptors["candidates"]["kind"] == "sample_table"
        samplers = _nodes(descriptors["candidates"]["process_graph"], SAMPLE)
        assert len(samplers) == 1
        sample_spec = json.loads(samplers[0][1]["arguments"]["spec"])
        assert ("image_sample" in sample_spec) == (mode == "image_sample_v2")
        assert descriptors["predictions"]["kind"] == "runtime_table"
        assert descriptors["classified"]["kind"] == "image"
        assert descriptors["csv"]["kind"] == "runtime_table"
        assert descriptors["geotiff"]["kind"] == "image"
        assert len(_nodes(graph, RF_SAMPLES)) == 1
        assert len(_nodes(graph, RF_CLASSIFY)) == 1
        assert len(_nodes(graph, ERROR_MATRIX)) == 0  # Each accessor owns its bounded graph.
        assert _nodes(graph, SAMPLE_OP)
        random_specs = [json.loads(node["arguments"]["spec"])
                        for _, node in _nodes(graph, SAMPLE_OP)]
        assert any(spec.get("operation") == "random_column" for spec in random_specs)
        train_specs = [json.loads(node["arguments"]["spec"])
                       for _, node in _nodes(graph, RF_SAMPLES)]
        assert train_specs[0]["schema"] == config["input_properties"]
        assert descriptors["training_matrix_array"]["kind"] == "runtime_value"
        for name in ("array", "order", "accuracy", "kappa", "consumers_accuracy",
                     "producers_accuracy", "fscore_beta_2"):
            descriptor = descriptors[f"validation_{name}"]
            assert descriptor["kind"] == "runtime_value"
            assert len(_nodes(descriptor["process_graph"], ERROR_MATRIX)) == 1
            assert len(_nodes(descriptor["process_graph"], ACCESSOR)) == 1
    assert all(payload["action"] == "map" for payload in captured_maps)


@pytest.mark.parametrize("mode", MODES)
def test_python_and_official_javascript_sdk_compile_the_same_random_split_graph(mode):
    if shutil.which("node") is None:
        pytest.skip("Node is required for official JavaScript SDK parity")
    config, source = load_fixtures()
    metadata = local_metadata(source)
    module = _module()
    with OfflineGuard() as guard:
        ee = _ee()
        workflow = module.build_workflow(ee, config, source, mode)
        python_values = {
            "candidates": workflow["candidates"], "randomized": workflow["randomized"],
            "complete": workflow["complete"], "training": workflow["training"],
            "validation": workflow["validation"], "predictions": workflow["predictions"],
            "classified": workflow["classified"],
        }
        python_values.update({
            "training_matrix_array": workflow["training_matrix"].array(),
            **{f"validation_{name}": value
               for name, value in workflow["validation_values"].items()},
        })
        if mode == "image_sample_v2":
            python_values.update({
                "band_order": workflow["band_order"],
                "property_names": workflow["property_names"],
            })
        python = {key: _compile(ee, value, metadata) for key, value in python_values.items()}
        javascript = javascript_expressions(ROOT)[mode]
        js_compiled = {
            key: compile_expression(value, *metadata) if value is not None else
            compile_expression(None, *metadata)
            for key, value in javascript.items() if key in python_values
        }
    assert guard.evidence()["attempt_count"] == 0
    assert semantic_wire(js_compiled) == semantic_wire(python)


def test_inline_controls_cover_normal_reordered_duplicate_and_overwritten_columns():
    config, source = load_fixtures()
    metadata = local_metadata(source)
    rows = [
        {"type": "Feature", "id": "row-a", "geometry": None,
         "properties": {"site": "same", "typed": True, "red": 11,
                         "landcover": 0, "nir": 1}},
        {"type": "Feature", "id": "row-b", "geometry": None,
         "properties": {"site": "same", "typed": 1, "red": 12,
                         "landcover": 1, "nir": 2}},
        {"type": "Feature", "id": "row-c", "geometry": None,
         "properties": {"site": "other", "typed": 1.0, "red": 13,
                         "landcover": 1, "nir": 3}},
    ]
    with OfflineGuard() as guard:
        ee = _ee()
        collection = _feature_collection(ee, rows)
        default = _compile(ee, collection.randomColumn(seed=4), metadata)
        renamed = _compile(ee, collection.randomColumn("renamed", seed=4), metadata)
        combined = _compile(ee, collection.randomColumn(
            "combined", seed=9, rowKeys=["site", "system:index"], distribution="normal",
        ), metadata)
        same_key = _compile(ee, collection.randomColumn(
            "duplicate", seed=9, rowKeys=["site"],
        ), metadata)
        typed = _compile(ee, collection.randomColumn(
            "typed_draw", seed=9, rowKeys=["typed"],
        ), metadata)
        reordered = _compile(ee, collection.randomColumn(
            "combined", seed=9, rowKeys=["system:index", "site"], distribution="normal",
        ), metadata)
        overwritten = _compile(ee, collection.randomColumn("red", seed=4), metadata)
        with pytest.raises(UnsupportedEEError, match="row key|system:index"):
            _compile(ee, _feature_collection(ee, [
                {"type": "Feature", "geometry": None, "properties": {"red": 1}},
            ]).randomColumn(), metadata)
        with pytest.raises(UnsupportedEEError, match="row key|absent"):
            _compile(ee, collection.randomColumn("draw", rowKeys=["absent"]), metadata)
    assert guard.evidence()["attempt_count"] == 0
    # Static inline calls return the actual bounded reference value, compared
    # with the independent typed-wire implementation above.
    values = default["value"]["features"]
    renamed_values = renamed["value"]["features"]
    for feature, result, renamed_result in zip(rows, values, renamed_values):
        assert result["properties"]["random"].hex() == \
            independent_draw(feature, 4).hex()
        assert renamed_result["properties"]["renamed"] == result["properties"]["random"]
    combined_rows = combined["value"]["features"]
    reordered_rows = reordered["value"]["features"]
    same_key_rows = same_key["value"]["features"]
    typed_rows = typed["value"]["features"]
    normal_values = []
    for feature, left, right in zip(rows, combined_rows, reordered_rows):
        expected = independent_draw(feature, 9, ["site", "system:index"], "normal")
        reverse = independent_draw(feature, 9, ["system:index", "site"], "normal")
        assert left["properties"]["combined"].hex() == expected.hex()
        assert right["properties"]["combined"].hex() == reverse.hex()
        normal_values.append(expected)
    assert any(value < 0 or value > 1 for value in normal_values)
    assert same_key_rows[0]["properties"]["duplicate"] == \
        same_key_rows[1]["properties"]["duplicate"]
    typed_draws = [feature["properties"]["typed_draw"] for feature in typed_rows]
    assert [value.hex() for value in typed_draws] == [
        independent_draw(feature, 9, ["typed"]).hex() for feature in rows
    ]
    assert typed_draws[0] != typed_draws[1]  # bool and number use distinct frames.
    assert typed_draws[1] == typed_draws[2]  # int and float normalize to binary64.
    assert reordered_rows[0]["properties"]["combined"] != combined_rows[0]["properties"]["combined"]
    replaced = overwritten["value"]["features"][0]["properties"]
    original_names = list(rows[0]["properties"])
    assert list(replaced) == [*original_names, "system:index"]
    assert replaced["red"].hex() == independent_draw(rows[0], 4).hex()
