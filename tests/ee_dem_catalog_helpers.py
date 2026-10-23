"""Small normalized DEM fixtures for compiler-only contract checks."""
from copy import deepcopy

from gee.dem_contract import (
    COLLECTION_ID,
    CONTRACT_VERSION,
    TIFF_COG_MEDIA_TYPE,
)


def collection_metadata():
    return {
        "type": "Collection",
        "stac_version": "1.0.0",
        "id": COLLECTION_ID,
        "gee:dem_contract": CONTRACT_VERSION,
        "cube:dimensions": {
            "bands": {"type": "bands", "values": ["elevation"]},
        },
        "gee:units": {"elevation": "m"},
    }


def dem_item(item_id="dem-a", date="2020-01-01T00:00:00Z"):
    west, south, east, north = 100.0, 30.0, 101.0, 31.0
    return {
        "type": "Feature",
        "id": item_id,
        "collection": COLLECTION_ID,
        "bbox": [west, south, east, north],
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [west, south], [east, south], [east, north],
                [west, north], [west, south],
            ]],
        },
        "properties": {
            "datetime": date,
            "gee:dem_contract": CONTRACT_VERSION,
            "gee:source_collection": COLLECTION_ID,
            "gee:source_id": f"source-{item_id}",
            "gee:source_metadata_sha256": "a" * 64,
            "gee:vertical_datum": "EGM2008",
            "gee:cloud_mask": "not-applicable",
            "gee:processing": {
                "elevation": {
                    "source_asset": "data",
                    "scale": 1.0,
                    "offset": 0.0,
                    "resampling": "none",
                },
            },
            "proj:epsg": 4326,
        },
        "assets": {
            "elevation": {
                "href": f"/data/assets/{COLLECTION_ID}/{item_id}/elevation.tif",
                "type": TIFF_COG_MEDIA_TYPE,
                "roles": ["data"],
                "file:checksum": "sha256:" + "b" * 64,
                "raster:bands": [{
                    "data_type": "float32",
                    "scale": 1.0,
                    "offset": 0.0,
                    "unit": "m",
                    "nodata": "nan",
                }],
                "proj:epsg": 4326,
                "proj:shape": [100, 100],
                "proj:transform": [0.01, 0.0, west, 0.0, -0.01, north],
            },
        },
    }


def compiler_catalog(items=None):
    return [collection_metadata()], {
        COLLECTION_ID: [deepcopy(item) for item in (items or [])],
    }
