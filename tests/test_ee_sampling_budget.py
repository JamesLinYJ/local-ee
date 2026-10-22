"""A classifier's fixed training scene must not enlarge its output extent."""
from pathlib import Path

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.services.ee_budget import pixel_budget, sample_input_budget
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


def test_sample_trained_image_budget_uses_target_extent_and_separate_training_budget():
    catalog = [{
        "id": "sentinel-2-l2a",
        "cube:dimensions": {"bands": {"values": ["red", "nir"]}},
    }]
    item_geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
    }
    items = {"sentinel-2-l2a": [
        {"id": "training", "bbox": [0, 0, 1, 1], "geometry": item_geometry,
         "properties": {"proj:epsg": 32610}},
        {"id": "target", "bbox": [0, 0, 0.001, 0.001], "geometry": item_geometry,
         "properties": {"proj:epsg": 32610}},
    ]}
    for item in items["sentinel-2-l2a"]:
        item["assets"] = {
            band: {"proj:shape": [1000, 1000], "proj:epsg": 32610,
                   "proj:transform": [10, 0, 0, 0, -10, 10000]}
            for band in ("red", "nir")
        }

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        regions = ee.FeatureCollection([
            ee.Feature(ee.Geometry.Point([0.5, 0.5]), {"label": 1}),
            ee.Feature(ee.Geometry.Point([0.6, 0.6]), {"label": 2}),
        ])
        samples = ee.Image("training").select(["red", "nir"]).sampleRegions(
            collection=regions, properties=["label"], geometries=False,
            scale=10, projection=ee.Projection("EPSG:32610"),
        )
        classifier = ee.Classifier.minimumDistance().train(
            features=samples, classProperty="label", inputProperties=["red", "nir"],
        )
        classified = ee.Image("target").select(["red", "nir"]).classify(classifier)
        output = compile_expression(
            ee.serializer.encode(for_cloud_api=False, obj=classified), catalog, items,
        )
        target_only = compile_expression(
            ee.serializer.encode(
                for_cloud_api=False,
                obj=ee.Image("target").select(["red", "nir"]),
            ),
            catalog, items,
        )

    assert guard.evidence()["attempt_count"] == 0
    assert output["kind"] == target_only["kind"] == "image"
    loads = [node["arguments"] for node in output["process_graph"].values()
             if node["process_id"] == "load_collection"]
    assert {tuple(load["_gee_item_ids"]) for load in loads} == {
        ("training",), ("target",),
    }

    output_budget = pixel_budget(output, items, {}, 100_000_000)
    target_budget = pixel_budget(target_only, items, {}, 100_000_000)
    assert output_budget == target_budget
    assert output_budget["conservative_pixels_per_band"] < 100_000_000
    assert sample_input_budget(output, items)["input_asset_grid_cells"] == 2_000_000
