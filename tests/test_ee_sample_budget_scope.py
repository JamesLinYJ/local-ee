"""Sample preflight follows top-level raster edges, not callback-local names."""
from __future__ import annotations

from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from gee.services.ee_budget import (
    _output_raster_loads,
    sample_input_budget,
)
from scripts.ee_python_api.offline import OfflineGuard
from ee_empty_expression_reference import load_fixture as load_wave67_fixture
from ee_empty_expression_sdk import python_example as wave67_example
from ee_rf_validation_workflow_helpers import (
    compile_value as compile_rf_value,
    load_fixture as load_rf_fixture,
    local_metadata as rf_local_metadata,
    make_ee as make_rf_ee,
)


ROOT = Path(__file__).resolve().parents[1]


def _wave67_sample():
    fixture = load_wave67_fixture()
    example = wave67_example()
    catalog, items = example.synthetic_metadata(fixture)
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        image = ee.Image(ee.ImageCollection(fixture["source_id"]).first())
        outputs = example.build_workflow(ee, image, fixture)
        descriptors = {
            name: compile_expression(
                ee.serializer.encode(value, for_cloud_api=False), catalog, items,
            )
            for name, value in (
                ("map_sample", outputs["map_sample"]),
                ("map_values", outputs["map_values"]),
            )
        }
    assert guard.evidence()["attempt_count"] == 0
    for descriptor in descriptors.values():
        validate(descriptor["process_graph"])
    return fixture, items, descriptors


def _asset(shape, transform):
    return {
        "proj:shape": shape,
        "proj:epsg": 4326,
        "proj:transform": transform,
    }


def test_official_sdk_callback_a0_shadow_does_not_mask_real_source_or_siblings():
    fixture, items, descriptors = _wave67_sample()
    sample_graph = descriptors["map_sample"]["process_graph"]
    image_graph = descriptors["map_values"]["process_graph"]
    callbacks = [
        node["arguments"]["reducer"]["process_graph"]
        for node in sample_graph.values()
        if node["process_id"] == "reduce_dimension"
    ]
    assert callbacks and any("a0" in callback for callback in callbacks)
    assert "a0" not in sample_graph

    # This top-level node deliberately shadows callback-local `a0`. It has a
    # valid but enormous grid, so treating the callback edge as a source fails
    # the existing input-cell cap instead of silently producing a false budget.
    item_id = "callback-shadow-large-grid"
    bands = ["red", "nir"]
    shadow_load = {
        "process_id": "load_collection",
        "arguments": {
            "id": "callback-shadow",
            "spatial_extent": {"west": 0, "south": 0, "east": 4, "north": 4},
            "_gee_item_ids": [item_id],
            "bands": bands,
        },
    }
    sample_graph["a0"] = shadow_load
    image_graph["a0"] = shadow_load
    items["callback-shadow"] = [{
        "id": item_id,
        "bbox": [0, 0, 4, 4],
        "properties": {"proj:epsg": 4326},
        "assets": {
            band: _asset([5_000_000, 5_000_000], [1e-6, 0, 0, 0, -1e-6, 4])
            for band in bands
        },
    }]
    validate(sample_graph)
    validate(image_graph)

    budget = sample_input_budget(descriptors["map_sample"], items)
    assert budget["input_asset_grid_cells"] == 32  # 4x4x2 true source cells
    assert [args["id"] for args in _output_raster_loads(descriptors["map_values"])] == [
        fixture["source_id"],
    ]
    # The reducer's callback is one argument; its ordinary `data` sibling still
    # leads both preflight walkers back to load_collection n0.
    assert sample_graph["a0"]["arguments"]["id"] == "callback-shadow"


def test_official_sdk_sample_dispatch_passes_budget_preflight(monkeypatch, tmp_path):
    from gee.services import ee as ee_service
    from table_export_support import install

    fixture = load_wave67_fixture()
    example = wave67_example()
    catalog, items = example.synthetic_metadata(fixture)
    with OfflineGuard() as guard:
        runtime = install(monkeypatch, tmp_path)
        monkeypatch.setattr(ee_service, "DATA", tmp_path)
        monkeypatch.setattr(ee_service, "catalog_snapshot", lambda: (catalog, items))
        image = runtime.ee.Image(
            runtime.ee.ImageCollection(fixture["source_id"]).first(),
        )
        output = example.build_workflow(runtime.ee, image, fixture)["map_sample"]
        response = runtime.dispatch({
            "action": "evaluate",
            "expression": runtime.ee.serializer.encode(output, for_cloud_api=False),
        })
    assert guard.evidence()["attempt_count"] == 0
    assert response["pending"] is True
    row = runtime.store.job(response["job_id"], runtime.account["user_id"])
    assert row["context"]["result_kind"] == "samples"


def test_sampled_training_and_query_branches_keep_both_source_loads_in_budget():
    fixture = load_rf_fixture()
    catalog, items = rf_local_metadata(fixture)
    grid = fixture["grid"]
    rows, columns = grid["shape_rows_columns"]
    xmin, ymin, xmax, ymax = grid["extent"]
    transform = [1, 0, xmin, 0, -1, ymax]
    item = items[fixture["collection_id"]][0]
    item["properties"].update({"proj:epsg": 4326, "proj:transform": transform})
    item["assets"] = {
        band: _asset([rows, columns], transform)
        for band in fixture["training_pixel_values"]
    }

    with OfflineGuard() as guard:
        ee = make_rf_ee()

        def sample_regions(offset=0):
            regions = ee.FeatureCollection([
                ee.Feature(ee.Geometry.Point([0.5 + offset, 0.5]), {"actual": 0}),
                ee.Feature(ee.Geometry.Point([1.5 + offset, 1.5]), {"actual": 1}),
            ])
            image = ee.Image(fixture["training_scene_id"]).select(["red", "nir"])
            return image.sampleRegions(
                collection=regions, properties=["actual"], geometries=False,
                scale=10, projection=ee.Projection("EPSG:32610"),
            ).filter(ee.Filter.gte("nir", 0)).limit(20)

        classifier = ee.Classifier.smileRandomForest(
            numberOfTrees=5, variablesPerSplit=1, minLeafPopulation=1,
            bagFraction=0.8, maxNodes=8, seed=13,
        ).train(
            features=sample_regions(), classProperty="actual",
            inputProperties=["nir", "red"],
        )
        result = compile_rf_value(
            ee, sample_regions(0.1).classify(classifier, "predicted"),
            (catalog, items),
        )
    assert guard.evidence()["attempt_count"] == 0

    graph = result["process_graph"]
    validate(graph)
    sample_nodes = [node for node in graph.values()
                    if node["process_id"] == "local_ee_sample_regions"]
    load_nodes = [node for node in graph.values()
                  if node["process_id"] == "load_collection"]
    trainers = [node for node in graph.values()
                if node["process_id"] == "local_ee_train_smile_rf_samples"]
    assert len(sample_nodes) == len(load_nodes) == 2
    assert len(trainers) == 1
    budget = sample_input_budget(result, items)
    assert budget["input_asset_grid_cells"] == 72  # two 3x6x2 sample branches


def test_real_sample_source_still_rejects_input_grids_above_cell_limit():
    _, items, descriptors = _wave67_sample()
    item = items["sentinel-2-l2a"][0]
    for asset in item["assets"].values():
        asset["proj:shape"] = [100_000, 100_000]
        asset["proj:transform"] = [1e-4, 0, 0, 0, -1e-4, 4]

    with pytest.raises(ValueError, match="Sample input exceeds the 100000000"):
        sample_input_budget(descriptors["map_sample"], items)
