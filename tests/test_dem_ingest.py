"""Focused tests for source-grid Copernicus DEM normalization."""
import hashlib
import json

import numpy as np
import pytest
import rasterio

from gee import dem_ingest, ingest
from dem_ingest_helpers import Budget, item_band, source_item, write_source


@pytest.fixture
def captured_ingest(tmp_path, monkeypatch):
    monkeypatch.setattr(dem_ingest, "ROOT", tmp_path)
    stored_ids = set()
    registered = []

    def query(sql, params, one=False):
        return {"id": params[0]} if params[0] in stored_ids else None

    def register(cid, metadata, item, budget=None):
        registered.append((cid, metadata, item))
        stored_ids.add(item["id"])

    monkeypatch.setattr(dem_ingest.db, "query", query)
    monkeypatch.setattr(dem_ingest, "register", register)
    return registered, stored_ids


def test_cop_dem_route_writes_physical_cog_with_nan_mask_and_real_grid(tmp_path, captured_ingest):
    registered, _ = captured_ingest
    values = np.array([
        [0, 1, 2, 3],
        [4, -32768, 6, 7],
        [-400, 9, -9999, 11],
        [12, 13, 14, 15],
    ], dtype=np.int16)
    source = write_source(tmp_path / "provider.tif", values, nodata=-32768)
    item = source_item(
        source,
        bands=item_band(scale=0.25, offset=100),
        extra_assets={"thumbnail": {"href": "https://example.invalid/preview.jpg"}},
    )
    requested = [0.2, 0.2, 2.2, 2.2]

    item_id = ingest.optical_item(item, "cop-dem-glo-30", requested, budget=Budget())

    assert len(registered) == 1
    _, collection, normalized = registered[0]
    assert item_id.endswith(hashlib.sha256(json.dumps(
        [item, requested, "normalize-dem-v1"], sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()[:16])
    assert collection["gee:dem_contract"] == "cop-dem-glo-30/v1"
    assert collection["gee:units"] == {"elevation": "m"}
    assert collection["summaries"]["eo:bands"] == [{"name": "elevation"}]
    assert normalized["properties"]["gee:processing"]["elevation"] == {
        "source_asset": "data", "scale": 0.25, "offset": 100.0, "resampling": "none"
    }
    assert normalized["properties"]["gee:requested_bbox"] == requested
    assert normalized["bbox"] != requested
    assert normalized["bbox"] == [0.0, 0.0, 3.0, 3.0]
    assert normalized["assets"].keys() == {"elevation"}
    assert normalized["assets"]["elevation"]["eo:bands"] == [{"name": "elevation"}]
    asset = normalized["assets"]["elevation"]
    assert asset["href"] == f"/data/assets/cop-dem-glo-30/{item_id}/elevation.tif"
    assert asset["raster:bands"] == [{
        "data_type": "float32", "nodata": "nan", "scale": 1, "offset": 0, "unit": "m"
    }]
    assert asset["proj:shape"] == [3, 3]
    assert asset["proj:transform"] == [1.0, 0.0, 0.0, 0.0, -1.0, 3.0]
    assert normalized["properties"]["gee:source_metadata_sha256"] == hashlib.sha256(
        json.dumps(item, sort_keys=True, indent=2, allow_nan=False).encode()
    ).hexdigest()

    cog = tmp_path / asset["href"].removeprefix("/data/")
    with rasterio.open(cog) as ds:
        assert ds.count == 1
        assert ds.dtypes == ("float32",)
        assert np.isnan(ds.nodata)
        assert ds.units == ("m",)
        assert ds.tags(ns="IMAGE_STRUCTURE")["LAYOUT"] == "COG"
        actual = ds.read(1, masked=True)
        assert np.ma.getmaskarray(actual).tolist() == [
            [False, True, False], [False, False, False], [False, False, False]
        ]
        assert actual[0, 0] == 101.0
        assert actual[0, 2] == 101.5
        assert actual[1, 0] == 0.0
        assert actual[1, 2] == -2399.75  # A valid source value of -9999 stays data.
        assert actual[2, 0] == 103.0


def test_provider_interval_and_missing_source_version_are_preserved(tmp_path, captured_ingest):
    registered, _ = captured_ingest
    source = write_source(tmp_path / "provider.tif")
    item = source_item(source, bands=item_band())
    item["properties"] = {"start_datetime": "2021-04-22T00:00:00+00:00", "end_datetime": "2021-04-23T00:00:00Z"}

    ingest.optical_item(item, "cop-dem-glo-30", [0, 0, 2, 2], budget=Budget())

    properties = registered[0][2]["properties"]
    assert properties["datetime"] == item["properties"]["start_datetime"]
    assert properties["gee:datetime_interpretation"] == "start_datetime"
    assert properties["gee:provider_interval"] == item["properties"]
    assert properties["gee:source_version"] is None


def test_item_datetime_remains_collection_time_when_provider_interval_is_also_supplied(
    tmp_path, captured_ingest
):
    registered, _ = captured_ingest
    source = write_source(tmp_path / "provider.tif")
    item = source_item(source, bands=item_band())
    item["properties"] = {
        "datetime": "2022-06-01T12:30:00+03:00",
        "start_datetime": "2022-05-01T00:00:00Z",
        "end_datetime": "2022-07-01T00:00:00Z",
    }

    ingest.optical_item(item, "cop-dem-glo-30", [0, 2, 2, 4], budget=Budget())

    collection = registered[0][1]
    props = registered[0][2]["properties"]
    assert collection["extent"]["temporal"]["interval"] == [
        ["2022-06-01T12:30:00+03:00", "2022-06-01T12:30:00+03:00"]
    ]
    assert props["datetime"] == "2022-06-01T12:30:00+03:00"
    assert props["gee:provider_interval"] == {
        "start_datetime": "2022-05-01T00:00:00Z", "end_datetime": "2022-07-01T00:00:00Z"
    }


def test_tiff_scale_offset_are_used_when_stac_metadata_is_absent_and_unit_defaults_to_metres(
    tmp_path, captured_ingest
):
    registered, _ = captured_ingest
    source = write_source(tmp_path / "provider.tif", scale=0.5, offset=3)
    item = source_item(source)

    ingest.optical_item(item, "cop-dem-glo-30", [0, 2, 2, 4], budget=Budget())

    normalized = registered[0][2]
    assert normalized["assets"]["elevation"]["raster:bands"][0]["unit"] == "m"
    assert normalized["properties"]["gee:processing"]["elevation"]["scale"] == 0.5
    assert normalized["properties"]["gee:processing"]["elevation"]["offset"] == 3


def test_stac_only_nodata_is_added_to_the_source_mask(tmp_path, captured_ingest):
    registered, _ = captured_ingest
    values = np.array([[1, -32768], [3, 4]], dtype=np.int16)
    source = write_source(tmp_path / "provider.tif", values, nodata=None)
    item = source_item(source, bands=item_band(scale=1, offset=0, nodata=-32768))

    item_id = ingest.optical_item(item, "cop-dem-glo-30", [0, 2, 2, 4], budget=Budget())

    cog_path = tmp_path / "assets" / "cop-dem-glo-30" / item_id / "elevation.tif"
    with rasterio.open(cog_path) as ds:
        actual = ds.read(1, masked=True)
        assert np.ma.getmaskarray(actual).tolist() == [[False, True], [False, False]]
        assert actual[0, 0] == 1
    assert registered[0][2]["assets"]["elevation"]["raster:bands"][0]["nodata"] == "nan"


@pytest.mark.parametrize(
    "mutate,values,kwargs,match",
    [
        (lambda item: item["properties"].clear(), None, {}, "datetime|start_datetime"),
        (lambda item: item["properties"].update(datetime="2021-04-22T00:00:00"), None, {}, "timezone"),
        (lambda item: item["assets"]["data"]["raster:bands"][0].update(unit="ft"), None, {}, "unit"),
        (lambda item: item["assets"]["data"]["raster:bands"][0].update(scale=True), None, {}, "finite number"),
        (lambda item: item["assets"]["data"].pop("raster:bands"), np.ones((2, 4, 4), dtype=np.int16), {}, "single-band"),
        (lambda item: item["assets"]["data"]["raster:bands"][0].update(scale=1), None, {"tiff_scale": 0.5}, "conflicts"),
        (lambda item: item["assets"]["data"]["raster:bands"][0].update(nodata=-32768), None, {"tiff_nodata": -9999}, "NoData"),
    ],
)
def test_rejects_malformed_source_metadata(tmp_path, captured_ingest, mutate, values, kwargs, match):
    source_options = {}
    if kwargs.get("tiff_scale") is not None:
        source_options["scale"] = kwargs["tiff_scale"]
    if kwargs.get("tiff_nodata") is not None:
        source_options["nodata"] = kwargs["tiff_nodata"]
    source = write_source(tmp_path / "provider.tif", values, **source_options)
    item = source_item(source, bands=item_band(scale=0.25))
    mutate(item)

    with pytest.raises(ValueError, match=match):
        ingest.optical_item(item, "cop-dem-glo-30", [0, 0, 2, 2], budget=Budget())


@pytest.mark.parametrize("crs", [None, "LOCAL_CS[\"no epsg\",LOCAL_DATUM[\"unknown\",0],UNIT[\"metre\",1]]"])
def test_rejects_missing_or_unidentified_crs(tmp_path, captured_ingest, crs):
    source = write_source(tmp_path / "provider.tif", crs=crs)
    item = source_item(source, bands=item_band())

    with pytest.raises(ValueError, match="CRS"):
        ingest.optical_item(item, "cop-dem-glo-30", [0, 0, 2, 2], budget=Budget())


def test_rejects_nonfinite_and_float32_overflow_in_valid_source_pixels(tmp_path, captured_ingest):
    for name, values in (
        ("nonfinite", np.array([[np.inf, 1.0], [2.0, 3.0]], dtype=np.float64)),
        ("overflow", np.array([[1e100, 1.0], [2.0, 3.0]], dtype=np.float64)),
    ):
        source = write_source(tmp_path / f"{name}.tif", values, nodata=None, dtype="float64")
        item = source_item(source, bands=item_band(data_type="float64"))
        match = "nonfinite" if name == "nonfinite" else "Float32"
        with pytest.raises(ValueError, match=match):
            ingest.optical_item(item, "cop-dem-glo-30", [0, 2, 2, 4], budget=Budget())


def test_rejects_complex_source_rasters(tmp_path, captured_ingest):
    values = np.array([[1 + 2j, 3 + 0j], [4 + 0j, 5 + 0j]], dtype=np.complex64)
    source = write_source(tmp_path / "complex.tif", values, nodata=None, dtype="complex64")
    item = source_item(source, bands=item_band(data_type="complex64"))

    with pytest.raises(ValueError, match="real numeric"):
        ingest.optical_item(item, "cop-dem-glo-30", [0, 2, 2, 4], budget=Budget())


def test_rejects_64_bit_integer_source_before_lossy_float64_conversion(tmp_path, captured_ingest):
    values = np.array([[2**53 + 1, 1], [2, 3]], dtype=np.int64)
    source = write_source(tmp_path / "int64.tif", values, nodata=None, dtype="int64")
    item = source_item(source, bands=item_band(scale=1, offset=-(2**53), data_type="int64"))

    with pytest.raises(ValueError, match="at most 32-bit"):
        ingest.optical_item(item, "cop-dem-glo-30", [0, 2, 2, 4], budget=Budget())


def test_four_million_pixel_bound_is_applied_to_source_window(tmp_path, captured_ingest, monkeypatch):
    source = write_source(tmp_path / "provider.tif")
    item = source_item(source, bands=item_band())
    monkeypatch.setattr("gee.dem_ingest_helpers.MAX_CELLS", 4)

    with pytest.raises(ValueError, match="4 million"):
        ingest.optical_item(item, "cop-dem-glo-30", [0.2, 0.2, 2.2, 2.2], budget=Budget())


def test_duplicate_and_source_version_changes_use_dem_fingerprint(tmp_path, captured_ingest):
    registered, _ = captured_ingest
    source = write_source(tmp_path / "provider.tif")
    first = source_item(source, bands=item_band(), item_id="same-source")
    first["properties"]["version"] = "v1"
    first_id = ingest.optical_item(first, "cop-dem-glo-30", [0, 0, 2, 2], budget=Budget())
    second = json.loads(json.dumps(first))
    second["properties"]["version"] = "v2"
    second_id = ingest.optical_item(second, "cop-dem-glo-30", [0, 0, 2, 2], budget=Budget())
    repeated_id = ingest.optical_item(second, "cop-dem-glo-30", [0, 0, 2, 2], budget=Budget())

    assert first_id != second_id == repeated_id
    assert len(registered) == 2
    assert registered[0][2]["properties"]["gee:source_version"] == "v1"
    assert registered[1][2]["properties"]["gee:source_version"] == "v2"
    assert (tmp_path / "assets" / "cop-dem-glo-30" / first_id / "elevation.tif").exists()
    assert (tmp_path / "assets" / "cop-dem-glo-30" / second_id / "elevation.tif").exists()


def test_item_id_keeps_asset_and_catalog_components_within_filesystem_limit(tmp_path, captured_ingest):
    source = write_source(tmp_path / "provider.tif")
    item = source_item(source, bands=item_band(), item_id="i" * 233)

    item_id = ingest.optical_item(item, "cop-dem-glo-30", [0, 2, 2, 4], budget=Budget())

    assert len(item_id) == 250
    assert len(f"{item_id}.json") == 255


def test_source_id_longer_than_catalog_filename_budget_is_rejected(tmp_path, captured_ingest):
    source = write_source(tmp_path / "provider.tif")
    item = source_item(source, bands=item_band(), item_id="i" * 234)

    with pytest.raises(ValueError, match="233"):
        ingest.optical_item(item, "cop-dem-glo-30", [0, 2, 2, 4], budget=Budget())


def test_failed_registration_removes_only_new_partial_outputs(tmp_path, monkeypatch):
    source = write_source(tmp_path / "provider.tif")
    item = source_item(source, bands=item_band())
    calls = 0

    def query(sql, params, one=False):
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(dem_ingest, "ROOT", tmp_path)
    monkeypatch.setattr(dem_ingest.db, "query", query)
    monkeypatch.setattr(dem_ingest, "register", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("publish failed")))

    with pytest.raises(RuntimeError, match="publish failed"):
        ingest.optical_item(item, "cop-dem-glo-30", [0, 0, 2, 2], budget=Budget())

    assert calls == 2
    assert not list((tmp_path / "assets" / "cop-dem-glo-30").glob("*/elevation.tif"))
    assert not list((tmp_path / "catalog" / "cop-dem-glo-30").glob("*.json"))


def test_unknown_publish_readback_preserves_assets(tmp_path, monkeypatch):
    source = write_source(tmp_path / "provider.tif")
    item = source_item(source, bands=item_band())
    calls = 0

    def query(sql, params, one=False):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        raise RuntimeError("database readback unavailable")

    monkeypatch.setattr(dem_ingest, "ROOT", tmp_path)
    monkeypatch.setattr(dem_ingest.db, "query", query)
    monkeypatch.setattr(dem_ingest, "register", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("publish outcome unknown")))

    with pytest.raises(RuntimeError, match="publish outcome unknown"):
        ingest.optical_item(item, "cop-dem-glo-30", [0, 0, 2, 2], budget=Budget())

    assert calls == 2
    outputs = list((tmp_path / "assets" / "cop-dem-glo-30").glob("*/elevation.tif"))
    assert len(outputs) == 1
