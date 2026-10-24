"""Sample fractional-mask values while preserving the official GEE sample API.

This fixture compiles offline. Native tile rows are exercised by the separate
Wave65 probe; this example does not submit a Spark or Google task.
"""
from __future__ import annotations


SYNTHETIC_VERSION = "local-ee-weighted-sampling-wave65/v1"
FIXTURE_PATH = "tests/fixtures/ee-weighted-sampling-wave65-v1.json"
BANDS = ["class_id", "red", "wide_float", "nir"]
MASK_BANDS = ["class_weight", "red_weight", "wide_float_weight", "nir_weight"]
SAMPLE_PROPERTIES = ["source_id", "record_number", "source_note"]
INPUT_PROPERTIES = ["red", "nir"]
CLASS_PROPERTY = "class_id"


def _science_image(ee, image):
    source = ee.Image(image)
    # Preserve an explicit Float32 rounding stage, then continue in Float64.
    wide_float = source.select("wide_float").toFloat().toDouble()
    return ee.Image.cat(
        source.select("class_id"), source.select("red"), wide_float,
        source.select("nir"),
    ).rename(BANDS)


def build_workflow(ee, image, regions, fixture):
    source = _science_image(ee, image)
    weights = ee.Image(image).select(MASK_BANDS)
    weighted = source.updateMask(weights)
    all_positive = source.updateMask(1)
    region = ee.Geometry(fixture["sample_region"])
    sample_options = {
        "region": region, "factor": 0.5, "seed": 77,
        "dropNulls": False, "geometries": True, "tileScale": 1,
    }
    samples = weighted.sample(region=region, dropNulls=False, geometries=True)
    complete = samples.filter(ee.Filter.notNull([CLASS_PROPERTY, *INPUT_PROPERTIES]))
    randomized = complete.randomColumn(
        "split", seed=77, distribution="uniform", rowKeys=["system:index"],
    )
    training = randomized.filter(ee.Filter.lt("split", 1)).limit(8)
    md = ee.Classifier.minimumDistance(metric="euclidean", kNearest=1).train(
        features=training, classProperty=CLASS_PROPERTY,
        inputProperties=INPUT_PROPERTIES,
    )
    rf = ee.Classifier.smileRandomForest(5, None, 1, 0.5, None, 77).train(
        features=training, classProperty=CLASS_PROPERTY,
        inputProperties=INPUT_PROPERTIES,
    )
    target = ee.Image(image).select(INPUT_PROPERTIES)
    return {
        "samples_nullable": samples,
        "samples_drop_nulls": weighted.sample(region=region, dropNulls=True, geometries=True),
        "fractional_factor_control": weighted.sample(**sample_options),
        "all_positive_factor_control": all_positive.sample(**sample_options),
        "sample_regions_fractional": weighted.sampleRegions(
            collection=regions, properties=SAMPLE_PROPERTIES, geometries=True,
        ),
        "sample_regions_all_positive": all_positive.sampleRegions(
            collection=regions, properties=SAMPLE_PROPERTIES, geometries=True,
        ),
        "md_training": training,
        "md_classification": target.classify(md, "md_class"),
        "rf_training": training,
        "rf_classification": target.classify(rf, "rf_class"),
    }


def synthetic_metadata():
    collection = {"id": "sentinel-2-l2a", "cube:dimensions": {
        "bands": {"values": [*BANDS, *MASK_BANDS]},
    }}
    item = {
        "id": "wave65-synthetic-source", "bbox": [0, 0, 4, 2],
        "geometry": {"type": "Polygon", "coordinates": [
            [[0, 0], [4, 0], [4, 2], [0, 2], [0, 0]],
        ]},
        "properties": {
            "system:index": "wave65-synthetic-source", "system:time_start": 1,
            "proj:code": "EPSG:4326", "proj:transform": [1, 0, 0, 0, -1, 2],
        },
        "assets": {
            band: {"proj:shape": [2, 4], "proj:epsg": 4326,
                   "proj:transform": [1, 0, 0, 0, -1, 2]}
            for band in [*BANDS, *MASK_BANDS]
        },
    }
    return [{"id": collection["id"], **collection}], {collection["id"]: [item]}


def main():
    import json
    from pathlib import Path
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.offline import OfflineGuard

    fixture = json.loads((root / FIXTURE_PATH).read_text(encoding="utf-8"))
    catalog, items = synthetic_metadata()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=root / "vendor/earthengine-js/algorithms.json",
        )
        outputs = build_workflow(
            ee, ee.Image(fixture["source_id"]),
            ee.FeatureCollection(fixture["sample_regions"]), fixture,
        )
        descriptors = {
            name: compile_expression(
                ee.serializer.encode(value, for_cloud_api=False), catalog, items,
            )
            for name, value in outputs.items()
        }
    print(json.dumps({
        "fixture": SYNTHETIC_VERSION,
        "scope": "official Python SDK syntax and local compilation only",
        "descriptor_kinds": {name: value["kind"] for name, value in descriptors.items()},
        "network_attempts": guard.evidence()["attempt_count"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
