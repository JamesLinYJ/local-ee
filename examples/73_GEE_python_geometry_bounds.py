"""Build the offline default and explicit-projection geometry bounds workflow."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def build_workflow(ee, fixture):
    """Use SDK defaults for the main path and keep null controls separate."""
    projection = ee.Projection("EPSG:4326")
    image = ee.Image(fixture["image"]["id"])
    collection = ee.ImageCollection(fixture["catalog"]["id"])
    source_feature = ee.Feature(
        ee.Geometry.Polygon(
            fixture["feature"]["geometry"]["coordinates"],
            proj=projection,
            geodesic=False,
        ),
        fixture["feature"]["properties"],
    )

    image_bounds = image.geometry().bounds()
    feature_bounds = source_feature.bounds()
    projected_image_bounds = image.geometry().bounds(proj=projection)
    projected_feature_bounds = source_feature.bounds(proj=projection)
    sample_regions = ee.FeatureCollection([projected_feature_bounds])
    rows = ee.FeatureCollection([
        ee.Feature(image_bounds, {"name": "image-geometry-bounds", "rank": 8}),
        feature_bounds,
    ])

    return {
        "image_bounds_default": image_bounds,
        "feature_bounds_default": feature_bounds,
        "image_bounds_projected": projected_image_bounds,
        "feature_bounds_projected": projected_feature_bounds,
        "filter_bounds": collection.filterBounds(projected_image_bounds),
        "clipped_image": image.clip(projected_image_bounds),
        "sample_regions": image.sampleRegions(
            collection=sample_regions,
            properties=["name", "rank"],
            geometries=True,
        ),
        "bounds_table": rows,
        "explicit_null_controls": {
            "geometry": ee.Geometry.Polygon(
                fixture["feature"]["geometry"]["coordinates"],
                proj=projection,
                geodesic=False,
            ).bounds(maxError=None, proj=None),
            "feature": source_feature.bounds(maxError=None, proj=None),
            "image": image.geometry(
                maxError=None, proj=None, geodesics=None,
            ).bounds(maxError=None, proj=None),
        },
    }


def build_numeric_references(ee, fixture):
    """Construct geodesic examples whose extrema have independent formulas."""
    references = fixture["numeric_references"]
    line = references["high_latitude_line"]
    polygon = references["high_latitude_polygon"]
    planar = references["planar_rectangle"]
    projection = ee.Projection("EPSG:4326")
    return {
        "planar_rectangle": ee.Geometry.Polygon(
            planar["coordinates"], proj=projection, geodesic=False,
        ).bounds(),
        "high_latitude_line": ee.Geometry.LineString(
            line["coordinates"],
        ).bounds(),
        "high_latitude_polygon": ee.Geometry.Polygon(
            polygon["coordinates"],
        ).bounds(),
    }


def local_sources(fixture):
    item = {
        "id": fixture["image"]["id"],
        "bbox": fixture["image"]["bbox"],
        "geometry": fixture["image"]["geometry"],
        "properties": fixture["image"]["properties"],
    }
    return [fixture["catalog"]], {fixture["catalog"]["id"]: [item]}


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.offline import OfflineGuard

    fixture = json.loads(
        (root / "tests/fixtures/ee-bounds-wave69-v2.json")
        .read_text(encoding="utf-8")
    )
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=root / "vendor/earthengine-js/algorithms.json",
        )
        workflow = build_workflow(ee, fixture)
        references = build_numeric_references(ee, fixture)
        catalog, items = local_sources(fixture)
        compiled = {
            name: compile_expression(
                ee.serializer.encode(value, for_cloud_api=False), catalog, items,
            )
            for name, value in workflow.items()
            if name != "explicit_null_controls"
        }
        numeric = {
            name: compile_expression(
                ee.serializer.encode(value, for_cloud_api=False), [], {},
            )
            for name, value in references.items()
        }
    assert guard.evidence()["attempt_count"] == 0
    print(json.dumps({
        "fixture": fixture["schema"],
        "image_bounds": compiled["image_bounds_default"]["value"],
        "feature_bounds": compiled["feature_bounds_default"]["value"],
        "numeric_bounds": {name: value["value"] for name, value in numeric.items()},
        "offline_attempts": 0,
        "google_runtime_used": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
