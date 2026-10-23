"""Classify first, select held-out rows afterwards; offline synthetic example.

Explicit predictor properties exclude the class label. Neither compilation nor
synthetic validation establishes real-data skill or Google numerical parity.
"""
from __future__ import annotations

import json
from pathlib import Path


def build_workflow(ee, fixture, parameters):
    image = ee.Image("wave31-classified-scene").select(fixture["band_order"])
    samples = image.sample(
        region=ee.Geometry(fixture["region"], proj="EPSG:4326", geodesic=False),
        seed=fixture["options"]["seed"], dropNulls=True, geometries=True,
    )
    randomized = samples.randomColumn("split", 29)
    training = randomized.filter(ee.Filter.lt("split", 0.5))
    predictors = [name for name in fixture["band_order"] if name != "landcover"]
    classifier = ee.Classifier.smileRandomForest(*[
        parameters[key] for key in (
            "number_of_trees", "variables_per_split", "min_leaf_population",
            "bag_fraction", "max_nodes", "seed",
        )
    ]).train(training, "landcover", predictors)
    predictions = randomized.classify(classifier, "prediction")
    validation = predictions.filter(ee.Filter.gte("split", 0.5))
    annotated = validation.randomColumn("audit_draw", 31)
    limited = annotated.limit(8)
    matrix = limited.errorMatrix("landcover", "prediction", [0, 1])
    return {
        "training": training, "predictions": predictions,
        "validation": validation, "annotated": annotated, "limited": limited,
        "matrix_array": matrix.array(), "accuracy": matrix.accuracy(),
    }


def local_metadata(fixture):
    grid = fixture["grid"]
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {
        "bands": {"values": fixture["band_order"]},
    }}]
    items = {"sentinel-2-l2a": [{
        "id": "wave31-classified-scene", "geometry": fixture["region"],
        "bbox": [grid[key] for key in ("xmin", "ymin", "xmax", "ymax")],
        "properties": {"system:index": "wave31-classified-scene"},
    }]}
    return catalog, items


def main():
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from gee.graph import validate
    from gee.smile_rf_spec import prepare_rf_parameters
    from scripts.ee_python_api.offline import OfflineGuard

    fixture = json.loads((root / "tests/fixtures/ee-random-split-native-v1.json").read_text())
    parameters = prepare_rf_parameters(13, 1, 1, 1.0, 4, 41)
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=root / "vendor/earthengine-js/algorithms.json")
        compiled = {name: compile_expression(
            ee.serializer.encode(value, for_cloud_api=False), *local_metadata(fixture),
        ) for name, value in build_workflow(ee, fixture, parameters).items()}
    for result in compiled.values():
        validate(result["process_graph"])
    assert guard.evidence()["attempt_count"] == 0
    print(json.dumps({"kinds": {key: value["kind"] for key, value in compiled.items()},
                      "network_attempts": 0, "fitted_or_deployed": False}, indent=2))


if __name__ == "__main__":
    main()
