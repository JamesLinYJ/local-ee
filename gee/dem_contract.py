"""Scientific metadata schema for the normalized local Copernicus DEM.

The version marker describes known source and raster semantics; it is not a
security attestation for files or arbitrary STAC metadata.
"""
from __future__ import annotations

from datetime import datetime
import math
import re


COLLECTION_ID = "cop-dem-glo-30"
CONTRACT_VERSION = "cop-dem-glo-30/v1"
TIFF_COG_MEDIA_TYPE = "image/tiff; application=geotiff; profile=cloud-optimized"
MAX_STRING_LENGTH = 4096
MAX_ITEM_ID_LENGTH = 250  # Leave room for the catalog's five-character ".json" suffix.
MAX_PROPERTIES = 128
MAX_COLLECTION_FIELDS = 128
MAX_DIMENSIONS = 16
MAX_RASTER_CELLS = 4_000_000
MAX_GEOMETRY_POSITIONS = 129
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LOCAL_ID = re.compile(r"[A-Za-z0-9_.-]{1,250}\Z")


class DEMContractError(ValueError):
    """A local DEM record does not satisfy the normalized schema."""


def _charge(charge, count: int) -> None:
    if not callable(charge) or type(count) is not int or count < 0:
        raise DEMContractError("DEM metadata work charge is invalid")
    charge(count)


def _mapping(value, label: str, charge, limit: int):
    if type(value) is not dict:
        raise DEMContractError(f"{label} must be an object")
    size = len(value)
    if size > limit:
        raise DEMContractError(f"{label} has too many fields")
    _charge(charge, size + 1)
    for key in value:
        if type(key) is not str or len(key) > MAX_STRING_LENGTH:
            raise DEMContractError(f"{label} keys must be bounded strings")
        _charge(charge, len(key) + 1)
    return value


def _string(value, label: str, charge, *, limit=MAX_STRING_LENGTH, nonempty=False):
    if type(value) is not str:
        raise DEMContractError(f"{label} must be a string")
    if len(value) > limit:
        raise DEMContractError(f"{label} exceeds the metadata string limit")
    _charge(charge, len(value) + 1)
    if "\x00" in value or (nonempty and not value.strip()):
        raise DEMContractError(f"{label} must be nonempty valid text")
    return value


def _finite_number(value, label: str, charge):
    _charge(charge, 1)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DEMContractError(f"{label} must be a finite number")
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        finite = False
    if not finite:
        raise DEMContractError(f"{label} must be a finite number")
    return float(value)


def _integer(value, label: str, charge, *, minimum=1, maximum=None):
    _charge(charge, 1)
    if (type(value) is not int or value < minimum
            or (maximum is not None and value > maximum)):
        bound = f" in [{minimum}, {maximum}]" if maximum is not None else f" >= {minimum}"
        raise DEMContractError(f"{label} must be an integer{bound}")
    return value


def _bounds(value, label: str, charge):
    if type(value) is not list or len(value) != 4:
        raise DEMContractError(f"{label} must be a four-value rectangle")
    _charge(charge, 4)
    west, south, east, north = (
        _finite_number(part, label, charge) for part in value
    )
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise DEMContractError(f"{label} must be a finite world-bounded rectangle")
    return west, south, east, north


def _geometry_bounds(geometry, charge):
    geometry = _mapping(geometry, "Item geometry", charge, 2)
    if set(geometry) != {"type", "coordinates"}:
        raise DEMContractError("Item geometry must contain only type and coordinates")
    if geometry["type"] != "Polygon":
        raise DEMContractError("Item geometry must be a Polygon")
    rings = geometry["coordinates"]
    if type(rings) is not list or len(rings) != 1:
        raise DEMContractError("Item geometry must contain exactly one exterior ring")
    _charge(charge, 1)
    ring = rings[0]
    if (type(ring) is not list or len(ring) < 4
            or len(ring) > MAX_GEOMETRY_POSITIONS):
        raise DEMContractError(
            f"Item geometry ring must contain 4 to {MAX_GEOMETRY_POSITIONS} positions"
        )
    _charge(charge, len(ring))
    first = previous = None
    area_twice = 0.0
    west = south = math.inf
    east = north = -math.inf
    for position in ring:
        if type(position) is not list or len(position) != 2:
            raise DEMContractError("Item geometry positions must be [longitude, latitude]")
        _charge(charge, 2)
        x = _finite_number(position[0], "Item longitude", charge)
        y = _finite_number(position[1], "Item latitude", charge)
        if not (-180 <= x <= 180 and -90 <= y <= 90):
            raise DEMContractError("Item geometry coordinates must lie within the world bounds")
        point = (x, y)
        if first is None:
            first = point
        if previous is not None:
            # Translate around the first vertex before the shoelace sum, which
            # avoids cancellation for small footprints at large coordinates.
            area_twice += (
                (previous[0] - first[0]) * (y - first[1])
                - (x - first[0]) * (previous[1] - first[1])
            )
        previous = point
        west, south = min(west, x), min(south, y)
        east, north = max(east, x), max(north, y)
    if previous != first or area_twice == 0:
        raise DEMContractError("Item geometry ring must be closed and nondegenerate")
    return west, south, east, north


