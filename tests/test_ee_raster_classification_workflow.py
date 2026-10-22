"""SDK -> Image.classify -> process graph -> independent sample oracle."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from ee_raster_classification_helpers import (
    PROCESS_HANDLERS,
    PROCESS_ID,
    classifier_node,
    compile_inputs,
    independent_reference,
    load_fixture,
)
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "examples/28_GEE_python_raster_classification.py"
METRICS = ("euclidean", "manhattan", "cosine")


def example_module():
    spec = importlib.util.spec_from_file_location(
        "raster_classification_example", EXAMPLE_PATH,
    )
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


def compile_value(ee, value, local):
    return compile_expression(encode(ee, value), local[0], local[1])


def check_sample_labels(actual, expected):
    np.testing.assert_array_equal(np.isnan(actual), np.isnan(expected))
    valid = np.isfinite(expected)
    np.testing.assert_array_equal(actual[valid], expected[valid])
    assert np.equal(actual[valid], np.floor(actual[valid])).all()


def expected_wire(metric):
    return {
        "version": 1,
        "metric": metric,
        "schema": ["nir", "red"],
        "labels": [0, 1, 2],
        "centers": [
            [["3", "1"], ["0", "1"]],
            [["2", "1"], ["2", "1"]],
            [["1", "3"], ["1", "2"]],
        ],
    }


def check_against_fixed_samples(actual, data, metric):
    fixed = np.asarray([
        [np.nan if value is None else value for value in scene]
        for scene in data["sample_reference"][metric]
    ], dtype=np.float64)[:, None, :]
    check_sample_labels(actual, fixed)


@pytest.mark.parametrize("metric", METRICS)
def test_sdk_mapped_raster_classification_matches_independent_multiscene_samples(metric):
    data = load_fixture()
    module = example_module()
    assert data["schema"] == module.SYNTHETIC_VERSION
    local = compile_inputs(data)

    with OfflineGuard() as guard:
        ee = make_ee()
        collection = ee.ImageCollection(data["collection_id"])
        classified = module.build_workflow(ee, collection, metric=metric)
        result = compile_value(ee, classified, local)

    assert guard.evidence()["attempt_count"] == 0
    validate(result["process_graph"])
    assert result["kind"] == "collection"
    assert result["bands"] == [data["output_name"]]
    assert result["source_item_ids"] == [item["id"] for item in data["items"]]
    assert result["has_time_dimension"] is True
    node = classifier_node(result)
    assert set(node["arguments"]) == {"data", "model"}
    assert node["arguments"]["model"] == expected_wire(metric)
    assert node["arguments"]["model"]["centers"][2][0] == ["1", "3"]
    assert not any(
        item["process_id"] in {"apply", "local_ee_to_float", "local_ee_to_double"}
        for item in result["process_graph"].values()
    )

    loads = [item["arguments"] for item in result["process_graph"].values()
             if item["process_id"] == "load_collection"]
    assert len(loads) == 1
    # Source band order is aux/red/nir, while the model's data cube is explicitly
    # assembled in nir/red schema order. The missing aux sample is not loaded.
    assert loads[0]["bands"] == ["red", "nir"]
    actual, band_names, timed = evaluate_graph(
        result, local[2], grid=data["pixel_centers"], source_geometries=local[3],
        process_handlers=PROCESS_HANDLERS,
    )
    expected = independent_reference(data, metric)
    check_against_fixed_samples(expected, data, metric)
    assert band_names == [data["output_name"]] and timed is True
    check_sample_labels(actual, expected)
    # Scene A's last center is inside the item bbox but outside its real polygon.
    assert np.isnan(actual[0, 0, 5])
    # Scene B has a missing required red input at sample 5; its other inputs exist.
    assert np.isnan(actual[1, 0, 4])
    # Scene A sample 0 has missing aux but valid nir/red and gets a class.
    assert np.isfinite(actual[0, 0, 0])


def test_single_image_preserves_item_metadata_and_class_band_only():
    data = load_fixture()
    module = example_module()
    local = compile_inputs(data)
    item = data["items"][0]

    with OfflineGuard() as guard:
        ee = make_ee()
        source = ee.Image(item["id"]).select(["aux", "red", "nir"])
        classified = source.classify(
            module.build_classifier(ee), data["output_name"],
        )
        result = compile_value(ee, classified, local)

    assert guard.evidence()["attempt_count"] == 0
    validate(result["process_graph"])
    assert result["kind"] == "image"
    assert result["bands"] == [data["output_name"]]
    assert result["source_item_ids"] == [item["id"]]
    assert result["properties"] == item["properties"]
    assert result["has_time_dimension"] is False
    actual, band_names, timed = evaluate_graph(
        result, local[2], grid=data["pixel_centers"], source_geometries=local[3],
        process_handlers=PROCESS_HANDLERS,
    )
    expected = independent_reference(data, "euclidean")[0]
    assert band_names == [data["output_name"]] and timed is False
    check_sample_labels(actual, expected)


def test_rename_addbands_map_and_export_expression_remain_composable():
    data = load_fixture()
    module = example_module()
    local = compile_inputs(data)

    with OfflineGuard() as guard:
        ee = make_ee()
        collection = ee.ImageCollection(data["collection_id"])
        mapped = module.build_workflow(ee, collection)
        followup = mapped.map(lambda image: image.rename("class_code").addBands(
            image.select(data["output_name"]).rename("class_code_copy")
        ))
        composed = compile_value(ee, followup, local)

        image = ee.Image(data["items"][0]["id"]).select(["aux", "red", "nir"])
        single = image.classify(module.build_classifier(ee), data["output_name"])
        composition = compile_value(
            ee,
            single.rename("class_code").addBands(
                image.select("aux").rename("aux_copy")
            ),
            local,
        )

        captured_maps = []
        map_api = ee.Map
        original_send = map_api._send
        original_map = getattr(module, "Map", None)
        try:
            map_api._send = lambda payload: (
                captured_maps.append(payload) or {"job_id": "sample-map"}
            )
            module.Map = ee.Map
            region = ee.Geometry.Polygon(
                [[[0, 0], [6, 0], [6, 1], [0, 1], [0, 0]]]
            )
            task = module.add_workbench_layer_and_export(ee, mapped, region)
        finally:
            map_api._send = original_send
            if original_map is None:
                del module.Map
            else:
                module.Map = original_map

        map_result = compile_expression(
            captured_maps[0]["expression"], local[0], local[1],
        )
        export_result = compile_value(ee, task.config["expression"], local)

    assert guard.evidence()["attempt_count"] == 0
    validate(composed["process_graph"])
    validate(composition["process_graph"])
    validate(map_result["process_graph"])
    validate(export_result["process_graph"])
    assert composed["bands"] == ["class_code", "class_code_copy"]
    assert composition["bands"] == ["class_code", "aux_copy"]
    assert map_result["bands"] == [data["output_name"]]
    assert export_result["bands"] == [data["output_name"]]
    assert captured_maps[0]["action"] == "map"
    assert task.state == ee.batch.Task.State.UNSUBMITTED
    assert PROCESS_ID in {node["process_id"] for node in composition["process_graph"].values()}
    actual, names, timed = evaluate_graph(
        composition, local[2], grid=data["pixel_centers"],
        source_geometries=local[3], process_handlers=PROCESS_HANDLERS,
    )
    assert names == ["class_code", "aux_copy"] and timed is False
    expected = independent_reference(data, "euclidean")[0]
    np.testing.assert_array_equal(np.isnan(actual[0]), np.isnan(expected[0]))
    np.testing.assert_array_equal(actual[0, :5], expected[0, :5])
    assert np.isfinite(actual[0, 0]) and np.isnan(actual[1, 0])
