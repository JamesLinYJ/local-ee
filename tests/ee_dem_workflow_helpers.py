"""Independent terrain readback checks for the synthetic DEM workflow."""
from __future__ import annotations

import math
import struct
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine

from dem_workflow_fixture import source_cases
from ee_terrain_kernel_helpers import reference as terrain_reference
from gee.dem_contract import COLLECTION_ID
from gee.ee_translate import compile_expression
from gee.terrain_spec import decode_terrain_spec


PROBE_SHA256 = "ff261c228f08422f8702fba63ae5f98f6be2c4c51c70d8638dae45c84293ebdb"


def reference_case(values: np.ndarray, valid: np.ndarray, transform: Affine,
                   crs: str, operation: str, azimuth: float = 270.0,
                   elevation: float = 45.0) -> list[float | None]:
    """Call the existing independent pyproj/Decimal WGS84 terrain oracle."""
    height, width = values.shape
    return terrain_reference({
        "name": f"dem-{crs}-{operation}", "crs": crs,
        "xmin": transform.c, "ymax": transform.f,
        "cell_width": transform.a, "cell_height": abs(transform.e),
        "width": width, "height": height,
        "tile_cols": width, "tile_rows": height,
        "existing_tiles": [[0, 0]],
        "operation": operation, "azimuth": azimuth, "elevation": elevation,
        "values": [float(values[row, col]) if valid[row, col] else None
                   for row in range(height) for col in range(width)],
    })


def local_asset_path(root: Path, href: str) -> Path:
    prefix = "/data/"
    if not isinstance(href, str) or not href.startswith(prefix):
        raise ValueError(f"unexpected normalized DEM href: {href!r}")
    return root / href[len(prefix):]


def compile_products(ee, metadata: dict, item: dict):
    """Compile official Terrain.products and bind its exact selected local item."""
    value = ee.Terrain.products(ee.ImageCollection(COLLECTION_ID).first())
    expression = ee.serializer.encode(value, for_cloud_api=False)
    compiled = compile_expression(expression, [metadata], {COLLECTION_ID: [item]})
    graph = compiled["process_graph"]
    selected = [node for node in graph.values() if node["process_id"] == "load_collection"]
    terrain = [node for node in graph.values() if node["process_id"] == "local_ee_terrain"]
    assert len(selected) == 1
    assert selected[0]["arguments"]["id"] == COLLECTION_ID
    assert selected[0]["arguments"]["_gee_item_ids"] == [item["id"]]
    assert compiled["source_item_ids"] == [item["id"]]
    specs = {
        decode_terrain_spec(node["arguments"]["spec"])["operation"]:
        node["arguments"]["spec"] for node in terrain
    }
    assert set(specs) == {"slope", "aspect", "hillshade"}
    assert compiled["bands"] == ["elevation", "slope", "aspect", "hillshade"]
    return compiled, specs


def assert_normalized(case: dict, metadata: dict, item: dict, local_path: Path):
    """Check the captured catalogue record and read actual normalized COG pixels."""
    expected_epsg = 32610 if case["crs"] == "EPSG:32610" else 4326
    assert metadata["id"] == COLLECTION_ID
    assert metadata["gee:dem_contract"] == "cop-dem-glo-30/v1"
    assert metadata["cube:dimensions"]["bands"]["values"] == ["elevation"]
    assert metadata["gee:units"] == {"elevation": "m"}
    assert item["properties"]["gee:source_id"] == case["source_id"]
    assert item["properties"]["gee:vertical_datum"] == "EGM2008"
    assert item["properties"]["proj:epsg"] == expected_epsg
    asset = item["assets"]["elevation"]
    assert asset["raster:bands"] == [{
        "data_type": "float32", "nodata": "nan", "scale": 1, "offset": 0, "unit": "m",
    }]
    assert asset["proj:shape"] == [case["height"], case["width"]]
    assert asset["proj:transform"] == list(case["transform"])[:6]
    with rasterio.open(local_path) as dataset:
        assert dataset.driver == "GTiff" and dataset.dtypes == ("float32",)
        assert np.isnan(dataset.nodata) and dataset.crs.to_string() == case["crs"]
        assert dataset.transform == case["transform"]
        assert dataset.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") == "COG"
        normalized = dataset.read(1, masked=True)
        expected = (case["raw"].astype(np.float64) * case["scale"]
                    + case["offset"]).astype(np.float32)
        assert np.array_equal(np.ma.getmaskarray(normalized), ~case["valid"])
        assert np.array_equal(normalized.data[case["valid"]], expected[case["valid"]])
        assert np.isnan(normalized.data[~case["valid"]]).all()
        assert np.isnan(dataset.read(1)[7, 5])
        assert not np.ma.getmaskarray(normalized)[3, 14]
        assert normalized.data[3, 14] == -9999.0
    return normalized.data.copy(), case["valid"].copy()


