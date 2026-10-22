"""Label remapping, filtered sample training, and mapped classification graph."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point, shape

from ee_label_training_graph_oracles import (
    CLASSIFY_PROCESS,
    REMAP_PROCESS,
    SAMPLE_OP_PROCESS,
    SAMPLE_PROCESS,
    TRAIN_PROCESS,
    graph_process_handlers,
)
from ee_label_training_reference import (
    compile_inputs,
    independent_target_predictions,
    independent_training_model,
    load_fixture,
    reference_filter_stages,
)
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "examples/30_GEE_python_label_training.py"
METRICS = ("euclidean", "manhattan", "cosine")


def example_module():
    spec = importlib.util.spec_from_file_location("label_training_example", EXAMPLE_PATH)
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


def build(ee, module, data, metric="euclidean"):
    return module.build_workflow(
        ee,
        ee.ImageCollection(data["collection_id"]),
        ee.Image(module.TRAINING_SCENE_ID),
        ee.FeatureCollection(data["training_features"]),
        metric=metric,
    )


def _process_nodes(graph, process_id):
    return [(key, node) for key, node in graph.items()
            if node["process_id"] == process_id]


def _ancestor_loads(graph, ref):
    return [node["arguments"] for node in _ancestor_nodes(graph, ref)
            if node["process_id"] == "load_collection"]


def _ancestor_nodes(graph, ref):
    found, pending, loads = set(), [ref["from_node"]], []
    while pending:
        node_id = pending.pop()
        if node_id in found:
            continue
        found.add(node_id)
        node = graph[node_id]
        loads.append(node)
        if node["process_id"] == "load_collection":
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
    return loads


@pytest.mark.parametrize("metric", METRICS)
def test_remap_sample_filter_limit_train_and_map_match_raw_grid_reference(metric):
    data = load_fixture()
    module = example_module()
    local = compile_inputs(data)
    handlers = graph_process_handlers(data)
    observed = {key: [] for key in (REMAP_PROCESS, SAMPLE_PROCESS, SAMPLE_OP_PROCESS, TRAIN_PROCESS)}
    for process_id in observed:
        original = handlers[process_id]

        def capture(arguments, values, *, process_id=process_id, original=original):
            result = original(arguments, values)
            observed[process_id].append(result)
            return result

        handlers[process_id] = capture

    with OfflineGuard() as guard:
        ee = make_ee()
        outputs = build(ee, module, data, metric)
        training_image = compile_value(ee, outputs["training_image"], local)
        descriptors = {
            stage: compile_value(ee, outputs[stage], local)
            for stage in ("candidates", "non_null", "eligible", "samples")
        }
        mapped = compile_value(ee, outputs["classified"], local)
        workbench = module.build_workbench_outputs(ee, outputs, data)
        image_export = compile_value(
            ee, workbench["image_task"].config["expression"], local,
            options={"region": data["target_export_region"]},
        )
        table_export = compile_value(
            ee, workbench["table_task"].config["expression"], local,
        )

    assert guard.evidence()["attempt_count"] == 0
    for descriptor in [*descriptors.values(), mapped, image_export, table_export]:
        validate(descriptor["process_graph"])
    validate(training_image["process_graph"])
    assert all(descriptors[stage]["kind"] == "sample_table" for stage in descriptors)
    assert descriptors["samples"]["bands"] == [
        "system:index", "plot_id", "keep", "site", "landcover", "red", "nir", ".geo",
    ]
    stages = reference_filter_stages(data)
    mapped_values, mapped_names, mapped_timed = evaluate_graph(
        training_image, local[2], grid=data["pixel_centers"],
        source_geometries=local[3], process_handlers=handlers,
    )
    assert mapped_names == ["landcover", "red", "nir"] and mapped_timed is False
    expected_labels = np.asarray([
        np.nan if value is None else value
        for value in data["reference_expectations"]["mapped_label_values"]
    ])
    actual_labels = mapped_values[mapped_names.index("landcover")]
    np.testing.assert_array_equal(np.isnan(actual_labels), np.isnan(expected_labels))
    np.testing.assert_array_equal(actual_labels[np.isfinite(expected_labels)],
                                  expected_labels[np.isfinite(expected_labels)])
    for band in data["input_properties"]:
        actual_band = mapped_values[mapped_names.index(band)]
        source_band = local[2][module.TRAINING_SCENE_ID][band]
        np.testing.assert_array_equal(
            np.isnan(actual_band), np.isnan(source_band),
        )
        np.testing.assert_array_equal(actual_band[np.isfinite(source_band)],
                                      source_band[np.isfinite(source_band)])
    for descriptor_stage, reference_stage in [
        ("candidates", "candidates"), ("non_null", "non_null"),
        ("eligible", "eligible"), ("samples", "limited"),
    ]:
        rows = stages[reference_stage]
        actual = evaluate_graph(
            descriptors[descriptor_stage], local[2], grid=data["pixel_centers"],
            source_geometries=local[3], process_handlers=handlers,
        )
        expected = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature", "id": row["id"], "geometry": row["geometry"],
                "properties": row["properties"],
            } for row in rows],
        }
        assert actual == expected
    assert table_export == descriptors["samples"]
    sample_graph = descriptors["samples"]["process_graph"]
    remap_nodes = _process_nodes(sample_graph, REMAP_PROCESS)
    sample_nodes = _process_nodes(sample_graph, SAMPLE_PROCESS)
    operation_nodes = _process_nodes(sample_graph, SAMPLE_OP_PROCESS)
    assert len(remap_nodes) == len(sample_nodes) == 1
    assert len(operation_nodes) == 3
    assert [json.loads(node["arguments"]["spec"])["operation"]
            for _, node in operation_nodes] == ["filter", "filter", "limit"]
    remap_spec = json.loads(remap_nodes[0][1]["arguments"]["spec"])
    assert remap_spec == {"version": 1, "from": [10, 20], "to": [0, 1], "default": None}
    assert REMAP_PROCESS in {node["process_id"] for node in _ancestor_nodes(
        sample_graph, sample_nodes[0][1]["arguments"]["data"],
    )}
    graph = mapped["process_graph"]
    trainer_id, trainer = _process_nodes(graph, TRAIN_PROCESS)[0]
    sample_id, sample = _process_nodes(graph, SAMPLE_PROCESS)[0]
    graph_operations = _process_nodes(graph, SAMPLE_OP_PROCESS)
    assert len(graph_operations) == 3
    assert graph_operations[0][1]["arguments"]["data"] == {"from_node": sample_id}
    assert graph_operations[1][1]["arguments"]["data"] == {"from_node": graph_operations[0][0]}
    assert graph_operations[2][1]["arguments"]["data"] == {"from_node": graph_operations[1][0]}
    assert trainer["arguments"]["data"] == {"from_node": graph_operations[2][0]}
    operation_specs = [json.loads(node["arguments"]["spec"]) for _, node in graph_operations]
    assert operation_specs[0]["predicate"]["name"] == "notNull"
    assert operation_specs[1]["predicate"]["name"] == "and"
    assert operation_specs[2] == {"version": 1, "operation": "limit", "count": 8}
    assert json.loads(trainer["arguments"]["spec"]) == {
        "version": 1, "metric": metric,
        "class_property": data["class_property"],
        "schema": data["input_properties"],
    }
    assert _process_nodes(graph, CLASSIFY_PROCESS)
    assert {node["arguments"]["model"]["from_node"]
            for _, node in _process_nodes(graph, CLASSIFY_PROCESS)} == {trainer_id}
    assert REMAP_PROCESS in {node["process_id"] for node in _ancestor_nodes(
        graph, sample["arguments"]["data"],
    )}
    training_loads = _ancestor_loads(graph, trainer["arguments"]["data"])
    assert len(training_loads) == 1
    assert training_loads[0]["_gee_item_ids"] == [module.TRAINING_SCENE_ID]
    assert training_loads[0]["spatial_extent"] == {"west": 0, "south": 0, "east": 4, "north": 3}

    actual, names, timed = evaluate_graph(
        mapped, local[2], grid=data["pixel_centers"], source_geometries=local[3],
        process_handlers=handlers,
    )
    expected = independent_target_predictions(data, metric)
    pinned = np.asarray([[
        np.nan if value is None else value for value in scene
    ] for scene in data["reference_expectations"]["target_predictions_by_metric"][metric]])[:, None, :]
    assert names == [module.OUTPUT_NAME] and timed is True
    np.testing.assert_array_equal(np.isnan(expected), np.isnan(pinned))
    np.testing.assert_array_equal(expected[np.isfinite(pinned)], pinned[np.isfinite(pinned)])
    np.testing.assert_array_equal(np.isnan(actual), np.isnan(expected))
    np.testing.assert_array_equal(actual[np.isfinite(expected)], expected[np.isfinite(expected)])
    export_actual, export_names, export_timed = evaluate_graph(
        image_export, local[2], grid=data["pixel_centers"], source_geometries=local[3],
        process_handlers=handlers,
    )
    export_expected = expected[:1, 0, :].copy()
    roi = shape(data["target_export_region"])
    inside = np.asarray([roi.covers(Point(*coordinate)) for coordinate in data["pixel_centers"]])
    export_expected[:, ~inside] = np.nan
    assert export_names == [module.OUTPUT_NAME] and export_timed is False
    np.testing.assert_array_equal(np.isnan(export_actual), np.isnan(export_expected))
    np.testing.assert_array_equal(
        export_actual[np.isfinite(export_expected)], export_expected[np.isfinite(export_expected)],
    )
    assert observed[REMAP_PROCESS]
    assert observed[SAMPLE_PROCESS]
    assert observed[SAMPLE_OP_PROCESS]
    runtime_model = observed[TRAIN_PROCESS][-1]
    reference_model = independent_training_model(data, metric)
    assert runtime_model["labels"] == reference_model["labels"]
    assert runtime_model["centers"] == [
        list(reference_model["centers"][label]) for label in reference_model["labels"]
    ]

    export_training = _process_nodes(image_export["process_graph"], TRAIN_PROCESS)[0][1]
    export_loads = _ancestor_loads(image_export["process_graph"], export_training["arguments"]["data"])
    assert export_loads[0]["spatial_extent"] == {"west": 0, "south": 0, "east": 4, "north": 3}
    assert workbench["image_task"].state == ee.batch.Task.State.UNSUBMITTED
    assert workbench["table_task"].state == ee.batch.Task.State.UNSUBMITTED


def test_example_cli_compiles_sample_map_and_unsubmitted_exports():
    data = load_fixture()
    module = example_module()
    with OfflineGuard() as guard:
        summary = module._compile_fixture_summary(make_ee(), ROOT)
    assert guard.evidence()["attempt_count"] == 0
    assert summary["fixture"] == data["schema"]
    assert set(summary["descriptors"]) == {"sample", "map", "image_export", "table_export"}
    assert summary["descriptors"]["sample"]["kind"] == "sample_table"
    assert summary["descriptors"]["map"]["kind"] == "image"
    assert summary["descriptors"]["image_export"]["kind"] == "image"
    assert summary["descriptors"]["table_export"]["kind"] == "sample_table"
    assert summary["submitted"] is False
