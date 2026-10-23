"""Bounded grid, source-metadata, and COG helpers for Copernicus DEM ingest."""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import rasterio
from rasterio.errors import WindowError
from rasterio.warp import transform, transform_bounds
from rasterio.windows import Window, from_bounds
from shapely.geometry import Polygon

MAX_CELLS = 4_000_000
FLOAT32_MAX = float(np.finfo(np.float32).max)


def finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Copernicus DEM {label} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"Copernicus DEM {label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"Copernicus DEM {label} must be a finite number")
    return result


def source_date(properties):
    """Require a real timezone-qualified item time and retain its interpretation."""
    if not isinstance(properties, dict):
        raise ValueError("Copernicus DEM item properties must be an object")

    def parse(field):
        value = properties.get(field)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise ValueError(f"Copernicus DEM {field} must be a timezone-aware ISO datetime")
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Copernicus DEM {field} must be a timezone-aware ISO datetime") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"Copernicus DEM {field} must include an explicit timezone")
        return value.strip(), parsed

    datetime_value = parse("datetime")
    start_value = parse("start_datetime")
    end_value = parse("end_datetime")
    chosen = datetime_value or start_value
    if chosen is None:
        raise ValueError("Copernicus DEM item requires explicit datetime or start_datetime metadata")
    if start_value and end_value and start_value[1] > end_value[1]:
        raise ValueError("Copernicus DEM provider interval is reversed")
    interval = None
    if start_value or end_value:
        interval = {
            "start_datetime": start_value[0] if start_value else None,
            "end_datetime": end_value[0] if end_value else None,
        }
    return chosen[0], "datetime" if datetime_value else "start_datetime", interval, chosen[1]


