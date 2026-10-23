"""Copernicus DEM normalization on the provider's original pixel grid."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import numpy as np
import rasterio
from shapely.geometry import mapping

from . import db
from . import dem_ingest_helpers as helpers

COLLECTION_ID = "cop-dem-glo-30"
FINGERPRINT_VERSION = "normalize-dem-v1"
MAX_METADATA_WORK = 50_000
ROOT = None  # Tests and trusted wrappers may override the normalizer's data root.


def register(*args, **kwargs):
    """Late-bind the shared publisher so ingest can import this module lazily."""
    from .ingest import register as publish

    return publish(*args, **kwargs)


def _helpers():
    from . import ingest

    return ingest


def _root(ingest):
    return Path(ROOT) if ROOT is not None else Path(ingest.ROOT)


def _validate_contract(meta, item, charge):
    from .dem_contract import CONTRACT_VERSION, validate_dem_collection, validate_dem_item

    meta["gee:dem_contract"] = CONTRACT_VERSION
    item["properties"]["gee:dem_contract"] = CONTRACT_VERSION
    validate_dem_item(item, charge=charge)
    validate_dem_collection(meta, [item], charge=charge)


def optical_dem_item(item, bbox, sign=lambda x: x, budget=None):
    """Normalize one Copernicus DEM item without changing its source grid."""
    ingest = _helpers()
    root = _root(ingest)
    if not isinstance(item, dict) or item.get("collection") != COLLECTION_ID:
        raise ValueError("Copernicus DEM source collection must be cop-dem-glo-30")
    source_id = item.get("id")
    if (not isinstance(source_id, str) or not source_id.strip() or "\x00" in source_id
            or len(source_id) > 233):
        raise ValueError("Copernicus DEM item source id must contain 1 to 233 characters")
    properties = item.get("properties")
    date, date_field, provider_interval, date_instant = helpers.source_date(properties)
    source_version = next((value for value in (
        item.get("version"), properties.get("version"),
        properties.get("copernicus:product_version"), properties.get("copernicus:version"),
    ) if value is not None), None)
    if source_version is not None and not isinstance(source_version, (str, int, float)):
        raise ValueError("Copernicus DEM source version must be a JSON scalar")
    if isinstance(source_version, bool):
        raise ValueError("Copernicus DEM source version must be a JSON scalar")
    if isinstance(source_version, float) and not np.isfinite(source_version):
        raise ValueError("Copernicus DEM source version must be finite")
    if isinstance(source_version, int) and abs(source_version) > 2**63 - 1:
        raise ValueError("Copernicus DEM source version integer is out of range")
    if isinstance(source_version, str) and (len(source_version) > 128 or "\x00" in source_version):
        raise ValueError("Copernicus DEM source version must be bounded valid text")
    for key in ("vertical_datum", "copernicus:vertical_datum"):
        datum = properties.get(key)
        if datum is not None and datum != "EGM2008":
            raise ValueError("Copernicus DEM vertical datum must be EGM2008")
    requested_bbox = helpers.requested_bbox(bbox)
    assets = item.get("assets")
    if not isinstance(assets, dict) or not isinstance(assets.get("data"), dict):
        raise ValueError("Copernicus DEM item must contain one data asset")
    source_asset = assets["data"]
    href = source_asset.get("href")
    if not isinstance(href, str) or not href:
        raise ValueError("Copernicus DEM data asset requires an href")

    try:
        source_json = json.dumps(item, sort_keys=True, indent=2, allow_nan=False).encode("utf-8")
        fingerprint_payload = json.dumps(
            [item, requested_bbox, FINGERPRINT_VERSION],
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Copernicus DEM source metadata must be finite JSON") from exc
    source_metadata_hash = hashlib.sha256(source_json).hexdigest()
    fingerprint = hashlib.sha256(fingerprint_payload).hexdigest()[:16]
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", source_id)
    if not safe_id or len(safe_id) > 233:
        raise ValueError("Copernicus DEM source id cannot form a safe bounded local id")
    item_id = f"{safe_id}-{fingerprint}"
    if len(item_id) > 250:
        raise ValueError("Copernicus DEM normalized item id and catalog suffix exceed the filename limit")
    if db.query("SELECT id FROM items WHERE id=%s", (item_id,), one=True):
        return item_id

    asset_band = helpers.band_metadata(source_asset)
    dates = [date_instant.isoformat(), date_instant.isoformat()]
    if budget is None:
        budget = ingest.IngestBudget()

    with rasterio.open(sign(href), driver="GTiff") as src:
        if src.count != 1:
            raise ValueError("Copernicus DEM data asset must be a single-band GeoTIFF")
        source_dtype = np.dtype(src.dtypes[0])
        if source_dtype.kind not in "iuf":
            raise ValueError("Copernicus DEM source raster must have a real numeric data type")
        # Casting int64/uint64 to float64 can silently change valid raw values
        # above 2**53 before scale/offset are applied (and can change the
        # resulting Float32 value when an offset nearly cancels the raw value).
        # Copernicus DEM's encoded elevations and supported provider fixtures
        # fit in at most 32-bit integer storage, whose values convert exactly.
        if source_dtype.kind in "iu" and source_dtype.itemsize > 4:
            raise ValueError("Copernicus DEM integer source raster must be at most 32-bit")
        scale, offset = helpers.scale_offset(asset_band, src)
        unit = helpers.source_unit(asset_band, src)
        stac_nodata = helpers.check_nodata(asset_band, src)
        window, width, height, epsg, out_transform = helpers.crop_window(src, requested_bbox)
        raw = src.read(1, window=window, masked=True)
        raw_data = np.asarray(raw.data)
        source_mask = np.ma.getmaskarray(raw) | helpers.nodata_mask(raw_data, stac_nodata)
        valid_source = ~source_mask
        if np.any(valid_source & ~np.isfinite(raw_data)):
            raise ValueError("Copernicus DEM contains valid nonfinite source pixels")
        with np.errstate(over="ignore", invalid="ignore"):
            physical = raw_data.astype(np.float64) * scale + offset
        if np.any(valid_source & ~np.isfinite(physical)):
            raise ValueError("Copernicus DEM scale/offset produced a nonfinite valid elevation")
        if np.any(valid_source & (np.abs(physical) > helpers.FLOAT32_MAX)):
            raise ValueError("Copernicus DEM valid elevation exceeds Float32 range")
        normalized = np.full((height, width), np.nan, dtype=np.float32)
        normalized[valid_source] = physical[valid_source].astype(np.float32)
        profile = {"crs": src.crs, "transform": out_transform, "height": height, "width": width}
        source_crs = src.crs

    geometry, actual_bbox = helpers.grid_geometry(source_crs, out_transform, width, height)
    folder = root / "assets" / COLLECTION_ID / item_id
    catalog_item_path = root / "catalog" / COLLECTION_ID / f"{item_id}.json"
    catalog_tmp_path = catalog_item_path.with_suffix(".tmp")
    if catalog_item_path.exists() or catalog_tmp_path.exists():
        raise ValueError("Copernicus DEM catalog artifact already exists without a database item")
    folder.parent.mkdir(parents=True, exist_ok=True)
    try:
        folder.mkdir(exist_ok=False)
    except FileExistsError as exc:
        # A prior filesystem artifact with no catalog row is not ours to overwrite.
        raise ValueError("Copernicus DEM output path already exists without a catalog item") from exc

    published = False
    register_started = False
    try:
        budget.reserve(len(source_json), target=root / "assets")
        (folder / "source.json").write_bytes(source_json)
        cog_path = folder / "elevation.tif"
        helpers.write_dem_cog(normalized, profile, cog_path, budget)
        item_asset = {
            "href": f"/data/assets/{COLLECTION_ID}/{item_id}/elevation.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "eo:bands": [{"name": "elevation"}],
            "raster:bands": [{
                "data_type": "float32", "nodata": "nan", "scale": 1, "offset": 0, "unit": unit,
            }],
            "proj:epsg": epsg,
            "proj:shape": [height, width],
            "proj:transform": list(out_transform)[:6],
            "file:checksum": "sha256:" + ingest.sha256(cog_path),
        }
        local = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "stac_extensions": [
                "https://stac-extensions.github.io/eo/v1.1.0/schema.json",
                "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
                "https://stac-extensions.github.io/raster/v1.1.0/schema.json",
            ],
            "id": item_id,
            "collection": COLLECTION_ID,
            "bbox": actual_bbox,
            "geometry": json.loads(json.dumps(mapping(geometry))),
            "links": [],
            "properties": {
                "datetime": date,
                "proj:epsg": epsg,
                "gee:dem_contract": "cop-dem-glo-30/v1",
                "gee:source_collection": COLLECTION_ID,
                "gee:source_id": source_id,
                "gee:source_version": source_version,
                "gee:source_metadata_sha256": source_metadata_hash,
                "gee:source_metadata": f"/data/assets/{COLLECTION_ID}/{item_id}/source.json",
                "gee:requested_bbox": requested_bbox,
                "gee:vertical_datum": "EGM2008",
                "gee:cloud_mask": "not-applicable",
                "gee:processing": {
                    "elevation": {
                        "source_asset": "data", "scale": scale, "offset": offset, "resampling": "none",
                    },
                },
                "gee:datetime_interpretation": date_field,
                **({"gee:provider_interval": provider_interval} if provider_interval is not None else {}),
            },
            "assets": {"elevation": item_asset},
        }
        meta = ingest.collection_metadata(
            COLLECTION_ID, "Copernicus DEM · 30 m", ["elevation"], actual_bbox, dates, {"elevation": unit}
        )
        meta["summaries"]["eo:bands"] = [{"name": "elevation"}]
        license_value = properties.get("license")
        meta["license"] = license_value if isinstance(license_value, str) else "various"
        charge = helpers.metadata_work_counter(MAX_METADATA_WORK)
        _validate_contract(meta, local, charge)
        register_started = True
        register(COLLECTION_ID, meta, local, budget=budget)
        published = True
        return item_id
    except Exception:
        if not published:
            publication_state_known = True
            persisted = None
            if register_started:
                try:
                    persisted = db.query("SELECT id FROM items WHERE id=%s", (item_id,), one=True)
                except Exception:
                    publication_state_known = False
            if not publication_state_known or persisted:
                # The publisher may have committed before a sidecar write failed.
                raise
            for candidate in (catalog_item_path, catalog_tmp_path):
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass
            shutil.rmtree(folder, ignore_errors=True)
        raise
