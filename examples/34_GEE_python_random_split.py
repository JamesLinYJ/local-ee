"""Compile Image.sample/randomColumn/split/Smile RF graph from local fixtures.

This offline example creates lazy graphs only. Compilation does not materialize
rows, fit the forest, run the map, or start either local export task.
"""
from pathlib import Path


SYNTHETIC_VERSION = "local-ee-synthetic-random-split/v1"
FIXTURE_PATH = "tests/fixtures/ee-random-split-v1.json"
SAMPLE_MODES = ("image_sample_v2", "sample_regions_v1")
DEFAULT_URL = "http://127.0.0.1:8787/openeo/1.2"
_SYNTHETIC_TOKEN = "a" * 48


def _fixtures(root):
    import json

    config = json.loads((root / FIXTURE_PATH).read_text(encoding="utf-8"))
    source = json.loads((root / "tests/fixtures" / config["source_fixture"])
                        .read_text(encoding="utf-8"))
    if config.get("schema") != SYNTHETIC_VERSION:
        raise ValueError("Unexpected random-split fixture version")
    return config, source


def _pixel_regions(ee, source, allowed_cells):
    """Create one explicitly keyed point per source-grid cell for sampleRegions."""
    rows, columns = source["grid"]["shape_rows_columns"]
    west, south, east, north = source["extent"]
    features = []
    for row in range(rows):
        for column in range(columns):
            x = west + (column + 0.5) * (east - west) / columns
            y = north - (row + 0.5) * (north - south) / rows
            cell_id = f"f0_r{row}_c{column}"
            if cell_id not in allowed_cells:
                continue
            features.append(ee.Feature(
                ee.Geometry.Point([x, y]), {"cell_id": cell_id},
            ))
    return ee.FeatureCollection(features)


def build_workflow(ee, config, source, mode="image_sample_v2"):
    """Build disjoint training/validation branches from an explicit random column."""
    if mode not in SAMPLE_MODES:
        raise ValueError(f"Unknown sample mode: {mode}")
    image = ee.Image(source["scene_id"]).select(source["sample_bands"])
    row_keys = None
    if mode == "image_sample_v2":
        candidates = image.sample(
            seed=source["sample_seed"], dropNulls=False, geometries=True,
        )
    else:
        candidates = image.sampleRegions(
            collection=_pixel_regions(ee, source, config["sample_regions_cells"]),
            properties=["cell_id"],
            geometries=True,
        )
        row_keys = ["cell_id"]

    random_args = {
        "columnName": config["random_column"],
        "seed": config["seed"],
        "distribution": config["distribution"],
    }
    if row_keys is not None:
        random_args["rowKeys"] = row_keys
    randomized = candidates.randomColumn(**random_args)
    complete = randomized.filter(ee.Filter.notNull([
        config["class_property"], *config["input_properties"],
        config["random_column"],
    ]))
    training = complete.filter(ee.Filter.lt(
        config["random_column"], config["threshold"],
    ))
    validation = complete.filter(ee.Filter.gte(
        config["random_column"], config["threshold"],
    ))

    parameters = source["rf_parameters"]
    classifier = ee.Classifier.smileRandomForest(
        numberOfTrees=parameters["number_of_trees"],
        variablesPerSplit=parameters["variables_per_split"],
        minLeafPopulation=parameters["min_leaf_population"],
        bagFraction=parameters["bag_fraction"],
        maxNodes=parameters["max_nodes"], seed=parameters["seed"],
    ).train(
        features=training, classProperty=config["class_property"],
        inputProperties=config["input_properties"], subsampling=1,
        subsamplingSeed=0,
    )
    predictions = validation.classify(classifier, config["output_name"])
    matrix = predictions.errorMatrix(
        config["class_property"], config["output_name"], config["class_order"],
    )
    classified = ee.Image(source["scene_id"]).select(
        config["input_properties"],
    ).classify(classifier, config["output_name"])
    return {
        "candidates": candidates, "randomized": randomized, "complete": complete,
        "training": training, "validation": validation, "classifier": classifier,
        "predictions": predictions, "classified": classified,
        "band_order": candidates.get("band_order") if mode == "image_sample_v2" else None,
        "property_names": candidates.propertyNames() if mode == "image_sample_v2" else None,
        "training_matrix": classifier.confusionMatrix(), "validation_matrix": matrix,
        "validation_values": _matrix_accessors(matrix),
    }


