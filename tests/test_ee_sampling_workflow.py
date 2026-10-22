"""Pinned sampleRegions -> runtime training -> raster classification workflow."""
import importlib.util
import json
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point, shape

from ee_sampling_workflow_helpers import (
    CLASSIFY_PROCESS,
    SAMPLE_PROCESS,
    TRAIN_PROCESS,
    compile_inputs,
    graph_process_handlers,
    independent_target_predictions,
    independent_training_model,
    load_fixture,
    model_centers_as_pairs,
    reference_feature_collection,
    reference_sample_rows,
)
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "examples/29_GEE_python_sample_training.py"
METRICS = ("euclidean", "manhattan", "cosine")


def example_module():
    spec = importlib.util.spec_from_file_location("sample_training_example", EXAMPLE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_value(ee, value, local, options=None):
    return compile_expression(encode(ee, value), local[0], local[1], options=options)


def _build(ee, module, data, metric):
    regions = ee.FeatureCollection(data["training_features"])
    outputs = module.build_workflow(
        ee, ee.ImageCollection(data["collection_id"]),
        ee.Image(module.TRAINING_SCENE_ID), regions, metric=metric,
    )
    return outputs


def _processes(result):
    return [node["process_id"] for node in result["process_graph"].values()]


def _ancestor_loads(graph, ref):
    found = set()
    pending = [ref["from_node"]]
    while pending:
        node_id = pending.pop()
        if node_id in found:
            continue
        found.add(node_id)
        node = graph[node_id]
        if node["process_id"] == "load_collection":
            yield node["arguments"]
            continue
        def visit(value):
            if isinstance(value, dict):
                if set(value) == {"from_node"}:
                    pending.append(value["from_node"])
                else:
                    for child in value.values():
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(node["arguments"])


def _ancestor_processes(graph, ref):
    return {arguments["process_id"] for arguments in _ancestor_nodes(graph, ref)}


def _ancestor_nodes(graph, ref):
    found = set()
    pending = [ref["from_node"]]
    while pending:
        node_id = pending.pop()
        if node_id in found:
            continue
        found.add(node_id)
        node = graph[node_id]
        yield node
        def visit(value):
            if isinstance(value, dict):
                if set(value) == {"from_node"}:
                    pending.append(value["from_node"])
                else:
                    for child in value.values():
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(node["arguments"])


def test_versioned_raw_fixture_has_independent_rows_and_fractional_class_means():
    data = load_fixture()
    reference = data["reference_expectations"]
    rows = reference_sample_rows(data)
    assert len(rows) == reference["training_row_count"] == 11
    assert [row["id"] for row in rows] == reference["sample_feature_system_indexes"]
    # MultiPoint cell 0 is repeated inside one feature and produces one row;
    # cell (0, 1) remains a separate row for each overlapping source feature.
    assert [row["id"] for row in rows if row["id"].startswith("f1_")] == [
        "f1_r0_c0", "f1_r0_c1",
    ]
    assert [row["id"] for row in rows if row["row"] == 0 and row["col"] == 1] == [
        "f0_r0_c1", "f1_r0_c1", "f2_r0_c1",
    ]
    # The selected red NoData row is removed, while positive-area overlaps and
    # the class-1 training area beyond the target ROI remain in the table.
    assert "f2_r0_c2" not in {row["id"] for row in rows}
    assert {row["id"] for row in rows if row["feature"] == 3} == {
        "f3_r0_c3", "f3_r1_c3", "f3_r2_c3",
    }
    model = independent_training_model(data, "euclidean")
    assert model_centers_as_pairs(model) == reference["class_means_in_red_nir_order"]
    assert model["centers"][0] == (Fraction(2), Fraction(7, 2))
    assert model["centers"][1] == (Fraction(13, 5), Fraction(7))


def test_sample_table_getinfo_export_and_direct_compiler_descriptor():
    data = load_fixture()
    module = example_module()
    local = compile_inputs(data)
    with OfflineGuard() as guard:
        ee = make_ee()
        outputs = _build(ee, module, data, "euclidean")
        descriptor = compile_value(ee, outputs["samples"], local)
        no_geometry = ee.Image(data["items"][0]["id"]).select(["red", "nir"]).sampleRegions(
            collection=ee.FeatureCollection(data["training_features"]),
            properties=data["sample_properties"], geometries=False,
        )
        no_geometry_descriptor = compile_value(ee, no_geometry, local)

        # Exercise the SDK getInfo serialization boundary while returning the
        # compiler descriptor instead of claiming runtime table execution.
        seen = []
        original_compute = ee.data.computeValue
        def compile_get_info(value):
            expression = encode(ee, value)
            seen.append(expression)
            return compile_expression(expression, local[0], local[1])
        ee.data.computeValue = compile_get_info
        try:
            get_info_descriptor = outputs["samples"].getInfo()
        finally:
            ee.data.computeValue = original_compute

        captured = []
        original_send = ee.Map._send
        ee.Map._send = lambda payload: captured.append(payload) or {"job_id": "wave24-map"}
        try:
            workbench = module.build_workbench_outputs(
                ee, outputs, data, map_facade=ee.Map,
            )
        finally:
            ee.Map._send = original_send
        table_task = workbench["table_task"]
        table_export = compile_value(ee, table_task.config["expression"], local)
        assert table_task.config["selectors"] == data["reference_expectations"]["sample_columns_with_geometry"]
        assert table_task.state == ee.batch.Task.State.UNSUBMITTED
        assert workbench["image_task"].state == ee.batch.Task.State.UNSUBMITTED
        map_descriptor = compile_expression(captured[0]["expression"], local[0], local[1])

    assert guard.evidence()["attempt_count"] == 0
    assert len(seen) == 1
    assert descriptor == get_info_descriptor == table_export
    assert descriptor["kind"] == "sample_table"
    assert descriptor["bands"] == data["reference_expectations"]["sample_columns_with_geometry"]
    assert descriptor["source_item_ids"] == ["wave24-sampling-a"]
    assert "features" not in descriptor and "value" not in descriptor
    assert _processes(descriptor)[-1] == SAMPLE_PROCESS
    sample_node = next(node for node in descriptor["process_graph"].values()
                       if node["process_id"] == SAMPLE_PROCESS)
    spec = json.loads(sample_node["arguments"]["spec"])
    assert spec["bands"] == ["red", "nir"]
    assert spec["properties"] == ["plot_id", "landcover"]
    assert spec["geometries"] is True
    assert spec["grid"] == {"scale": None, "crs": None}
    assert all("unused_note" not in feature["properties"] for feature in spec["regions"]["features"])
    assert captured[0]["action"] == "map"
    assert map_descriptor["kind"] == "image" and map_descriptor["bands"] == [module.OUTPUT_NAME]

    actual = evaluate_graph(
        descriptor, local[2], grid=data["pixel_centers"],
        source_geometries=local[3], process_handlers=graph_process_handlers(data),
    )
    expected = reference_feature_collection(data)
    assert actual == expected
    assert [feature["id"] for feature in actual["features"]] == \
        data["reference_expectations"]["sample_feature_system_indexes"]
    assert [feature["geometry"]["coordinates"] for feature in actual["features"]] == [
        [row["x"], row["y"]] for row in reference_sample_rows(data)
    ]
    assert list(actual["features"][0]["properties"]) == ["plot_id", "landcover", "red", "nir"]
    no_geometry_table = evaluate_graph(
        no_geometry_descriptor, local[2], grid=data["pixel_centers"],
        source_geometries=local[3], process_handlers=graph_process_handlers(data),
    )
    assert no_geometry_descriptor["bands"] == descriptor["bands"]
    assert no_geometry_table == reference_feature_collection(data, geometries=False)


@pytest.mark.parametrize("metric", METRICS)
def test_mapped_sample_trained_classification_matches_independent_raw_grid_reference(metric):
    data = load_fixture()
    module = example_module()
    local = compile_inputs(data)
    handlers = graph_process_handlers(data)
    observed = {SAMPLE_PROCESS: [], TRAIN_PROCESS: []}
    for process_id in observed:
        original = handlers[process_id]
        def capture(arguments, values, *, process_id=process_id, original=original):
            result = original(arguments, values)
            observed[process_id].append(result)
            return result
        handlers[process_id] = capture
    with OfflineGuard() as guard:
        ee = make_ee()
        outputs = _build(ee, module, data, metric)
        mapped = compile_value(ee, outputs["classified"], local)

        # Compile the shipped image export with its export ROI. The sample
        # branch must still load the complete fixed source image, including the
        # class-1 polygon that lies wholly east of this ROI.
        workbench = module.build_workbench_outputs(ee, outputs, data)
        exported = compile_value(
            ee, workbench["image_task"].config["expression"], local,
            options={"region": data["target_export_region"]},
        )
        scaled_export = compile_value(
            ee, workbench["image_task"].config["expression"], local,
            options={"region": data["target_export_region"], "scale": 2},
        )

    assert guard.evidence()["attempt_count"] == 0
    validate(mapped["process_graph"])
    validate(exported["process_graph"])
    assert mapped["kind"] == "collection"
    assert mapped["bands"] == [module.OUTPUT_NAME]
    assert set(mapped["source_item_ids"]) == {item["id"] for item in data["items"]}
    processes = _processes(mapped)
    assert SAMPLE_PROCESS in processes and TRAIN_PROCESS in processes
    assert processes.count(SAMPLE_PROCESS) == 1
    assert processes.count(TRAIN_PROCESS) == 1
    assert processes.count(CLASSIFY_PROCESS) >= 1
    graph = mapped["process_graph"]
    training_id, training_node = next(
        (key, node) for key, node in graph.items()
        if node["process_id"] == TRAIN_PROCESS
    )
    sampler_id = training_node["arguments"]["data"]["from_node"]
    assert graph[sampler_id]["process_id"] == SAMPLE_PROCESS
    classify_nodes = [node for node in graph.values()
                      if node["process_id"] == CLASSIFY_PROCESS]
    assert {node["arguments"]["model"]["from_node"] for node in classify_nodes} == {training_id}

    training_loads = list(_ancestor_loads(graph, training_node["arguments"]["data"]))
    assert len(training_loads) == 1
    assert training_loads[0]["_gee_item_ids"] == ["wave24-sampling-a"]
    assert training_loads[0]["spatial_extent"] == {
        "west": 0, "south": 0, "east": 4, "north": 3,
    }

    actual, band_names, timed = evaluate_graph(
        mapped, local[2], grid=data["pixel_centers"],
        source_geometries=local[3], process_handlers=handlers,
    )
    expected = independent_target_predictions(data, metric)
    pinned = np.asarray([
        [np.nan if value is None else value
         for value in scene]
        for scene in data["reference_expectations"]["target_predictions_by_metric"][metric]
    ], dtype=np.float64)[:, None, :]
    np.testing.assert_array_equal(np.isnan(expected), np.isnan(pinned))
    np.testing.assert_array_equal(expected[np.isfinite(pinned)], pinned[np.isfinite(pinned)])
    assert band_names == [module.OUTPUT_NAME] and timed is True
    np.testing.assert_array_equal(np.isnan(actual), np.isnan(expected))
    np.testing.assert_array_equal(actual[np.isfinite(expected)], expected[np.isfinite(expected)])
    assert observed[SAMPLE_PROCESS] == [reference_feature_collection(data)]
    runtime_model = observed[TRAIN_PROCESS][0]
    reference_model = independent_training_model(data, metric)
    assert runtime_model["metric"] == metric
    assert runtime_model["schema"] == data["input_properties"]
    assert runtime_model["labels"] == reference_model["labels"]
    assert runtime_model["centers"] == [
        list(reference_model["centers"][label]) for label in reference_model["labels"]
    ]

    export_graph = exported["process_graph"]
    export_training = next(node for node in export_graph.values()
                           if node["process_id"] == TRAIN_PROCESS)
    export_loads = list(_ancestor_loads(export_graph, export_training["arguments"]["data"]))
    assert export_loads[0]["spatial_extent"] == {
        "west": 0, "south": 0, "east": 4, "north": 3,
    }
    export_actual, export_names, export_timed = evaluate_graph(
        exported, local[2], grid=data["pixel_centers"],
        source_geometries=local[3], process_handlers=handlers,
    )
    export_expected = independent_target_predictions(data, metric)[:1, 0, :].copy()
    roi = shape(data["target_export_region"])
    inside = np.array([roi.covers(Point(*coordinate)) for coordinate in data["pixel_centers"]])
    export_expected[:, ~inside] = np.nan
    assert export_names == [module.OUTPUT_NAME] and export_timed is False
    np.testing.assert_array_equal(np.isnan(export_actual), np.isnan(export_expected))
    np.testing.assert_array_equal(export_actual[np.isfinite(export_expected)],
                                  export_expected[np.isfinite(export_expected)])

    scaled_graph = scaled_export["process_graph"]
    scaled_training = next(node for node in scaled_graph.values()
                           if node["process_id"] == TRAIN_PROCESS)
    scaled_sampler = scaled_graph[scaled_training["arguments"]["data"]["from_node"]]
    assert scaled_sampler["arguments"]["spec"] == graph[sampler_id]["arguments"]["spec"]
    scaled_training_loads = list(_ancestor_loads(
        scaled_graph, scaled_training["arguments"]["data"],
    ))
    assert scaled_training_loads[0]["spatial_extent"] == {
        "west": 0, "south": 0, "east": 4, "north": 3,
    }
    assert "resample_spatial" in _processes(scaled_export)
    assert "resample_spatial" not in _ancestor_processes(
        scaled_graph, scaled_sampler["arguments"]["data"],
    )


def test_dynamic_sample_outputs_reject_unsupported_follow_on_operations():
    data = load_fixture()
    local = compile_inputs(data)
    with OfflineGuard() as guard:
        ee = make_ee()
        regions = ee.FeatureCollection(data["training_features"])
        sampled = ee.Image(data["items"][0]["id"]).select(["red", "nir"]).sampleRegions(
            collection=regions, properties=data["sample_properties"], geometries=True,
        )
        classifier = ee.Classifier.minimumDistance("euclidean").train(
            sampled, data["class_property"], data["input_properties"],
        )
        with pytest.raises(UnsupportedEEError, match="sample-trained|Sampled FeatureCollections"):
            compile_value(ee, sampled.aggregate_array("red"), local)
        with pytest.raises(UnsupportedEEError, match="sample-trained classifiers"):
            compile_value(ee, classifier.confusionMatrix(), local)
        validation = ee.FeatureCollection([ee.Feature(None, {"red": 1, "nir": 2})])
        with pytest.raises(UnsupportedEEError, match="sample-trained classifiers"):
            compile_value(ee, validation.classify(classifier), local)
    assert guard.evidence()["attempt_count"] == 0


def test_example_cli_summary_compiles_sample_map_and_exports_without_submission():
    data = load_fixture()
    module = example_module()
    with OfflineGuard() as guard:
        ee = make_ee()
        summary = module._compile_fixture_summary(ee, ROOT)
    assert guard.evidence()["attempt_count"] == 0
    assert summary["fixture"] == data["schema"]
    assert summary["sample_getInfo_descriptor"]["kind"] == "sample_table"
    assert summary["sample_getInfo_descriptor"]["bands"] == \
        data["reference_expectations"]["sample_columns_with_geometry"]
    assert summary["map_descriptor"]["kind"] == "image"
    assert summary["image_export_descriptor"]["kind"] == "image"
    assert summary["table_export_descriptor"]["kind"] == "sample_table"
    assert summary["submitted"] is False
