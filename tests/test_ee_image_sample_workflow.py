"""Image.sample -> sampled Smile RF compiler workflow and raw-grid references."""
import shutil

import pytest

from ee_image_sample_parity import javascript_expressions, semantic_wire
from ee_image_sample_assertions import (
    assert_sample_rows_match_reference, assert_sample_workflow_graph,
)
from ee_image_sample_workflow_helpers import (
    ROOT, class_frequencies, compile_value, example_module,
    graph_process_handlers, load_fixture, local_metadata,
    reference_sample_rows, reference_training_rows,
)
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard


def make_ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def _selected_pixels(features):
    return [int(feature["id"].rsplit("_c", 1)[1])
            + 4 * int(feature["id"].split("_r", 1)[1].split("_", 1)[0])
            for feature in features]


def test_versioned_raw_grid_hash_null_and_frequency_references():
    data = load_fixture()
    expected = data["reference_expectations"]

    all_rows = reference_sample_rows(data, "all")
    nullable_rows = reference_sample_rows(data, "nullable")
    factor_rows = reference_sample_rows(data, "factor")
    pixel_rows = reference_sample_rows(data, "num_pixels")
    assert len(all_rows) == expected["whole_image_population"] - \
        expected["whole_image_drop_null_false_rows"]
    assert [row["id"] for row in all_rows] == expected["whole_image_drop_null_true_ids"]
    assert len(nullable_rows) == expected["whole_image_population"]
    assert sum(any(value is None for value in row["properties"].values())
               for row in nullable_rows) == expected["whole_image_drop_null_false_rows"]

    assert _selected_pixels(factor_rows) == expected["factor_half_seed_7_global_pixels"]
    assert _selected_pixels(pixel_rows) == \
        expected["num_pixels_8_approx_seed_7_global_pixels"]
    factor_complete = [row for row in factor_rows
                       if all(value is not None for value in row["properties"].values())]
    pixel_complete = [row for row in pixel_rows
                      if all(value is not None for value in row["properties"].values())]
    assert class_frequencies(factor_complete, "landcover") == \
        expected["factor_half_complete_class_counts"]
    assert class_frequencies(pixel_complete, "landcover") == \
        expected["num_pixels_8_complete_class_counts"]
    assert len(factor_rows) == 7
    assert len(pixel_rows) == 9  # numPixels is an approximate target, not a quota.
    assert len(reference_training_rows(data, "factor")) == data["training_limit"]


