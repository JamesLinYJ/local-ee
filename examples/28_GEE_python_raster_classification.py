"""Classify the versioned synthetic local raster fixture with a mean classifier.

The pinned fixture version is local-ee-synthetic-raster-classification/v1.
Its catalogue shape is aux/red/nir and classification uses nir/red by name.
Its values are synthetic research samples, not ingested satellite data. To use
the workflow with a real local collection, pass an image collection that has
both nir and red bands; no dataset is created by this example.
"""
from pathlib import Path


SYNTHETIC_VERSION = "local-ee-synthetic-raster-classification/v1"
COLLECTION_ID = "sentinel-2-l2a"  # Local compatibility alias used by the synthetic fixture.
INPUT_PROPERTIES = ["nir", "red"]
CLASS_PROPERTY = "landcover"
OUTPUT_NAME = "landcover_id"
METRIC = "euclidean"

TRAINING_ROWS = [
    {"nir": 2, "red": 0, "landcover": 0},
    {"nir": 4, "red": 0, "landcover": 0},
    {"nir": 1, "red": 1, "landcover": 1},
    {"nir": 3, "red": 3, "landcover": 1},
    {"nir": 1, "red": 0, "landcover": 2},
    {"nir": 0, "red": 1, "landcover": 2},
    {"nir": 0, "red": 0.5, "landcover": 2},
]


def build_classifier(ee, metric=METRIC):
    """Train explicit class means from the small inline sample table."""
    training = ee.FeatureCollection([
        ee.Feature(None, row) for row in TRAINING_ROWS
    ])
    return ee.Classifier.minimumDistance(
        metric=metric, kNearest=1,
    ).train(
        features=training,
        classProperty=CLASS_PROPERTY,
        inputProperties=INPUT_PROPERTIES,
    )


def build_workflow(ee, collection, metric=METRIC):
    """Train explicit class means and classify every image by band name."""
    classifier = build_classifier(ee, metric)

    def classify_image(image):
        # The source may carry other bands; the trained schema selects nir/red
        # by name after this intentional red/nir order change.
        ordered = ee.Image(image).select(["red", "nir"])
        return ordered.classify(classifier, OUTPUT_NAME)

    return ee.ImageCollection(collection).map(classify_image)


def add_workbench_layer_and_export(ee, classified, region):
    """Show the first classified image and prepare a local GeoTIFF task.

    The returned task is deliberately left unstarted; the workbench's normal
    review/start flow controls local exports. Its toDrive name maps to a local
    downloadable result and does not upload to Google Drive.
    """
    image = ee.ImageCollection(classified).first()
    Map.addLayer(
        image, {"min": 0, "max": 2, "palette": ["386cb0", "7fc97f", "fdc086"]},
        "Synthetic land-cover classes",
    )
    return ee.batch.Export.image.toDrive(
        image=image,
        description="synthetic_raster_classification",
        fileNamePrefix="synthetic_raster_classification",
        region=region,
        fileFormat="GeoTIFF",
    )


def _compile_fixture_summary(ee, root):
    """Compile the checked-in sample expression without submitting a task."""
    import json

    from gee.ee_translate import compile_expression

    data = json.loads(
        (root / "tests/fixtures/ee-raster-classification-v1.json").read_text()
    )
    catalog = [{
        "id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": data["catalog_bands"]}},
    }]
    items = {data["collection_id"]: [{
        key: row[key] for key in ("id", "bbox", "geometry", "properties")
    } for row in data["items"]]}
    classified = build_workflow(ee, ee.ImageCollection(data["collection_id"]))
    expression = ee.serializer.encode(classified, for_cloud_api=False)
    return compile_expression(expression, catalog, items)


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
    result = _compile_fixture_summary(ee, root)
    print(json.dumps({
        "fixture": SYNTHETIC_VERSION,
        "kind": result["kind"],
        "bands": result["bands"],
        "source_item_ids": result["source_item_ids"],
        "graph_nodes": len(result["process_graph"]),
        "submitted": False,
    }, indent=2))


if __name__ == "__main__":
    main()