def validate_dem_item(item, *, charge) -> str:
    """Validate one normalized DEM STAC item and return its local item ID.

    The scan is deliberately shallow and schema-directed. Geometry coordinates
    are charged by bounded array length before their positions are inspected.
    """
    item = _mapping(item, "DEM item", charge, 32)
    item_id = _string(item.get("id"), "DEM item id", charge,
                       limit=MAX_ITEM_ID_LENGTH, nonempty=True)
    if _LOCAL_ID.fullmatch(item_id) is None or item_id in {".", ".."}:
        raise DEMContractError("DEM item id must be one safe local path component")
    _charge(charge, 1)
    if _string(item.get("collection"), "DEM item collection", charge) != COLLECTION_ID:
        raise DEMContractError("DEM item collection must be cop-dem-glo-30")

    properties = _mapping(item.get("properties"), "DEM item properties", charge, MAX_PROPERTIES)
    contract = _string(properties.get("gee:dem_contract"), "gee:dem_contract", charge)
    if contract != CONTRACT_VERSION:
        raise DEMContractError("DEM item lacks the required cop-dem-glo-30/v1 contract marker")
    if _string(properties.get("gee:source_collection"), "gee:source_collection", charge) != COLLECTION_ID:
        raise DEMContractError("gee:source_collection must be cop-dem-glo-30")
    _string(properties.get("gee:source_id"), "gee:source_id", charge,
            limit=MAX_STRING_LENGTH, nonempty=True)
    checksum = _string(properties.get("gee:source_metadata_sha256"),
                        "gee:source_metadata_sha256", charge, limit=64)
    if _SHA256.fullmatch(checksum) is None:
        raise DEMContractError("gee:source_metadata_sha256 must be lowercase SHA-256 hex")
    if _string(properties.get("gee:vertical_datum"), "gee:vertical_datum", charge) != "EGM2008":
        raise DEMContractError("gee:vertical_datum must be EGM2008")
    if _string(properties.get("gee:cloud_mask"), "gee:cloud_mask", charge) != "not-applicable":
        raise DEMContractError("gee:cloud_mask must be not-applicable")

    date_text = _string(properties.get("datetime"), "DEM datetime", charge, limit=128, nonempty=True)
    if date_text != date_text.strip():
        raise DEMContractError("DEM datetime must be an explicit timezone-aware ISO-8601 value")
    try:
        parsed_date = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
        if parsed_date.tzinfo is None or parsed_date.utcoffset() is None:
            raise ValueError("missing timezone")
    except (OverflowError, TypeError, ValueError) as exc:
        raise DEMContractError("DEM datetime must be an explicit timezone-aware ISO-8601 value") from exc

    epsg = _integer(properties.get("proj:epsg"), "Item proj:epsg", charge,
                    maximum=2_147_483_647)
    processing = _mapping(properties.get("gee:processing"), "gee:processing", charge, 1)
    if set(processing) != {"elevation"}:
        raise DEMContractError("gee:processing must describe elevation only")
    process_band = _mapping(processing["elevation"], "gee:processing.elevation", charge, 4)
    if set(process_band) != {"source_asset", "scale", "offset", "resampling"}:
        raise DEMContractError("gee:processing.elevation has an unsupported schema")
    if _string(process_band["source_asset"], "processing source_asset", charge) != "data":
        raise DEMContractError("DEM processing source_asset must be data")
    _finite_number(process_band["scale"], "processing scale", charge)
    _finite_number(process_band["offset"], "processing offset", charge)
    if _string(process_band["resampling"], "processing resampling", charge) != "none":
        raise DEMContractError("DEM processing resampling must be none")

    bbox = _bounds(item.get("bbox"), "DEM item bbox", charge)
    geometry_bounds = _geometry_bounds(item.get("geometry"), charge)
    if any(not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9)
           for actual, expected in zip(geometry_bounds, bbox)):
        raise DEMContractError("DEM item geometry bounds must match its bbox")

    assets = _mapping(item.get("assets"), "DEM assets", charge, 1)
    if set(assets) != {"elevation"}:
        raise DEMContractError("DEM item must contain the elevation asset only")
    asset = _mapping(assets["elevation"], "DEM elevation asset", charge, 16)
    href = _string(asset.get("href"), "DEM elevation href", charge, limit=1024)
    expected_href = f"/data/assets/{COLLECTION_ID}/{item_id}/elevation.tif"
    if href != expected_href:
        raise DEMContractError("DEM elevation href must follow the local asset convention")
    if _string(asset.get("type"), "DEM elevation media type", charge) != TIFF_COG_MEDIA_TYPE:
        raise DEMContractError("DEM elevation asset must be a cloud-optimized TIFF")
    roles = asset.get("roles")
    if type(roles) is not list or len(roles) != 1:
        raise DEMContractError("DEM elevation roles must be ['data']")
    _charge(charge, 1)
    if roles != ["data"]:
        raise DEMContractError("DEM elevation roles must be ['data']")
    file_checksum = _string(asset.get("file:checksum"), "DEM file checksum", charge, limit=71)
    if not file_checksum.startswith("sha256:") or _SHA256.fullmatch(file_checksum[7:]) is None:
        raise DEMContractError("DEM file checksum must be sha256:<lowercase hex>")
    raster_bands = asset.get("raster:bands")
    if type(raster_bands) is not list or len(raster_bands) != 1:
        raise DEMContractError("DEM raster:bands must contain one normalized elevation band")
    _charge(charge, 1)
    raster_band = _mapping(raster_bands[0], "DEM raster band", charge, 8)
    if set(raster_band) != {"data_type", "scale", "offset", "unit", "nodata"}:
        raise DEMContractError("DEM raster band must be float32, meters, and NaN NoData")
    if (_string(raster_band.get("data_type"), "DEM raster data_type", charge) != "float32"
            or _string(raster_band.get("unit"), "DEM raster unit", charge) != "m"
            or _string(raster_band.get("nodata"), "DEM raster NoData", charge) != "nan"):
        raise DEMContractError("DEM raster band must be float32, meters, and NaN NoData")
    if _finite_number(raster_band.get("scale"), "raster scale", charge) != 1.0:
        raise DEMContractError("DEM normalized raster scale must be 1")
    if _finite_number(raster_band.get("offset"), "raster offset", charge) != 0.0:
        raise DEMContractError("DEM normalized raster offset must be 0")

    asset_epsg = _integer(asset.get("proj:epsg"), "Asset proj:epsg", charge,
                          maximum=2_147_483_647)
    if asset_epsg != epsg:
        raise DEMContractError("Item and elevation asset proj:epsg must match")
    shape = asset.get("proj:shape")
    if type(shape) is not list or len(shape) != 2:
        raise DEMContractError("DEM proj:shape must contain positive height and width")
    _charge(charge, 2)
    height = _integer(shape[0], "DEM proj:shape height", charge,
                      maximum=MAX_RASTER_CELLS)
    width = _integer(shape[1], "DEM proj:shape width", charge,
                     maximum=MAX_RASTER_CELLS)
    if height * width > MAX_RASTER_CELLS:
        raise DEMContractError("DEM raster exceeds the 4,000,000-cell item limit")
    transform = asset.get("proj:transform")
    if type(transform) is not list or len(transform) != 6:
        raise DEMContractError("DEM proj:transform must contain six affine values")
    _charge(charge, 6)
    affine = [_finite_number(value, "DEM proj:transform", charge) for value in transform]
    if affine[0] <= 0 or affine[4] >= 0 or affine[1] != 0 or affine[3] != 0:
        raise DEMContractError("DEM transform must be axis-aligned and north-up")
    return item_id


