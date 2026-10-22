"""Compile static and sampled Smile RandomForest workflows from a local fixture.

The pinned SDK expressions and graphs are synthetic/offline. No task is
submitted and no model is fitted by this example; numerical forest evidence
requires the separately tested trusted Smile JVM implementation.
"""
from pathlib import Path


SYNTHETIC_VERSION = "local-ee-synthetic-smile-rf-workflow/v1"
FIXTURE_PATH = "tests/fixtures/ee-smile-rf-workflow-v1.json"
TRAINING_SCENE_ID = "smile-rf-training-scene"
CLASS_PROPERTY = "class_id"
INPUT_PROPERTIES = ["red", "nir"]
OUTPUT_NAME = "rf_class"
SAMPLE_PROPERTIES = ["site", "keep"]
RF_PARAMETERS = {
    "number_of_trees": 15,
    "variables_per_split": 2,
    "min_leaf_population": 1,
    "bag_fraction": 0.75,
    "max_nodes": 15,
    "seed": 42,
}


def _classifier(ee, parameters):
    """Pass all six Smile RF constructor parameters without inferred defaults."""
    return ee.Classifier.smileRandomForest(
        numberOfTrees=parameters["number_of_trees"],
        variablesPerSplit=parameters["variables_per_split"],
        minLeafPopulation=parameters["min_leaf_population"],
        bagFraction=parameters["bag_fraction"],
        maxNodes=parameters["max_nodes"],
        seed=parameters["seed"],
    )


def _classify_targets(ee, target_collection, classifier):
    """Apply a trained RF to the selected raster schema in fixed band order."""
    targets = ee.ImageCollection(target_collection).filter(ee.Filter.eq("role", "target"))

    def classify_image(image):
        return ee.Image(image).select(INPUT_PROPERTIES).classify(
            classifier, OUTPUT_NAME,
        )

    return targets.map(classify_image)


def build_static_workflow(ee, target_collection, training_features, parameters=None):
    """Train from a literal FeatureCollection and map over target images."""
    chosen = RF_PARAMETERS if parameters is None else parameters
    features = ee.FeatureCollection(training_features)
    classifier = _classifier(ee, chosen).train(
        features=features,
        classProperty=CLASS_PROPERTY,
        inputProperties=INPUT_PROPERTIES,
        subsampling=1,
        subsamplingSeed=0,
    )
    return {
        "features": features,
        "classifier": classifier,
        "classified": _classify_targets(ee, target_collection, classifier),
    }


def build_sampled_workflow(
    ee, target_collection, training_source, regions, data, parameters=None,
):
    """Sample a fixed training scene, filter/limit its table, then train/map."""
    chosen = RF_PARAMETERS if parameters is None else parameters
    training_image = ee.Image(training_source).select(
        [CLASS_PROPERTY, *INPUT_PROPERTIES],
    )
    candidates = training_image.sampleRegions(
        collection=ee.FeatureCollection(regions),
        properties=SAMPLE_PROPERTIES,
        geometries=True,
        scale=data["training_scale"],
    )
    non_null = candidates.filter(ee.Filter.notNull(data["sample_filter"]["not_null"]))
    eligible = non_null.filter(
        ee.Filter.expression(data["sample_filter"]["expression"]),
    )
    samples = eligible.limit(data["sample_filter"]["limit"])
    classifier = _classifier(ee, chosen).train(
        features=samples,
        classProperty=CLASS_PROPERTY,
        inputProperties=INPUT_PROPERTIES,
        subsampling=1,
        subsamplingSeed=0,
    )
    return {
        "training_image": training_image,
        "candidates": candidates,
        "non_null": non_null,
        "eligible": eligible,
        "samples": samples,
        "classifier": classifier,
        "classified": _classify_targets(ee, target_collection, classifier),
    }


def build_workbench_outputs(ee, outputs, data, name, map_facade=None):
    """Build map and unstarted image/table export expressions."""
    target = ee.ImageCollection(outputs["classified"]).first()
    if map_facade is not None:
        map_facade.addLayer(
            target,
            {"min": 0, "max": 1, "palette": ["386cb0", "fdc086"]},
            f"Synthetic Smile RF {name}",
        )
    image_task = ee.batch.Export.image.toDrive(
        image=target,
        description=f"smile_rf_{name}",
        fileNamePrefix=f"smile_rf_{name}",
        region=ee.Geometry(data["target_export_region"]),
        scale=data["target_export_scale"],
        fileFormat="GeoTIFF",
    )
    table_task = ee.batch.Export.table.toDrive(
        collection=outputs["samples"] if "samples" in outputs else outputs["features"],
        description=f"smile_rf_{name}_training",
        fileNamePrefix=f"smile_rf_{name}_training",
        fileFormat="CSV",
        selectors=["system:index", *SAMPLE_PROPERTIES, CLASS_PROPERTY, *INPUT_PROPERTIES],
    )
    return {"map_image": target, "image_task": image_task, "table_task": table_task}


def _metadata(data):
    catalog = [{
        "id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": data["catalog_bands"]}},
    }]
    items = {data["collection_id"]: [{
        key: row[key] for key in ("id", "bbox", "geometry", "properties")
    } for row in data["items"]]}
    return catalog, items


def _compile_fixture_summary(ee, root):
    """Compile both classifier paths and exports without submitting work."""
    import json

    from gee.ee_translate import compile_expression

    data = json.loads((root / FIXTURE_PATH).read_text())
    catalog, items = _metadata(data)
    targets = ee.ImageCollection(data["collection_id"])
    static = build_static_workflow(ee, targets, data["static_training_features"],
                                   data["example_parameters"])
    sampled = build_sampled_workflow(
        ee, targets, ee.Image(TRAINING_SCENE_ID), data["training_regions"], data,
        data["example_parameters"],
    )
    static_outputs = build_workbench_outputs(ee, static, data, "static")
    sampled_outputs = build_workbench_outputs(ee, sampled, data, "sampled")
    encode = lambda value: ee.serializer.encode(value, for_cloud_api=False)
    export_options = {
        "region": data["target_export_region"],
        "scale": data["target_export_scale"],
    }
    expressions = {
        "static_map": (static_outputs["map_image"], None),
        "static_image_export": (static_outputs["image_task"].config["expression"], export_options),
        "static_table_export": (static_outputs["table_task"].config["expression"], None),
        "sampled_samples": (sampled["samples"], None),
        "sampled_map": (sampled_outputs["map_image"], None),
        "sampled_image_export": (sampled_outputs["image_task"].config["expression"], export_options),
        "sampled_table_export": (sampled_outputs["table_task"].config["expression"], None),
    }
    descriptors = {
        name: compile_expression(encode(value), catalog, items, options=options)
        for name, (value, options) in expressions.items()
    }
    return {
        "fixture": SYNTHETIC_VERSION,
        "target_export_scale": data["target_export_scale"],
        "descriptors": {
            name: {"kind": value["kind"], "bands": value.get("bands"),
                   "source_item_ids": value.get("source_item_ids"),
                   "graph_nodes": len(value.get("process_graph", {}))}
            for name, value in descriptors.items()
        },
        "submitted": False,
    }


def main():
    import json
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee

    ee = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=root / "vendor/earthengine-js/algorithms.json",
    )
    print(json.dumps(_compile_fixture_summary(ee, root), indent=2))


if __name__ == "__main__":
    main()
