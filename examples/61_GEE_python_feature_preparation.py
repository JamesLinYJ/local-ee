"""Prepare station Features locally with typed metadata and explicit geometry.

The source rows and catalogue are synthetic, versioned fixtures. Compilation
uses the pinned offline Earth Engine SDK and the local bounded compiler; this
example makes no Google service request and does not require raster data.
"""
from __future__ import annotations

import json
from pathlib import Path


def station_feature(ee, row):
    geometry = None if row["geometry"] is None else ee.Geometry(row["geometry"])
    properties = dict(row["properties"])
    properties["samples"] = ee.Array(properties["samples"])
    properties["system:index"] = row["id"]
    return ee.Feature(geometry, properties)


def prepare_station(ee, feature, fixture):
    """Rename measured fields, retain identity, and rebuild a declared point."""
    selectors = fixture["filter"]["selectors"]
    names = fixture["filter"]["renamed_fields"]
    source_geometry = feature.geometry()
    renamed = ee.Feature(feature.select(selectors, names, retainGeometry=True))
    reading = feature.getNumber("reading")
    height_m = feature.getNumber("height_m")
    station_name = feature.getString("station_name")
    quality = feature.getString("quality")
    longitude = feature.getNumber("longitude")
    latitude = feature.getNumber("latitude")
    samples = feature.getArray("samples")
    additions = {
        "source_id": feature.id(),
        "station_name": station_name,
        "reading": reading,
        "height_m": height_m,
        "quality_flag": quality,
        "longitude": longitude,
        "latitude": latitude,
        "samples": samples,
        "typed_reading": reading,
        "typed_samples": samples,
        "reading_vector": feature.toArray(["reading", "height_m"]),
        "source_fields": feature.toDictionary(["station_code", "reading"]),
        "score": reading.add(height_m.divide(8)),
        "source_geometry_type": source_geometry.type(),
        "source_geometry_coordinates": source_geometry.coordinates(),
    }
    declared_point = ee.Geometry.Point(
        [longitude, latitude], "EPSG:4326",
    )
    return renamed.setGeometry(declared_point).set(additions)


def build_station_workflow(ee, fixture):
    """Filter by station metadata and calendar range, then prepare rows."""
    source = ee.FeatureCollection([
        station_feature(ee, row) for row in fixture["rows"]
    ])
    limits = fixture["filter"]
    predicate = ee.Filter.And(
        ee.Filter.stringStartsWith("station_code", limits["station_prefix"]),
        ee.Filter.stringEndsWith("station_code", limits["station_suffix"]),
        ee.Filter.gte("reading", limits["reading_min_inclusive"]),
        ee.Filter.lte("reading", limits["reading_max_inclusive"]),
        ee.Filter.calendarRange(
            limits["day_of_year_min_inclusive"],
            limits["day_of_year_max_inclusive"],
            field="day_of_year",
        ),
    )
    metadata_selected = source.filter(predicate)
    region = ee.Geometry.Rectangle(limits["bounds"], "EPSG:4326", False)
    spatially_selected = metadata_selected.filterBounds(region)
    prepared = spatially_selected.map(
        lambda feature: prepare_station(ee, feature, fixture)
    )
    null_geometry_control = ee.Feature(
        None, {"system:index": "null-geometry-control", "kind": "control"}
    ).setGeometry(None)
    return {
        "metadata_ids": metadata_selected.aggregate_array("system:index"),
        "metadata_count": metadata_selected.size(),
        "station_ids": prepared.aggregate_array("source_id"),
        "station_count": prepared.size(),
        "stations": prepared,
        "null_geometry_control": null_geometry_control,
    }


def build_catalog_workflow(ee, fixture):
    """Filter a declared local image catalogue and read typed item metadata."""
    limits = fixture["catalog"]
    collection = ee.ImageCollection(limits["collection_id"])
    predicate = ee.Filter.And(
        ee.Filter.stringStartsWith("system:index", limits["id_prefix"]),
        ee.Filter.stringEndsWith("system:index", limits["id_suffix"]),
        ee.Filter.gte("cloud", limits["cloud_min_inclusive"]),
        ee.Filter.lte("cloud", limits["cloud_max_inclusive"]),
        ee.Filter.calendarRange(
            limits["day_of_year_min_inclusive"],
            limits["day_of_year_max_inclusive"],
            field="day_of_year",
        ),
    )
    region = ee.Geometry.Rectangle(
        fixture["filter"]["bounds"], "EPSG:4326", False
    )
    selected = collection.filter(predicate).filterBounds(region)
    tagged = selected.map(lambda image: image.set({
        "cloud_typed": image.getNumber("cloud"),
        "scene_id_typed": image.getString("system:index"),
    }))
    first = selected.first()
    return {
        "image_ids": selected.aggregate_array("system:index"),
        "cloud_values": selected.aggregate_array("cloud"),
        "typed_cloud": first.getNumber("cloud"),
        "typed_scene_id": first.getString("system:index"),
        "mapped_typed_clouds": tagged.aggregate_array("cloud_typed"),
    }


def main():
    root = Path(__file__).resolve().parents[1]
    fixture_path = root / "tests/fixtures/ee-feature-preparation-wave56-v1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    from scripts.ee_python_api.offline import OfflineGuard
    from scripts.ee_python_api.probe_cases import synthetic_inputs
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression

    catalog, items, _ = synthetic_inputs()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2",
            "a" * 48,
            signatures_path=root / "vendor/earthengine-js/algorithms.json",
        )
        workflows = {
            "stations": build_station_workflow(ee, fixture),
            "catalog": build_catalog_workflow(ee, fixture),
        }
        compiled = {
            mode: {
                name: compile_expression(
                    ee.serializer.encode(value, for_cloud_api=False),
                    [catalog], items,
                )
                for name, value in outputs.items()
            }
            for mode, outputs in workflows.items()
        }
    assert guard.evidence()["attempt_count"] == 0
    print(json.dumps({
        "fixture": fixture["schema"],
        "station_ids": compiled["stations"]["station_ids"]["value"],
        "station_count": compiled["stations"]["station_count"]["value"],
        "catalog_ids": compiled["catalog"]["image_ids"]["value"],
        "catalog_clouds": compiled["catalog"]["cloud_values"]["value"],
        "network_attempts": 0,
        "services_used": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
