"""Train a sampled minimum-distance classifier from remapped label pixels.

The versioned source is a finite synthetic raster fixture, not satellite data.
This example demonstrates an offline-serializable workflow only; its CLI
compiles the map and export descriptors without executing or submitting them.
"""
from pathlib import Path


SYNTHETIC_VERSION = "local-ee-synthetic-label-training/v1"
FIXTURE_PATH = "tests/fixtures/ee-label-training-v1.json"
COLLECTION_ID = "sentinel-2-l2a"
TRAINING_SCENE_ID = "wave24-sampling-a"
LABEL_SOURCE_BAND = "label_code"
LABEL_FROM = [10, 20]
LABEL_TO = [0, 1]
SAMPLE_BANDS = ["landcover", "red", "nir"]
INPUT_PROPERTIES = ["red", "nir"]
SAMPLE_PROPERTIES = ["plot_id", "keep", "site"]
REQUIRED_PROPERTIES = ["keep", "site", "landcover", "red", "nir"]
FILTER_EXPRESSION = 'keep == true && landcover >= 0 && landcover < 2 && site != "drop"'
SAMPLE_LIMIT = 8
CLASS_PROPERTY = "landcover"
OUTPUT_NAME = "landcover_id"
METRIC = "euclidean"


def build_training_image(ee, source_image):
    """Remap the label raster, then append predictors in a fixed order."""
    source = ee.Image(source_image)
    labels = source.select([LABEL_SOURCE_BAND]).remap(
        LABEL_FROM, LABEL_TO, bandName=LABEL_SOURCE_BAND,
    ).rename(CLASS_PROPERTY)
    return labels.addBands(source.select(INPUT_PROPERTIES))


def build_workflow(ee, target_collection, training_source, regions, metric=METRIC):
    """Train on one fixed remapped source and classify each target scene."""
    training_image = build_training_image(ee, training_source)
    candidates = ee.Image(training_image).sampleRegions(
        collection=ee.FeatureCollection(regions),
        properties=SAMPLE_PROPERTIES,
        geometries=True,
    )
    non_null = candidates.filter(ee.Filter.notNull(REQUIRED_PROPERTIES))
    eligible = non_null.filter(ee.Filter.expression(FILTER_EXPRESSION))
    samples = eligible.limit(SAMPLE_LIMIT)
    classifier = ee.Classifier.minimumDistance(metric=metric, kNearest=1).train(
        features=samples,
        classProperty=CLASS_PROPERTY,
        inputProperties=INPUT_PROPERTIES,
    )

    def classify_image(image):
        return ee.Image(image).select(["nir", "red"]).classify(
            classifier, OUTPUT_NAME,
        )

    classified = ee.ImageCollection(target_collection).map(classify_image)
    return {
        "training_image": training_image,
        "candidates": candidates,
        "non_null": non_null,
        "eligible": eligible,
        "samples": samples,
        "classifier": classifier,
        "classified": classified,
    }


def build_workbench_outputs(ee, outputs, data, map_facade=None):
    """Create reviewable map and unstarted local image/table export expressions."""
    target = ee.ImageCollection(outputs["classified"]).first()
    if map_facade is not None:
        map_facade.addLayer(
            target,
            {"min": 0, "max": 1, "palette": ["386cb0", "fdc086"]},
            "Remapped synthetic land-cover classes",
        )
    image_task = ee.batch.Export.image.toDrive(
        image=target,
        description="remapped_landcover",
        fileNamePrefix="remapped_landcover",
        region=ee.Geometry(data["target_export_region"]),
        fileFormat="GeoTIFF",
    )
    table_task = ee.batch.Export.table.toDrive(
        collection=outputs["samples"],
        description="remapped_label_samples",
        fileNamePrefix="remapped_label_samples",
        fileFormat="CSV",
        selectors=["system:index", *SAMPLE_PROPERTIES, CLASS_PROPERTY,
                   *INPUT_PROPERTIES, ".geo"],
    )
    return {"map_image": target, "image_task": image_task, "table_task": table_task}


def _compile_fixture_summary(ee, root):
    """Compile the official Python expressions without submitting a task."""
    import json

    from gee.ee_translate import compile_expression

    data = json.loads((root / FIXTURE_PATH).read_text())
    catalog = [{
        "id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": data["catalog_bands"]}},
    }]
    items = {data["collection_id"]: [{
        key: row[key] for key in ("id", "bbox", "geometry", "properties")
    } for row in data["items"]]}
    outputs = build_workflow(
        ee,
        ee.ImageCollection(data["collection_id"]),
        ee.Image(TRAINING_SCENE_ID),
        ee.FeatureCollection(data["training_features"]),
    )
    workbench = build_workbench_outputs(ee, outputs, data)
    encode = lambda value: ee.serializer.encode(value, for_cloud_api=False)
    descriptors = {
        "sample": compile_expression(encode(outputs["samples"]), catalog, items),
        "map": compile_expression(encode(workbench["map_image"]), catalog, items),
        "image_export": compile_expression(
            encode(workbench["image_task"].config["expression"]), catalog, items,
            options={"region": data["target_export_region"]},
        ),
        "table_export": compile_expression(
            encode(workbench["table_task"].config["expression"]), catalog, items,
        ),
    }
    return {
        "fixture": SYNTHETIC_VERSION,
        "descriptors": {
            name: {"kind": value["kind"], "bands": value["bands"],
                   "source_item_ids": value["source_item_ids"],
                   "graph_nodes": len(value["process_graph"])}
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