def test_sample_filter_train_prediction_matrix_and_workbench_graphs():
    data = load_fixture()
    module = example_module()
    metadata = local_metadata(data)
    arrays, geometries = metadata[2], metadata[3]
    handlers = graph_process_handlers(data)
    outputs_by_mode = {}
    with OfflineGuard() as guard:
        ee = make_ee()
        for mode in module.SAMPLE_MODES:
            outputs = module.build_workflow(
                ee, ee.Image(data["scene_id"]), data["validation_features"],
                data, mode=mode,
            )
            descriptors = {
                name: compile_value(ee, outputs[name], metadata)
                for name in (
                    "candidates", "training", "validation_predictions",
                    "classified", "band_order", "sample_property_names",
                )
            }
            descriptors["validation_values"] = {
                name: compile_value(ee, value, metadata)
                for name, value in outputs["validation_values"].items()
            }
            descriptors["training_array"] = compile_value(
                ee, outputs["training_array"], metadata,
            )
            outputs_by_mode[mode] = (outputs, descriptors)

        # The table getInfo call returns its graph descriptor, never invented rows.
        factor_outputs = outputs_by_mode["factor"][0]
        original_compute = ee.data.computeValue
        seen_getinfo = []

        def compile_get_info(value):
            expression = ee.serializer.encode(value, for_cloud_api=False)
            seen_getinfo.append(expression)
            return compile_expression(expression, metadata[0], metadata[1])

        ee.data.computeValue = compile_get_info
        try:
            sample_getinfo = factor_outputs["samples"].getInfo()
        finally:
            ee.data.computeValue = original_compute

        captured = []
        original_send = ee.Map._send
        ee.Map._send = lambda payload: captured.append(payload) or {
            "job_id": "wave28-map",
        }
        try:
            workbench = module.build_workbench_outputs(
                ee, factor_outputs, data, map_facade=ee.Map,
            )
        finally:
            ee.Map._send = original_send

        from gee.ee_python_exports import local_options

        table_request = local_options(
            ee, "export_table", workbench["table_task"].config.copy(),
            lambda value: ee.serializer.encode(value, for_cloud_api=False),
        )
        table_export = compile_value(ee, table_request["expression"], metadata)
        image_request = local_options(
            ee, "export_image", workbench["image_task"].config.copy(),
            lambda value: ee.serializer.encode(value, for_cloud_api=False),
        )
        image_export = compile_expression(
            ee.serializer.encode(
                image_request["expression"], for_cloud_api=False,
            ), metadata[0], metadata[1],
            options={key: value for key, value in image_request["options"].items()
                     if key in {"region", "scale", "crs", "maxPixels"}},
        )
        map_descriptor = compile_expression(
            captured[0]["expression"], metadata[0], metadata[1],
        )
    assert guard.evidence()["attempt_count"] == 0

    assert len(seen_getinfo) == 1
    factor_outputs, factor_descriptors = outputs_by_mode["factor"]
    assert sample_getinfo == factor_descriptors["candidates"]
    assert "features" not in sample_getinfo and "value" not in sample_getinfo
    assert factor_descriptors["candidates"]["kind"] == "sample_table"
    assert factor_descriptors["candidates"]["bands"] == [
        "system:index", *data["sample_bands"], ".geo",
    ]
    assert factor_descriptors["band_order"].get("value") == data["sample_bands"]
    assert factor_descriptors["sample_property_names"].get("value") == ["band_order"]

    # The default region comes from a raw STAC/catalog footprint. The local
    # catalog path treats those legacy edges as planar and emits that model
    # explicitly after the planar union; keep the numerical reference inputs
    # untouched while asserting the model-preserving graph representation.
    graph_expectations = {
        **data,
        "items": [
            {
                **item,
                "geometry": {
                    **item["geometry"],
                    "geodesic": False,
                    "evenOdd": True,
                },
            }
            for item in data["items"]
        ],
    }
    for mode, (_, descriptors) in outputs_by_mode.items():
        assert_sample_workflow_graph(graph_expectations, mode, descriptors)
        assert_sample_rows_match_reference(
            data, mode, descriptors, arrays, geometries, handlers,
        )

    assert workbench["table_task"].state == ee.batch.Task.State.UNSUBMITTED
    assert workbench["image_task"].state == ee.batch.Task.State.UNSUBMITTED
    assert table_export["kind"] == "sample_table"
    assert image_export["kind"] == map_descriptor["kind"] == "image"
    assert captured[0]["action"] == "map"
    assert table_request["options"]["selectors"] == [
        "system:index", *data["sample_bands"], ".geo",
    ]
    assert image_request["options"]["fileFormat"] == "GeoTIFF"
    assert "features" not in table_export and "value" not in table_export


def test_factor_workflow_matches_official_python_and_javascript_sdk_graphs():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for official JavaScript serializer parity")
    data = load_fixture()
    metadata = local_metadata(data)
    module = example_module()
    with OfflineGuard() as guard:
        ee = make_ee()
        outputs = module.build_workflow(
            ee, ee.Image(data["scene_id"]), data["validation_features"],
            data, mode="factor",
        )
        python_values = {
            "candidates": outputs["candidates"],
            "training": outputs["training"],
            "predictions": outputs["validation_predictions"],
            "classified": outputs["classified"],
            "bandOrder": outputs["band_order"],
            "propertyNames": outputs["sample_property_names"],
            "matrixArray": outputs["validation_values"]["array"],
            "matrixOrder": outputs["validation_values"]["order"],
            "matrixAccuracy": outputs["validation_values"]["accuracy"],
            "matrixKappa": outputs["validation_values"]["kappa"],
            "matrixConsumers": outputs["validation_values"]["consumers_accuracy"],
            "matrixProducers": outputs["validation_values"]["producers_accuracy"],
            "matrixFscore": outputs["validation_values"]["fscore_beta_2"],
        }
        python_descriptors = {
            name: compile_value(ee, value, metadata)
            for name, value in python_values.items()
        }
        javascript = javascript_expressions(ROOT)
        javascript_descriptors = {
            name: compile_expression(expression, metadata[0], metadata[1])
            for name, expression in javascript.items()
        }
    assert guard.evidence()["attempt_count"] == 0
    assert semantic_wire(javascript_descriptors) == semantic_wire(python_descriptors)


def test_sample_controls_reject_mutually_exclusive_sampling_parameters():
    data = load_fixture()
    metadata = local_metadata(data)
    with OfflineGuard() as guard:
        ee = make_ee()
        bad = ee.Image(data["scene_id"]).sample(
            region=ee.Geometry(data["explicit_region"]),
            factor=0.5,
            numPixels=8,
            seed=data["sample_seed"],
        )
        with pytest.raises(UnsupportedEEError, match="mutually exclusive"):
            compile_value(ee, bad, metadata)
    assert guard.evidence()["attempt_count"] == 0
