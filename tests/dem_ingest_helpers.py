"""Synthetic GTiff and provider-item fixtures for DEM normalization tests."""
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


class Budget:
    def __init__(self):
        self.reserved = []

    def reserve(self, amount, target=None):
        self.reserved.append((amount, Path(target) if target is not None else None))


def write_source(path, values=None, *, crs="EPSG:4326", transform=None, nodata=-32768,
                 scale=1, offset=0, unit=None, dtype=None):
    path = Path(path)
    if values is None:
        values = np.arange(16, dtype=np.int16).reshape(4, 4)
    values = np.asarray(values)
    if values.ndim == 2:
        count, height, width = 1, *values.shape
        values_to_write = values[None, ...]
    elif values.ndim == 3:
        count, height, width = values.shape
        values_to_write = values
    else:
        raise ValueError("Fixture raster must be 2D or bands-by-rows-by-columns")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=count,
        dtype=dtype or values.dtype,
        transform=transform or from_origin(0, 4, 1, 1),
        crs=crs,
        nodata=nodata,
    ) as dst:
        dst.write(values_to_write.astype(dtype or values.dtype), indexes=list(range(1, count + 1)))
        dst.scales = tuple(scale for _ in range(count))
        dst.offsets = tuple(offset for _ in range(count))
        if unit is not None:
            for band in range(1, count + 1):
                dst.set_band_unit(band, unit)
    return path


def source_item(path, *, bands=None, extra_assets=None, item_id="synthetic-dem"):
    assets = {
        "data": {
            "href": str(path),
            **({"raster:bands": bands} if bands is not None else {}),
        },
    }
    assets.update(extra_assets or {})
    return {
        "type": "Feature",
        "id": item_id,
        "collection": "cop-dem-glo-30",
        "properties": {"datetime": "2021-04-22T00:00:00Z"},
        "assets": assets,
    }


def item_band(*, scale=1, offset=0, unit="m", nodata=-32768, data_type="int16"):
    band = {"data_type": data_type, "nodata": nodata, "scale": scale, "offset": offset}
    if unit is not None:
        band["unit"] = unit
    return [band]