def assert_geotiff_reference(output: Path, values: np.ndarray, valid: np.ndarray,
                             case: dict, spec_text: str, native: dict) -> dict:
    """Read GeoTrellis output independently with Rasterio and the Decimal oracle."""
    spec = decode_terrain_spec(spec_text)
    azimuth = struct.unpack(">d", bytes.fromhex(spec["azimuth"]))[0]
    elevation = struct.unpack(">d", bytes.fromhex(spec["elevation"]))[0]
    expected = reference_case(values, valid, case["transform"], case["crs"],
                              spec["operation"], azimuth, elevation)
    max_value_error = 0.0
    max_angle_error = 0.0
    valid_count = 0
    expected_affine = np.asarray(case["transform"][:6], dtype=np.float64)
    with rasterio.open(output) as dataset:
        actual = dataset.read(1, masked=True)
        assert dataset.dtypes == ("float64",)
        assert dataset.crs.to_string() == case["crs"]
        actual_affine = np.asarray(dataset.transform[:6], dtype=np.float64)
        affine_delta = np.abs(actual_affine - expected_affine)
        cell_x, cell_y = abs(expected_affine[0]), abs(expected_affine[4])
        origin_x_scale = max(abs(expected_affine[2]), abs(actual_affine[2]), cell_x)
        origin_y_scale = max(abs(expected_affine[5]), abs(actual_affine[5]), cell_y)
        affine_tolerance = np.asarray([
            cell_x * 1e-10,
            32 * math.ulp(cell_x),
            32 * math.ulp(origin_x_scale),
            32 * math.ulp(cell_y),
            cell_y * 1e-10,
            32 * math.ulp(origin_y_scale),
        ])
        assert np.all(affine_delta <= affine_tolerance), (
            affine_delta.tolist(), affine_tolerance.tolist()
        )
        assert dataset.width == case["width"] and dataset.height == case["height"]
        mask = np.ma.getmaskarray(actual)
        for index, wanted in enumerate(expected):
            row, col = divmod(index, case["width"])
            if wanted is None:
                assert mask[row, col], f"{spec['operation']}[{row},{col}] must be NoData"
            else:
                assert not mask[row, col], f"{spec['operation']}[{row},{col}] unexpectedly masked"
                value = float(actual.data[row, col])
                valid_count += 1
                if spec["operation"] == "hillshade":
                    assert value == wanted
                    error = abs(value - wanted)
                elif spec["operation"] == "aspect":
                    delta = abs(value - wanted)
                    error = min(delta, 360.0 - delta)
                    assert error <= 2.0e-7
                    max_angle_error = max(max_angle_error, error)
                else:
                    error = abs(value - wanted)
                    assert error <= 2.0e-7 + abs(wanted) * 2.0e-8
                    max_angle_error = max(max_angle_error, error)
                max_value_error = max(max_value_error, error)
        valid_count = int((~mask).sum())
        nodata_count = int(mask.sum())
        assert native["output_nodata"] == nodata_count
        assert native["output_valid"] == valid_count
        if spec["operation"] == "hillshade" and case["name"] == "projected-utm":
            assert native["output_zero"] > 0 and native["output_255"] > 0
        return {
            "comparison_count": len(expected),
            "valid_value_comparisons": valid_count,
            "expected_nodata_count": sum(value is None for value in expected),
            "actual_nodata_count": nodata_count,
            "affine_delta": affine_delta.tolist(),
            "affine_tolerance": affine_tolerance.tolist(),
            "affine_comparison_policy": (
                "pixel size <=1e-10 relative cell size; origin <=32 coordinate ULP; "
                "zero/shear terms <=32 ULP at cell-size scale"
            ),
            "max_angle_error_degrees": (
                max_angle_error if spec["operation"] in {"slope", "aspect"} else None
            ),
            "aspect_error_wrap": "min(abs(actual-expected), 360-abs(actual-expected))",
            "max_value_error": max_value_error,
                "max_affine_error": float(np.max(affine_delta)),
                "max_affine_error_tolerance": float(np.max(affine_tolerance)),
            "hillshade_exact": spec["operation"] == "hillshade",
            "hillshade_policy": (
                "exact integer equality after floor(clamp(Lambert illumination)*255+0.5)"
                if spec["operation"] == "hillshade" else None
            ),
            "valid_cells": valid_count,
            "nodata_cells": nodata_count,
            "minimum": float(np.min(actual.data[~mask])),
            "maximum": float(np.max(actual.data[~mask])),
        }
