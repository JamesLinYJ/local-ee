"""Deterministic synthetic source DEMs for local ingest workflow tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.warp import transform_bounds
from shapely.geometry import box, mapping

from gee.dem_contract import COLLECTION_ID


SOURCE_SCALE = 0.25
SOURCE_OFFSET = 100.0
SOURCE_NODATA = -2147483648
WIDTH = 16
HEIGHT = 16


def _surface():
    """Flat, sun-facing and sun-opposed strips with two distinct source masks."""
    by_col = []
    for col in range(WIDTH):
        if col <= 3:
            elevation = 0.0
        elif col <= 8:
            elevation = (col - 3) * 10.0
        else:
            elevation = 50.0 - (col - 8) * 10.0
        by_col.append(elevation)
    meters = np.broadcast_to(np.asarray(by_col, dtype=np.float64), (HEIGHT, WIDTH)).copy()
    raw = np.rint(meters / SOURCE_SCALE).astype(np.int32)
    valid = np.ones((HEIGHT, WIDTH), dtype=bool)
    raw[7, 5] = SOURCE_NODATA
    valid[7, 5] = False  # nodata sentinel
    valid[5, 10] = False  # internal GeoTIFF mask independent of nodata
    raw[3, 14] = int((-9999.0 - SOURCE_OFFSET) / SOURCE_SCALE)
    return raw, valid


def source_cases():
    """One UTM grid and one geographic grid, each 16x16 and north-up."""
    grids = (
        {
            "name": "projected-utm",
            "source_id": "synthetic-utm-dem",
            "crs": "EPSG:32610",
            "transform": Affine(10.0, 0.0, 500000.0, 0.0, -10.0, 4100160.0),
            "request_bbox": [-123.02, 37.0, -122.98, 37.09],
        },
        {
            "name": "geographic",
            "source_id": "synthetic-geographic-dem",
            "crs": "EPSG:4326",
            "transform": Affine(0.0001, 0.0, 15.0, 0.0, -0.0001, 0.0016),
            "request_bbox": [14.99, -0.001, 15.01, 0.003],
        },
    )
    raw, valid = _surface()
    return [
        {**grid, "raw": raw.copy(), "valid": valid.copy(),
         "width": WIDTH, "height": HEIGHT,
         "scale": SOURCE_SCALE, "offset": SOURCE_OFFSET}
        for grid in grids
    ]


def fixture_hash_payload() -> str:
    """Canonical source sample content used by the portable probe-hash test."""
    raw, valid = _surface()
    records = []
    for grid in source_cases():
        records.append({
            "name": grid["name"], "crs": grid["crs"],
            "transform": list(grid["transform"]),
            "request_bbox": grid["request_bbox"],
            "width": WIDTH, "height": HEIGHT,
            "scale": SOURCE_SCALE, "offset": SOURCE_OFFSET,
            "raw": raw.tolist(), "valid": valid.astype(int).tolist(),
        })
    return json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fixture_sha256() -> str:
    return hashlib.sha256(fixture_hash_payload().encode("utf-8")).hexdigest()


def write_source_geotiff(path: Path, case: dict) -> None:
    """Write a private, masked integer GeoTIFF with matching STAC/TIFF scale."""
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff", "height": case["height"], "width": case["width"],
        "count": 1, "dtype": "int32", "crs": case["crs"],
        "transform": case["transform"], "nodata": SOURCE_NODATA,
        "compress": "DEFLATE",
    }
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
        with rasterio.open(path, "w", **profile) as dataset:
            dataset.write(case["raw"], 1)
            dataset.write_mask(case["valid"].astype(np.uint8) * 255)
            dataset.scales = (case["scale"],)
            dataset.offsets = (case["offset"],)
            dataset.units = ("m",)


def source_item(path: Path, case: dict) -> dict:
    """Provider-shaped synthetic STAC source record for the real normalizer."""
    affine = case["transform"]
    bounds = (
        affine.c, affine.f - case["height"] * abs(affine.e),
        affine.c + case["width"] * affine.a, affine.f,
    )
    bbox = list(transform_bounds(case["crs"], "EPSG:4326", *bounds, densify_pts=21))
    return {
        "type": "Feature", "id": case["source_id"],
        "collection": COLLECTION_ID, "bbox": bbox,
        "geometry": mapping(box(*bbox)),
        "assets": {
            "data": {
                "href": str(path),
                "raster:bands": [{
                    "data_type": "int32", "nodata": SOURCE_NODATA,
                    "scale": case["scale"], "offset": case["offset"], "unit": "m",
                }],
            },
        },
        "properties": {
            "datetime": "2024-01-02T03:04:05Z",
            "license": "CC-BY-4.0",
            "vertical_datum": "EGM2008",
        },
    }


def assert_source_geotiff(path: Path, case: dict) -> None:
    """Confirm the synthetic provider file carries a real TIFF mask and scale."""
    with rasterio.open(path) as dataset:
        assert dataset.count == 1 and dataset.dtypes == ("int32",)
        assert dataset.crs.to_string() == case["crs"]
        assert dataset.transform == case["transform"]
        assert dataset.nodata == SOURCE_NODATA
        assert dataset.scales == (case["scale"],) and dataset.offsets == (case["offset"],)
        assert dataset.units == ("m",)
        source = dataset.read(1, masked=True)
        assert np.array_equal(np.ma.getmaskarray(source), ~case["valid"])
        assert source.data[3, 14] == -40396
