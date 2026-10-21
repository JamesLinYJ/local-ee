"""Synthetic inputs and independent NumPy/Rasterio constant-band references."""
import datetime as dt
from pathlib import Path
import warnings

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling, transform_bounds, transform_geom


NAMES = ["blue", "green", "red", "nir", "SCL"]
EPOCH = 1_700_000_000_000
BIG = 16_777_219
TRANSFORM = from_origin(763000, 2470000, 10, 10)
BBOX = list(transform_bounds(32649, 4326, 763000, 2469840, 763160, 2470000))


def rectangle(west, south, east, north):
    return {"type": "Polygon", "coordinates": [[[west, south], [east, south],
            [east, north], [west, north], [west, south]]]}


def create_inputs(folder: Path):
    patterns = {
        "blue": [np.nan] * 8,
        "green": [1, 2, 3, 4, 5, 6, 7, 8],
        "red": [3, 0, 1, 1, 3, 2, np.nan, 4],
        "nir": [-1, 0, 1, 3, 5, np.nan, np.nan, 4],
        "SCL": [4, 4, 9, 4, 9, 4, 4, 4],
    }
    arrays = {band: np.tile(np.array(values, dtype="float32"), (16, 2))
              for band, values in patterns.items()}
    west, south, east, north = BBOX
    geometries = [rectangle(*BBOX), rectangle(west, south, west + .6 * (east-west), north),
                  rectangle(east - .6 * (east-west), south, east, north)]
    items = []
    for iid, millis, geometry in zip("abc", [EPOCH, EPOCH+1, EPOCH], geometries):
        directory = folder / iid
        directory.mkdir()
        assets = {}
        for band in NAMES:
            path = directory / (band + ".tif")
            with rasterio.open(path, "w", driver="GTiff", width=16, height=16,
                               count=1, dtype="float32", crs=32649, transform=TRANSFORM,
                               nodata=-9999, tiled=True, blockxsize=256, blockysize=256) as target:
                target.write(np.where(np.isfinite(arrays[band]), arrays[band], -9999), 1)
            assets[band] = {
                "href": str(path), "type": "image/tiff; application=geotiff", "roles": ["data"],
                "eo:bands": [{"name": band, "common_name": band}], "proj:epsg": 32649,
                "proj:shape": [16, 16], "proj:transform": list(TRANSFORM)[:6],
                "raster:bands": [{"data_type": "float32", "scale": 1, "offset": 0, "nodata": -9999}],
            }
        items.append({
            "id": iid, "type": "Feature", "stac_version": "1.0.0", "bbox": BBOX,
            "geometry": geometry, "collection": "sentinel-2-l2a", "links": [], "assets": assets,
            "properties": {"datetime": dt.datetime.fromtimestamp(millis/1000, dt.timezone.utc).isoformat(),
                           "system:time_start": millis, "system:index": iid, "proj:epsg": 32649},
        })
    times = [item["properties"]["datetime"] for item in items]
    metadata = {
        "id": "sentinel-2-l2a", "type": "Collection", "stac_version": "1.0.0",
        "description": "Synthetic constant-band acceptance only; never added to the live catalogue.",
        "license": "proprietary", "links": [],
        "extent": {"spatial": {"bbox": [BBOX]}, "temporal": {"interval": [[min(times), max(times)]]}},
        "summaries": {"eo:bands": [{"name": band, "common_name": band} for band in NAMES]},
        "cube:dimensions": {
            "t": {"type": "temporal", "extent": [min(times), max(times)]},
            "x": {"type": "spatial", "axis": "x", "extent": [west, east], "reference_system": 4326},
            "y": {"type": "spatial", "axis": "y", "extent": [south, north], "reference_system": 4326},
            "bands": {"type": "bands", "values": NAMES},
        },
    }
    return metadata, items, arrays


def references(output, items, arrays):
    footprints = [geometry_mask([transform_geom(4326, output.crs, item["geometry"])],
                  out_shape=output.shape, transform=output.transform, invert=True) for item in items]
    full = footprints[0]
    nir = np.full(output.shape, np.nan, dtype="float64")
    reproject(arrays["nir"], nir, src_transform=TRANSFORM, src_crs=32649, src_nodata=np.nan,
              dst_transform=output.transform, dst_crs=output.crs, dst_nodata=np.nan,
              resampling=Resampling.nearest)
    def fill(value, mask=full):
        return np.where(mask, value, np.nan).astype("float64")
    dates = np.stack([fill(item["properties"]["system:time_start"], mask)
                      for item, mask in zip(items, footprints)])
    offsets = dates - EPOCH
    with warnings.catch_warnings(), np.errstate(invalid="ignore", divide="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        mean = EPOCH + np.nanmean(offsets, axis=0)
        sample_sd = np.nanstd(offsets, axis=0, ddof=1)
    count = np.isfinite(dates).sum(axis=0)
    return {
        "boundScalar": [fill(1)], "boundLarge": [fill(BIG)], "boundDate": [fill(EPOCH)],
        "boundArithmetic": [fill(7)], "maskedConstant": [np.where(full & (nir > 0), nir, np.nan), fill(7)],
        "allMaskedConstant": [fill(7)], "emptySourceConstant": [fill(7)],
        "staticMean": [fill(7, np.any(footprints, axis=0))], "dateMean": [mean],
        "dateCount": [np.where(count > 0, count, np.nan)], "dateSd": [sample_sd],
        "dateToBands": list(dates), "boundFloat": [fill(float(np.float32(BIG)))],
        "boundOverwrite": [fill(101), fill(202)],
    }
