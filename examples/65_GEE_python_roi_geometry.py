"""Apply explicit planar ROI overlays to two synthetic Sentinel-2 scenes."""
from __future__ import annotations

import json
from pathlib import Path
import sys


OPERATIONS = (
    "contains", "containedIn", "disjoint", "intersects",
    "intersection", "union", "difference", "symmetricDifference",
)
OVERLAYS = ("intersection", "union", "difference", "symmetricDifference")


def geometry(ee, value, projection):
    """Construct a finite WGS84 geometry with explicitly planar edges."""
    if value["type"] == "Point":
        return ee.Geometry.Point(value["coordinates"], proj=projection)
    ring = value["coordinates"][0]
    xs, ys = [point[0] for point in ring], [point[1] for point in ring]
    bounds = [min(xs), min(ys), max(xs), max(ys)]
    return ee.Geometry.Rectangle(bounds, proj=projection, geodesic=False)


def build_geometry_workflow(ee, fixture):
    projection = ee.Projection("EPSG:4326")
    study = geometry(ee, fixture["regions"]["study"], projection)
    exclusion = geometry(ee, fixture["regions"]["exclusion"], projection)
    boundary = geometry(ee, fixture["regions"]["intersection_boundary_point"], projection)
    geometry_operations = {
        name: getattr(study, name)(exclusion, proj=projection) for name in OPERATIONS
    }

    left_properties = {"roi": "study", "priority": 7}
    right_properties = {"roi": "exclusion", "priority": 99}
    left = ee.Feature(study, {**left_properties, "system:index": "roi-left-base"})
    right = ee.Feature(exclusion, {**right_properties, "system:index": "roi-right"})
    feature_operations = {
        name: getattr(left, name)(right, proj=projection) for name in OPERATIONS
    }

    overlay_features = []
    for name in OVERLAYS:
        identified_left = ee.Feature(
            study, {**left_properties, "system:index": f"roi-left-{name}"},
        )
        overlay_features.append(
            getattr(identified_left, name)(right, proj=projection)
        )
    return {
        "geometry": geometry_operations,
        "feature": feature_operations,
        "boundary": {
            "study_contains_corner": study.contains(boundary, proj=projection),
            "exclusion_contains_corner": exclusion.contains(boundary, proj=projection),
            "exclusion_intersects_corner": exclusion.intersects(boundary, proj=projection),
        },
        "feature_overlays": ee.FeatureCollection(overlay_features),
        "regions": {
            "study": study,
            "intersection": geometry_operations["intersection"],
            "difference": geometry_operations["difference"],
            "union": geometry_operations["union"],
            "symmetricDifference": geometry_operations["symmetricDifference"],
        },
    }


def scene_image(ee, fixture, roi, item_id):
    """Select one local scene only after applying the study-area filter."""
    return (
        ee.ImageCollection(fixture["stac"]["collection"]["id"])
        .filterBounds(roi)
        .filter(ee.Filter.eq("system:index", item_id))
        .first()
    )


def build_image_workflow(ee, image, regions):
    source = ee.Image(image).select(["B04", "B08"]).toDouble()
    red = source.select("B04")
    nir = source.select("B08")
    ndvi = ee.Image(
        nir.subtract(red).divide(nir.add(red)).rename("NDVI"),
    )
    return {name: ndvi.clip(region) for name, region in regions.items()}


def local_sources(fixture):
    collection = fixture["stac"]["collection"]
    return [collection], {collection["id"]: [scene["item"] for scene in fixture["scenes"]]}


def compile_workflow(ee, fixture, compile_expression):
    catalog, items = local_sources(fixture)
    overlay = build_geometry_workflow(ee, fixture)
    expressions = {
        "geometry": overlay["geometry"],
        "feature": overlay["feature"],
        "boundary": overlay["boundary"],
        "feature_overlays": overlay["feature_overlays"],
        "images": {},
    }
    for scene in fixture["scenes"]:
        image = scene_image(
            ee, fixture, overlay["regions"]["study"], scene["id"],
        )
        expressions["images"][scene["id"]] = build_image_workflow(
            ee, image, overlay["regions"],
        )
    compiled = {}
    for family, values in expressions.items():
        if family == "images":
            compiled[family] = {
                scene_id: {
                    name: compile_expression(
                        ee.serializer.encode(value, for_cloud_api=False), catalog, items,
                    )
                    for name, value in outputs.items()
                }
                for scene_id, outputs in values.items()
            }
        elif family == "feature_overlays":
            compiled[family] = compile_expression(
                ee.serializer.encode(values, for_cloud_api=False), catalog, items,
            )
        else:
            compiled[family] = {
                name: compile_expression(
                    ee.serializer.encode(value, for_cloud_api=False), catalog, items,
                )
                for name, value in values.items()
            }
    return expressions, compiled


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.offline import OfflineGuard

    fixture = json.loads(
        (root / "tests/fixtures/ee-roi-geometry-wave60-v1.json")
        .read_text(encoding="utf-8")
    )
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=root / "vendor/earthengine-js/algorithms.json",
        )
        expressions, compiled = compile_workflow(ee, fixture, compile_expression)
    assert guard.evidence()["attempt_count"] == 0
    print(json.dumps({
        "fixture": fixture["schema"],
        "binary_methods": {family: sorted(values) for family, values in (
            ("geometry", expressions["geometry"]), ("feature", expressions["feature"]),
        )},
        "scene_ids": sorted(compiled["images"]),
        "image_outputs": {
            scene_id: {name: result["bands"] for name, result in outputs.items()}
            for scene_id, outputs in compiled["images"].items()
        },
        "offline_attempts": 0,
        "backend_or_google_runtime_used": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