def requested_bbox(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("Copernicus DEM requested bbox must contain four WGS84 coordinates")
    result = [finite_number(v, "requested bbox coordinate") for v in value]
    west, south, east, north = result
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Copernicus DEM requested bbox must be a nonempty WGS84 rectangle")
    return result


def band_metadata(asset):
    bands = asset.get("raster:bands")
    if bands is None:
        return None
    if not isinstance(bands, list) or len(bands) != 1 or not isinstance(bands[0], dict):
        raise ValueError("Copernicus DEM data asset must declare exactly one raster band")
    return bands[0]


def scale_offset(stac_band, src):
    """Honor STAC precedence while rejecting disagreement with declared TIFF values."""
    stac_scale = finite_number(stac_band["scale"], "scale") if stac_band and "scale" in stac_band else None
    stac_offset = finite_number(stac_band["offset"], "offset") if stac_band and "offset" in stac_band else None
    tiff_scale = finite_number(src.scales[0], "TIFF scale")
    tiff_offset = finite_number(src.offsets[0], "TIFF offset")
    if stac_scale is not None and tiff_scale != 1.0 and stac_scale != tiff_scale:
        raise ValueError("Copernicus DEM STAC scale conflicts with the TIFF scale")
    if stac_offset is not None and tiff_offset != 0.0 and stac_offset != tiff_offset:
        raise ValueError("Copernicus DEM STAC offset conflicts with the TIFF offset")
    return (stac_scale if stac_scale is not None else tiff_scale), (
        stac_offset if stac_offset is not None else tiff_offset
    )


def source_unit(stac_band, src):
    stac_unit = stac_band.get("unit") if stac_band else None
    tiff_unit = src.units[0] if src.units else None
    for unit in (stac_unit, tiff_unit):
        if unit is not None and (not isinstance(unit, str) or unit.strip() != "m"):
            raise ValueError("Copernicus DEM source unit must be metres (m)")
    if stac_unit is not None and tiff_unit is not None and stac_unit.strip() != tiff_unit.strip():
        raise ValueError("Copernicus DEM STAC and TIFF source units conflict")
    return "m"


def _nodata_number(value, label):
    if isinstance(value, str) and value.strip().lower() == "nan":
        return float("nan")
    return finite_number(value, label)


def check_nodata(stac_band, src):
    """Require declarations to agree; a STAC-only sentinel adds to the TIFF mask."""
    if not stac_band or stac_band.get("nodata") is None:
        return None
    stac_nodata = _nodata_number(stac_band["nodata"], "NoData")
    tiff_nodata = src.nodata
    if tiff_nodata is not None:
        if math.isnan(float(tiff_nodata)):
            agrees = math.isnan(stac_nodata)
        else:
            agrees = stac_nodata == tiff_nodata
        if not agrees:
            raise ValueError("Copernicus DEM STAC NoData conflicts with the TIFF NoData")
        return None
    return stac_nodata


def nodata_mask(data, stac_nodata):
    if stac_nodata is None:
        return np.zeros(data.shape, dtype=bool)
    if math.isnan(stac_nodata):
        return np.isnan(data)
    return data == stac_nodata


def crop_window(src, bbox):
    crs = src.crs
    if crs is None:
        raise ValueError("Copernicus DEM TIFF must declare a CRS")
    epsg = crs.to_epsg()
    if epsg is None:
        raise ValueError("Copernicus DEM CRS must have an EPSG identifier")
    affine = src.transform
    if not all(math.isfinite(v) for v in affine[:6]):
        raise ValueError("Copernicus DEM source affine must be finite")
    if not (affine.b == 0 and affine.d == 0 and affine.a > 0 and affine.e < 0):
        raise ValueError("Copernicus DEM source grid must be axis-aligned and north-up")
    transformed = transform_bounds("EPSG:4326", crs, *bbox, densify_pts=21)
    if not all(math.isfinite(v) for v in transformed):
        raise ValueError("Copernicus DEM requested bbox cannot be transformed into the source CRS")
    raw = from_bounds(*transformed, transform=affine)
    left, top = math.floor(raw.col_off), math.floor(raw.row_off)
    right = math.ceil(raw.col_off + raw.width)
    bottom = math.ceil(raw.row_off + raw.height)
    if right <= left or bottom <= top:
        raise ValueError("Copernicus DEM requested area does not intersect the source grid")
    try:
        window = Window(left, top, right - left, bottom - top).intersection(Window(0, 0, src.width, src.height))
    except WindowError as exc:
        raise ValueError("Copernicus DEM requested area does not intersect the source grid") from exc
    if window.width <= 0 or window.height <= 0:
        raise ValueError("Copernicus DEM requested area does not intersect the source grid")
    width, height = int(window.width), int(window.height)
    if width * height > MAX_CELLS:
        raise ValueError("Copernicus DEM normalization is limited to 4 million source pixels")
    return window, width, height, int(epsg), src.window_transform(window)


def grid_geometry(crs, affine, width, height):
    """Transform a densified source-window boundary to a WGS84 polygon."""
    n = 32
    pixels = []
    for i in range(n):
        pixels.append((width * i / n, 0))
    for i in range(n):
        pixels.append((width, height * i / n))
    for i in range(n):
        pixels.append((width * (n - i) / n, height))
    for i in range(n):
        pixels.append((0, height * (n - i) / n))
    xs, ys = zip(*(affine @ pixel for pixel in pixels))
    out_x, out_y = transform(crs, "EPSG:4326", xs, ys)
    coords = list(zip(out_x, out_y))
    if not all(math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90
               for x, y in coords):
        raise ValueError("Copernicus DEM cropped grid has an invalid WGS84 footprint")
    polygon = Polygon(coords)
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
        raise ValueError("Copernicus DEM cropped grid has an invalid WGS84 footprint")
    return polygon, [float(v) for v in polygon.bounds]


def write_dem_cog(array, profile, path, budget):
    budget.reserve(array.nbytes * 2 + 1024 * 1024, target=path.parent)
    tmp = path.with_suffix(".part.tif")
    try:
        with rasterio.open(
            tmp,
            "w",
            driver="COG",
            height=array.shape[0],
            width=array.shape[1],
            count=1,
            dtype="float32",
            nodata=float("nan"),
            crs=profile["crs"],
            transform=profile["transform"],
            compress="DEFLATE",
            blocksize=256,
        ) as dst:
            dst.write(array, 1)
            dst.set_band_unit(1, "m")
        with rasterio.open(tmp) as check:
            layout = check.tags(ns="IMAGE_STRUCTURE").get("LAYOUT")
            if (check.width != array.shape[1] or check.height != array.shape[0] or
                    check.count != 1 or check.dtypes != ("float32",) or check.crs != profile["crs"] or
                    check.transform != profile["transform"] or not np.isnan(check.nodata) or layout != "COG"):
                raise ValueError("Copernicus DEM COG verification failed")
            verified = check.read(1, masked=True)
            expected_mask = np.isnan(array)
            if not np.array_equal(np.ma.getmaskarray(verified), expected_mask):
                raise ValueError("Copernicus DEM COG mask verification failed")
            if not np.array_equal(verified.data[~expected_mask], array[~expected_mask]):
                raise ValueError("Copernicus DEM COG pixel verification failed")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def metadata_work_counter(limit):
    used = 0

    def charge(count=1):
        nonlocal used
        if type(count) is not int or count < 0:
            raise ValueError("Copernicus DEM metadata work charge must be a nonnegative integer")
        used += count
        if used > limit:
            raise ValueError(f"Copernicus DEM metadata validation exceeded {limit:,} work units")

    return charge