def _matrix_accessors(matrix):
    return {
        "array": matrix.array(), "order": matrix.order(),
        "accuracy": matrix.accuracy(), "kappa": matrix.kappa(),
        "consumers_accuracy": matrix.consumersAccuracy(),
        "producers_accuracy": matrix.producersAccuracy(), "fscore_beta_2": matrix.fscore(2),
    }


def build_workbench_outputs(ee, outputs, config, source, mode, map_facade=None):
    if map_facade is not None:
        map_facade.addLayer(
            outputs["classified"], {"min": 0, "max": 1,
            "palette": ["386cb0", "fdc086"]}, "Random split RF classes",
        )
    selectors = ["system:index", config["random_column"], *source["sample_bands"],
                 config["output_name"]]
    if mode == "sample_regions_v1":
        selectors.insert(1, "cell_id")
    selectors.append(".geo")
    table_task = ee.batch.Export.table.toDrive(
        collection=outputs["predictions"], description="random_split_validation",
        fileNamePrefix="random_split_validation", fileFormat="CSV", selectors=selectors,
    )
    image_task = ee.batch.Export.image.toDrive(
        image=outputs["classified"], description="random_split_rf_classes",
        fileNamePrefix="random_split_rf_classes",
        region=ee.Geometry(source["export_region"]), fileFormat="GeoTIFF",
    )
    return {"table_task": table_task, "image_task": image_task}


def _local_metadata(source):
    catalog = [{
        "id": source["collection_id"],
        "cube:dimensions": {"bands": {"values": list(source["catalog_bands"])}},
    }]
    items = {source["collection_id"]: [{
        key: item[key] for key in ("id", "bbox", "geometry", "properties")
    } for item in source["items"]]}
    return catalog, items


def compile_fixture_summary(ee, root, mode="image_sample_v2"):
    """Compile query, classification, map and unstarted export descriptors."""
    from gee.ee_python_exports import local_options
    from gee.ee_translate import compile_expression

    config, source = _fixtures(root)
    metadata = _local_metadata(source)
    outputs = build_workflow(ee, config, source, mode)
    encode = lambda value: ee.serializer.encode(value, for_cloud_api=False)
    values = {
        "candidates": outputs["candidates"], "randomized": outputs["randomized"],
        "training": outputs["training"], "validation_predictions": outputs["predictions"],
        "classified": outputs["classified"],
        "training_matrix": outputs["training_matrix"].array(),
        **{f"validation_{key}": value
           for key, value in outputs["validation_values"].items()},
    }
    if outputs["band_order"] is not None:
        values["band_order"] = outputs["band_order"]
        values["property_names"] = outputs["property_names"]
    descriptors = {
        name: compile_expression(encode(value), *metadata)
        for name, value in values.items()
    }
    tasks = build_workbench_outputs(ee, outputs, config, source, mode)
    table_request = local_options(
        ee, "export_table", tasks["table_task"].config.copy(), encode,
    )
    descriptors["csv"] = compile_expression(
        encode(table_request["expression"]), *metadata,
    )
    image_request = local_options(
        ee, "export_image", tasks["image_task"].config.copy(), encode,
    )
    image_options = {key: value for key, value in image_request["options"].items()
                     if key in {"region", "scale", "crs", "maxPixels"}}
    descriptors["geotiff"] = compile_expression(
        encode(image_request["expression"]), *metadata, options=image_options,
    )
    return {
        "fixture": config["schema"], "mode": mode, "descriptors": descriptors,
        "exports_started": False, "fitted": False,
    }


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
    result = compile_fixture_summary(ee, root)
    print(json.dumps({
        "fixture": result["fixture"], "sample_mode": result["mode"],
        "descriptor_kinds": {name: value["kind"]
                              for name, value in result["descriptors"].items()},
        "exports_started": result["exports_started"], "fitted": result["fitted"],
    }, indent=2))


if __name__ == "__main__":
    main()
