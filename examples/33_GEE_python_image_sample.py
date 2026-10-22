"""Compile Image.sample -> sampled Smile RF classification from a local fixture.

The fixture is synthetic. This script only constructs and compiles graphs; it
does not fit an RF outside the trusted local engine or submit export tasks.
"""
from pathlib import Path


SYNTHETIC_VERSION = "local-ee-synthetic-image-sample-rf/v1"
FIXTURE_PATH = "tests/fixtures/ee-image-sample-rf-v1.json"
SAMPLE_BANDS = ["landcover", "nir", "red"]
INPUT_PROPERTIES = ["nir", "red"]
CLASS_PROPERTY = "landcover"
OUTPUT_NAME = "predicted_class"
SAMPLE_MODES = ("all", "factor", "num_pixels", "nullable")


def _sample_arguments(data, mode):
    """Return one documented sampling option set without mixing controls."""
    if mode not in SAMPLE_MODES:
        raise ValueError(f"Unknown sample mode: {mode}")
    common = {"seed": data["sample_seed"], "tileScale": 1, "geometries": True}
    if mode == "all":
        return common
    if mode == "nullable":
        return {**common, "dropNulls": False}
    if mode == "factor":
        return {
            **common,
            "region": data["explicit_region"],
            "factor": 0.5,
            "dropNulls": False,
        }
    return {
        **common,
        "region": data["explicit_region"],
        "numPixels": 8,
        "dropNulls": False,
    }


def _validation_collection(ee, validation_features):
    if isinstance(validation_features, list):
        return ee.FeatureCollection([
            ee.Feature(feature.get("geometry"), feature.get("properties", {}))
            for feature in validation_features
        ])
    return ee.FeatureCollection(validation_features)


def build_workflow(ee, image, validation_features, data, mode="all"):
    """Sample pixels, train an explicit-schema RF and build validation outputs."""
    sampling_image = ee.Image(image).select(SAMPLE_BANDS)
    arguments = _sample_arguments(data, mode)
    if "region" in arguments:
        arguments["region"] = ee.Geometry(arguments["region"])
    candidates = sampling_image.sample(**arguments)
    complete = candidates.filter(ee.Filter.notNull(
        [CLASS_PROPERTY, *INPUT_PROPERTIES],
    ))
    eligible = complete.filter(ee.Filter.gt("nir", -1))
    training = eligible.limit(data["training_limit"])

    parameters = data["rf_parameters"]
    classifier = ee.Classifier.smileRandomForest(
        numberOfTrees=parameters["number_of_trees"],
        variablesPerSplit=parameters["variables_per_split"],
        minLeafPopulation=parameters["min_leaf_population"],
        bagFraction=parameters["bag_fraction"],
        maxNodes=parameters["max_nodes"],
        seed=parameters["seed"],
    ).train(
        features=training,
        classProperty=CLASS_PROPERTY,
        inputProperties=INPUT_PROPERTIES,
        subsampling=1,
        subsamplingSeed=0,
    )

    validation = _validation_collection(ee, validation_features)
    predictions = validation.classify(classifier, OUTPUT_NAME)
    validation_matrix = predictions.errorMatrix(
        CLASS_PROPERTY, OUTPUT_NAME, data["class_order"],
    )
    training_matrix = classifier.confusionMatrix()
    classified = ee.Image(image).select(["red", "nir"]).classify(
        classifier, OUTPUT_NAME,
    )
    return {
        "sampling_image": sampling_image,
        "candidates": candidates,
        "complete": complete,
        "eligible": eligible,
        "training": training,
        "classifier": classifier,
        "samples": candidates,
        "band_order": candidates.get("band_order"),
        "sample_property_names": candidates.propertyNames(),
        "validation_predictions": predictions,
        "validation_matrix": validation_matrix,
        "validation_values": {
            "array": validation_matrix.array(),
            "order": validation_matrix.order(),
            "accuracy": validation_matrix.accuracy(),
            "kappa": validation_matrix.kappa(),
            "consumers_accuracy": validation_matrix.consumersAccuracy(),
            "producers_accuracy": validation_matrix.producersAccuracy(),
            "fscore_beta_2": validation_matrix.fscore(2),
        },
        "training_matrix": training_matrix,
        "training_array": training_matrix.array(),
        "classified": classified,
    }


def build_workbench_outputs(ee, outputs, data, map_facade=None):
    """Prepare unstarted local CSV/GeoTIFF exports and an optional map layer."""
    if map_facade is not None:
        map_facade.addLayer(
            outputs["classified"],
            {"min": 0, "max": 1, "palette": ["386cb0", "fdc086"]},
            "Image.sample RF classes",
        )
    table_task = ee.batch.Export.table.toDrive(
        collection=outputs["samples"],
        description="image_sample_training_rows",
        fileNamePrefix="image_sample_training_rows",
        fileFormat="CSV",
        selectors=["system:index", *SAMPLE_BANDS, ".geo"],
    )
    image_task = ee.batch.Export.image.toDrive(
        image=outputs["classified"],
        description="image_sample_rf_prediction",
        fileNamePrefix="image_sample_rf_prediction",
        region=ee.Geometry(data["export_region"]),
        fileFormat="GeoTIFF",
    )
    return {"table_task": table_task, "image_task": image_task}


def compile_fixture_summary(ee, root, mode="all"):
    """Compile each user-visible sink without materializing pixels or tasks."""
    import json

    from gee.ee_translate import compile_expression

    data = json.loads((root / FIXTURE_PATH).read_text(encoding="utf-8"))
    catalog = [{
        "id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": data["catalog_bands"]}},
    }]
    items = {data["collection_id"]: [{
        key: row[key] for key in ("id", "bbox", "geometry", "properties")
    } for row in data["items"]]}
    image = ee.Image(data["scene_id"])
    outputs = build_workflow(
        ee, image, data["validation_features"], data, mode=mode,
    )
    descriptors = {}
    for name in ("samples", "training", "validation_predictions", "classified",
                 "band_order", "sample_property_names", "validation_values"):
        value = outputs[name]
        if name == "validation_values":
            descriptors[name] = {
                key: compile_expression(ee.serializer.encode(item, for_cloud_api=False), catalog, items)
                for key, item in value.items()
            }
        else:
            expression = ee.serializer.encode(value, for_cloud_api=False)
            descriptors[name] = compile_expression(expression, catalog, items)
    return {"fixture": data["schema"], "mode": mode, "descriptors": descriptors,
            "submitted": False}


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
    result = compile_fixture_summary(ee, root)
    print(json.dumps({
        "fixture": result["fixture"],
        "mode": result["mode"],
        "kinds": {
            name: value["kind"] for name, value in result["descriptors"].items()
            if name != "validation_values"
        },
        "validation_value_kinds": {
            name: value["kind"]
            for name, value in result["descriptors"]["validation_values"].items()
        },
        "submitted": result["submitted"],
    }, indent=2))


if __name__ == "__main__":
    main()
