"""Build actual-feature RandomForest training and validation workflows.

The pinned Python SDK builds lazy expressions. Local compilation records the
runtime graph but does not fit a forest or invent predictions. ``run_local``
uses the configured local API for bounded getInfo reads and starts a local CSV
export; it never sends data to Google Earth Engine or Google Drive.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


SYNTHETIC_VERSION = "local-ee-synthetic-rf-validation-workflow/v1"
FIXTURE_PATH = "tests/fixtures/ee-rf-validation-workflow-v1.json"
DEFAULT_URL = "http://127.0.0.1:8787/openeo/1.2"
_SYNTHETIC_TOKEN = "a" * 48  # Compile-only adapter token; never a credential.


def _fixture(root: Path) -> dict[str, Any]:
    import json

    data = json.loads((root / FIXTURE_PATH).read_text(encoding="utf-8"))
    if data.get("schema") != SYNTHETIC_VERSION:
        raise ValueError("Unexpected RF validation fixture version")
    return data


def _feature_collection(ee: Any, rows: list[dict[str, Any]]):
    """Create synthetic point features while preserving fixture IDs and fields."""
    features = []
    for index, row in enumerate(rows):
        properties = {key: value for key, value in row.items() if key != "id"}
        properties["system:index"] = row["id"]
        point = ee.Geometry.Point([100 + index / 100, 30])
        features.append(ee.Feature(point, properties))
    return ee.FeatureCollection(features)


def _training_regions(ee: Any, data: dict[str, Any]):
    centers = data["grid"]["pixel_centers"]
    regions = []
    for index, row in enumerate(data["training_regions"]):
        pixel = row["pixel"]
        properties = {"system:index": f"region-{index:02d}",
                      "site": row["site"], "keep": row["keep"]}
        regions.append(ee.Feature(
            ee.Geometry.Point(centers[pixel]),
            properties,
        ))
    return ee.FeatureCollection(regions)


def _classifier(ee: Any, data: dict[str, Any]):
    parameters = data["classifier_parameters"]
    return ee.Classifier.smileRandomForest(
        numberOfTrees=parameters["number_of_trees"],
        variablesPerSplit=parameters["variables_per_split"],
        minLeafPopulation=parameters["min_leaf_population"],
        bagFraction=parameters["bag_fraction"],
        maxNodes=parameters["max_nodes"],
        seed=parameters["seed"],
    )


def build_workflow(ee: Any, data: dict[str, Any], training_mode: str):
    """Return lazy feature predictions and runtime matrix/accessor expressions."""
    if training_mode == "inline":
        training = _feature_collection(ee, data["static_training_rows"])
    elif training_mode == "sampled":
        image = ee.Image(data["training_scene_id"]).select(
            [data["class_property"], *data["input_properties"]],
        )
        candidates = image.sampleRegions(
            collection=_training_regions(ee, data),
            properties=data["region_properties"],
            geometries=True,
            scale=data["training_scale"],
        )
        non_null = candidates.filter(
            ee.Filter.notNull(data["sample_filter"]["not_null"]),
        )
        eligible = non_null.filter(
            ee.Filter.expression(data["sample_filter"]["expression"]),
        )
        training = eligible.limit(data["sample_filter"]["limit"])
    else:
        raise ValueError("training_mode must be 'inline' or 'sampled'")

    classifier = _classifier(ee, data).train(
        features=training,
        classProperty=data["class_property"],
        inputProperties=data["input_properties"],
        subsampling=1,
        subsamplingSeed=0,
    )
    # Expose the classified training table in both modes. Its confusion matrix
    # remains the model's resubstitution matrix; this table is useful for
    # inspecting the per-feature predictions that produce those counts.
    training_predictions = training.classify(classifier, data["output_name"])
    validation_features = _feature_collection(ee, data["validation_rows"])
    validation_predictions = validation_features.classify(
        classifier, data["output_name"],
    )

    training_matrix = classifier.confusionMatrix()
    validation_matrix = validation_predictions.errorMatrix(
        data["class_property"], data["output_name"], data["class_order"],
    )
    return {
        "training": training,
        "classifier": classifier,
        "training_predictions": training_predictions,
        "training_matrix": training_matrix,
        "validation_features": validation_features,
        "validation_predictions": validation_predictions,
        "validation_matrix": validation_matrix,
        "training_values": _matrix_accessors(training_matrix),
        "validation_values": _matrix_accessors(validation_matrix),
    }


def _matrix_accessors(matrix):
    """Keep each server-side accessor a direct, bounded JSON result."""
    return {
        "array": matrix.array(),
        "order": matrix.order(),
        "accuracy": matrix.accuracy(),
        "kappa": matrix.kappa(),
        "consumers_accuracy": matrix.consumersAccuracy(),
        "producers_accuracy": matrix.producersAccuracy(),
        "fscore_beta_2": matrix.fscore(2),
    }


def run_local(ee: Any, workflow: dict[str, Any], data: dict[str, Any], name: str):
    """Read bounded results and start a local FeatureCollection CSV task."""
    values = {
        group: {key: value.getInfo() for key, value in expressions.items()}
        for group, expressions in (
            ("training", workflow["training_values"]),
            ("validation", workflow["validation_values"]),
        )
    }
    classified_features = workflow["validation_predictions"].getInfo()
    export = ee.batch.Export.table.toDrive(
        collection=workflow["validation_predictions"],
        description=f"rf_validation_{name}",
        fileNamePrefix=f"rf_validation_{name}",
        fileFormat="CSV",
        selectors=data["export_selectors"],
    )
    export.start()
    return {
        "metrics": values,
        "classified_feature_count": len(classified_features["features"]),
        "export_task_id": export.id,
        "export_state": export.status()["state"],
    }


def _local_metadata(data: dict[str, Any]):
    grid = data["grid"]
    xmin, ymin, xmax, ymax = grid["extent"]
    scene_id = data["training_scene_id"]
    polygon = {
        "type": "Polygon",
        "coordinates": [[[xmin, ymin], [xmax, ymin], [xmax, ymax],
                         [xmin, ymax], [xmin, ymin]]],
    }
    catalog = [{
        "id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": list(data["training_pixel_values"])}},
    }]
    item = {
        "id": scene_id,
        "bbox": grid["extent"],
        "geometry": polygon,
        "properties": {"system:index": scene_id},
        "pixel_values": data["training_pixel_values"],
        "shape_rows_columns": grid["shape_rows_columns"],
        "pixel_centers": grid["pixel_centers"],
        "crs": grid["crs"],
    }
    return catalog, {data["collection_id"]: [item]}


def compile_workflows(ee, root: Path):
    """Compile workflow graphs for review without fitting a model."""
    from gee.ee_translate import compile_expression

    data = _fixture(root)
    catalog, items = _local_metadata(data)
    result = {}
    for mode in ("inline", "sampled"):
        workflow = build_workflow(ee, data, mode)
        expressions = {
            "validation_predictions": workflow["validation_predictions"],
            **{
                f"training_{key}": value
                for key, value in workflow["training_values"].items()
            },
            **{
                f"validation_{key}": value
                for key, value in workflow["validation_values"].items()
            },
        }
        expressions["training_predictions"] = workflow["training_predictions"]
        result[mode] = {
            name: compile_expression(
                ee.serializer.encode(value, is_compound=True, for_cloud_api=False),
                catalog, items,
            )
            for name, value in expressions.items()
        }
    return {"fixture": SYNTHETIC_VERSION, "workflows": result, "fitted": False}


def main():
    import json
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee

    ee = configure_local_ee(
        DEFAULT_URL, _SYNTHETIC_TOKEN,
        signatures_path=root / "vendor/earthengine-js/algorithms.json",
    )
    compiled = compile_workflows(ee, root)
    summary = {
        "fixture": compiled["fixture"],
        "fitted": compiled["fitted"],
        "graphs": {
            mode: {
                name: {"kind": value["kind"], "nodes": len(value["process_graph"]),
                       "source_item_ids": value.get("source_item_ids", [])}
                for name, value in outputs.items()
            }
            for mode, outputs in compiled["workflows"].items()
        },
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
