"""Train minimum-distance classification from actual synthetic raster samples.

The fixture is a finite local compatibility scene, not satellite data.  The
training image is sampled once before a two-scene target map, so the classifier
keeps the same training evidence when the target collection is mapped.  The
CLI compiles descriptors only; it never calls getInfo, starts an export, or
submits workbench jobs.
"""
from pathlib import Path


SYNTHETIC_VERSION = "local-ee-synthetic-sampling-training/v1"
FIXTURE_PATH = "tests/fixtures/ee-sampling-training-v1.json"
COLLECTION_ID = "sentinel-2-l2a"
TRAINING_SCENE_ID = "wave24-sampling-a"
INPUT_PROPERTIES = ["red", "nir"]
SAMPLE_PROPERTIES = ["plot_id", "landcover"]
CLASS_PROPERTY = "landcover"
OUTPUT_NAME = "landcover_id"
METRIC = "euclidean"


def build_training_table(ee, training_image, regions):
    """Sample selected named bands and copy only the declared feature fields."""
    return ee.Image(training_image).select(INPUT_PROPERTIES).sampleRegions(
        collection=ee.FeatureCollection(regions),
        properties=SAMPLE_PROPERTIES,
        geometries=True,
    )


def build_workflow(ee, target_collection, training_image, regions, metric=METRIC):
    """Keep the training source fixed while classifying every target scene."""
    samples = build_training_table(ee, training_image, regions)
    classifier = ee.Classifier.minimumDistance(metric=metric, kNearest=1).train(
        features=samples,
        classProperty=CLASS_PROPERTY,
        inputProperties=INPUT_PROPERTIES,
    )

    def classify_image(image):
        # Deliberately reverse source order; classification resolves the named
        # training schema red/nir rather than assuming the target's band order.
        return ee.Image(image).select(["nir", "red"]).classify(
            classifier, OUTPUT_NAME,
        )

    classified = ee.ImageCollection(target_collection).map(classify_image)
    return {"samples": samples, "classifier": classifier, "classified": classified}


def build_workbench_outputs(ee, outputs, data, map_facade=None):
    """Create one map expression and unstarted image/table export expressions."""
    target = ee.ImageCollection(outputs["classified"]).first()
    if map_facade is not None:
        map_facade.addLayer(
            target,
            {"min": 0, "max": 1, "palette": ["386cb0", "fdc086"]},
            "Sample-trained synthetic classes",
        )
    image_task = ee.batch.Export.image.toDrive(
        image=target,
        description="sample_trained_landcover",
        fileNamePrefix="sample_trained_landcover",
        region=ee.Geometry(data["target_export_region"]),
        fileFormat="GeoTIFF",
    )
    table_task = ee.batch.Export.table.toDrive(
        collection=outputs["samples"],
        description="sample_training_table",
        fileNamePrefix="sample_training_table",
        fileFormat="CSV",
        selectors=["system:index", *SAMPLE_PROPERTIES, *INPUT_PROPERTIES, ".geo"],
    )
    return {"map_image": target, "image_task": image_task, "table_task": table_task}


def _compile_fixture_summary(ee, root):
    """Compile actual SDK expressions for offline review without submission."""
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
    regions = ee.FeatureCollection(data["training_features"])
    outputs = build_workflow(
        ee,
        ee.ImageCollection(data["collection_id"]),
        ee.Image(TRAINING_SCENE_ID),
        regions,
    )
    workbench = build_workbench_outputs(ee, outputs, data)
    encode = lambda value: ee.serializer.encode(value, for_cloud_api=False)

    sample_descriptor = compile_expression(encode(outputs["samples"]), catalog, items)
    map_descriptor = compile_expression(encode(workbench["map_image"]), catalog, items)
    table_descriptor = compile_expression(
        encode(workbench["table_task"].config["expression"]), catalog, items,
    )
    image_descriptor = compile_expression(
        encode(workbench["image_task"].config["expression"]), catalog, items,
        options={"region": data["target_export_region"]},
    )
    return {
        "fixture": SYNTHETIC_VERSION,
        "sample_getInfo_descriptor": {
            "kind": sample_descriptor["kind"],
            "bands": sample_descriptor["bands"],
            "source_item_ids": sample_descriptor["source_item_ids"],
            "graph_nodes": len(sample_descriptor["process_graph"]),
        },
        "map_descriptor": {
            "kind": map_descriptor["kind"],
            "bands": map_descriptor["bands"],
            "source_item_ids": map_descriptor["source_item_ids"],
            "graph_nodes": len(map_descriptor["process_graph"]),
        },
        "image_export_descriptor": {
            "kind": image_descriptor["kind"],
            "bands": image_descriptor["bands"],
            "source_item_ids": image_descriptor["source_item_ids"],
            "graph_nodes": len(image_descriptor["process_graph"]),
        },
        "table_export_descriptor": {
            "kind": table_descriptor["kind"],
            "bands": table_descriptor["bands"],
            "source_item_ids": table_descriptor["source_item_ids"],
            "graph_nodes": len(table_descriptor["process_graph"]),
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