def validate_dem_collection(metadata, items, *, charge) -> None:
    """Validate one versioned collection and all of its bounded item metadata."""
    metadata = _mapping(metadata, "DEM collection metadata", charge, MAX_COLLECTION_FIELDS)
    if _string(metadata.get("id"), "DEM collection id", charge) != COLLECTION_ID:
        raise DEMContractError("DEM collection id must be cop-dem-glo-30")
    marker = _string(metadata.get("gee:dem_contract"), "collection gee:dem_contract", charge)
    if marker != CONTRACT_VERSION:
        raise DEMContractError("DEM collection requires the cop-dem-glo-30/v1 contract marker")
    dimensions = _mapping(metadata.get("cube:dimensions"), "DEM cube:dimensions", charge, MAX_DIMENSIONS)
    bands = _mapping(dimensions.get("bands"), "DEM band dimension", charge, 8)
    values = bands.get("values")
    if type(values) is not list or len(values) != 1:
        raise DEMContractError("DEM collection bands must be exactly ['elevation']")
    _charge(charge, 1)
    if values != ["elevation"]:
        raise DEMContractError("DEM collection bands must be exactly ['elevation']")
    units = _mapping(metadata.get("gee:units"), "DEM gee:units", charge, 1)
    if (set(units) != {"elevation"}
            or _string(units.get("elevation"), "DEM elevation unit", charge) != "m"):
        raise DEMContractError("DEM collection gee:units must be {'elevation': 'm'}")
    if type(items) is not list:
        raise DEMContractError("DEM collection items must be a finite list")
    _charge(charge, len(items))
    seen = set()
    for item in items:
        item_id = validate_dem_item(item, charge=charge)
        if item_id in seen:
            raise DEMContractError(f"Duplicate DEM item id: {item_id}")
        seen.add(item_id)
