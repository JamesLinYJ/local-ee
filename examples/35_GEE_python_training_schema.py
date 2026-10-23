"""Offline optional Classifier.train inputs; fixed finite fixtures, no task run.

Image.sample declares every selected band in band_order. To exclude the label
or other fields from prediction, pass inputProperties explicitly. This example
also demonstrates a static collection with a deliberate predictor-only list.
"""
from __future__ import annotations

import json
from pathlib import Path


def inline_training(ee, fixture):
    """Declare collection metadata separately from feature properties."""
    rows = [ee.Feature(None, values).set("system:index", f"site-{index}")
            for index, values in enumerate(fixture["rows"])]
    collection = ee.FeatureCollection(rows).set({
        "band_order": fixture["band_order"], "fixture": fixture["schema"],
    })
    # All rows pass this fixed predicate; the operation sequence checks that
    # collection metadata and feature identity survive normal table methods.
    prepared = (collection.randomColumn("split", seed=30)
                .filter(ee.Filter.lt("split", 1)).limit(len(rows)))
    automatic = ee.Classifier.minimumDistance().train(
        prepared, fixture["class_property"],
    )
    explicit = ee.Classifier.minimumDistance().train(
        prepared, fixture["class_property"], fixture["band_order"],
    )
    forest = ee.Classifier.smileRandomForest(5, seed=30).train(
        prepared, fixture["class_property"],
    )
    queries = ee.FeatureCollection([ee.Feature(None, row) for row in fixture["queries"]])
    return {
        "collection": prepared, "metadata": prepared.get("band_order"),
        "automatic_schema": automatic.schema(), "explicit_schema": explicit.schema(),
        "forest_schema": forest.schema(),
        "predictions": queries.classify(automatic, "prediction"),
        "explicit_predictions": queries.classify(explicit, "prediction"),
    }


def sampled_training(ee, source):
    """Resolve omitted inputs from the original Image.sample band order."""
    image = ee.Image(source["scene_id"]).select(source["sample_bands"])
    clean = (image.sample(seed=source["sample_seed"], dropNulls=False)
             .filter(ee.Filter.notNull(source["sample_bands"]))
             .randomColumn("split", seed=30).filter(ee.Filter.lt("split", 1)))
    forest = ee.Classifier.smileRandomForest(5, seed=30).train(
        clean, source["class_property"],
    )
    explicit = ee.Classifier.smileRandomForest(5, seed=30).train(
        clean, source["class_property"], source["sample_bands"],
    )
    minimum = ee.Classifier.minimumDistance().train(clean, source["class_property"])
    return {
        "metadata": clean.get("band_order"), "forest_schema": forest.schema(),
        "minimum_schema": minimum.schema(), "classified": image.classify(forest),
        "explicit_classified": image.classify(explicit),
        "minimum_classified": image.classify(minimum),
        "predictions": clean.classify(forest, "prediction"),
    }


def main():
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.offline import OfflineGuard

    fixtures = root / "tests/fixtures"
    fixture = json.loads((fixtures / "ee-training-schema-v1.json").read_text())
    source = json.loads((fixtures / "ee-image-sample-rf-v1.json").read_text())
    catalog = [{"id": source["collection_id"],
                "cube:dimensions": {"bands": {"values": source["catalog_bands"]}}}]
    items = {source["collection_id"]: [{
        key: item[key] for key in ("id", "bbox", "geometry", "properties")
    } for item in source["items"]]}
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=root / "vendor/earthengine-js/algorithms.json",
        )
        outputs = {"inline": inline_training(ee, fixture),
                   "sampled": sampled_training(ee, source)}
        compiled = {mode: {
            name: compile_expression(ee.serializer.encode(value, for_cloud_api=False),
                                     catalog, items)
            for name, value in values.items()
        } for mode, values in outputs.items()}
    assert guard.evidence()["attempt_count"] == 0
    print(json.dumps({
        "fixture": fixture["schema"],
        "descriptor_kinds": {mode: {key: value["kind"] for key, value in values.items()}
                             for mode, values in compiled.items()},
        "network_attempts": 0, "exports_started": False, "RF_fitted": False,
    }, indent=2))


if __name__ == "__main__":
    main()
