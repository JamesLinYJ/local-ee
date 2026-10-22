"""Trusted bridge for bounded EE sampleRegions and runtime classifier training."""
from __future__ import annotations

import json
import math
from typing import Any

from .ee_sampling_result import (
    PendingSampledTable,
    SampledFeatureTable,
)
from .ee_sample_training import local_ee_train_minimum_distance


MAX_SAMPLE_ROWS = 1_000
MAX_SAMPLE_JSON_BYTES = 1_000_000
MAX_NATIVE_INTEGER = 2**53
SCALE_RELATIVE_TOLERANCE = 1e-9


class _NativeJsonError(ValueError):
    """A response error that should keep its useful bounded-parser message."""


def _duplicate_checked_object(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            raise _NativeJsonError("Native sample response contains duplicate JSON keys")
        value[key] = child
    return value


def _reject_json_constant(value):
    raise _NativeJsonError(f"Native sample response contains invalid number {value}")


def _native_integer(text: str) -> int:
    """Bound integer token conversion and preserve Float64-exact native values."""
    digits = text[1:] if text.startswith("-") else text
    if len(digits) > 16:
        raise _NativeJsonError("Native sample integer exceeds the exact Float64 domain")
    value = int(text)
    if abs(value) > MAX_NATIVE_INTEGER:
        raise _NativeJsonError("Native sample integer exceeds the exact Float64 domain")
    return value


def _parse_native_rows(value: Any) -> list[Any]:
    """Decode bounded, duplicate-free JSON; shared values code checks rows."""
    if type(value) is not str:
        raise ValueError("Native sampler must return a JSON string")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Native sample response must be valid UTF-8") from exc
    if len(encoded) > MAX_SAMPLE_JSON_BYTES:
        raise ValueError("Native sample response exceeds the 1000000-byte limit")
    try:
        rows = json.loads(
            value,
            object_pairs_hook=_duplicate_checked_object,
            parse_constant=_reject_json_constant,
            parse_int=_native_integer,
        )
    except _NativeJsonError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ValueError("Native sample response is not bounded JSON rows") from exc
    if type(rows) is not list:
        raise ValueError("Native sampler response must be a JSON row array")
    if len(rows) > MAX_SAMPLE_ROWS:
        raise ValueError("Native sample response exceeds 1000 rows")
    return rows


def _sampling_wkts(spec: dict) -> list[str]:
    from shapely.geometry import shape

    result = []
    for feature in spec["regions"]["features"]:
        try:
            geometry = shape(feature["geometry"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Sampling region geometry could not be converted to WKT") from exc
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError("Sampling regions must be valid non-empty geometries")
        result.append(geometry.wkt)
    return result


def _invoke_native_sampler(cube, level, band_names: list[str], spec: dict) -> str:
    """Invoke the single-level Scala SPI with bounded WGS84 regions and options."""
    from openeogeotrellis.utils import get_jvm
    from gee.sampling_spec import encode_spec
    from gee.image_sampling_spec import is_image_sample

    jvm = get_jvm()
    wrapped = jvm.org.openeo.geotrellis.OpenEOProcesses().wrapCube(level.srdd.rdd())
    wrapped.openEOMetadata().setBandNames(band_names)
    registry = jvm.org.openeo.geotrelliscommon.CubeProcessRegistry
    if is_image_sample(spec):
        return registry.invoke(
            wrapped,
            "local_ee_image_sample",
            {
                "regions": _sampling_wkts(spec),
                "options": encode_spec(spec["image_sample"]),
            },
        )
    return registry.invoke(
        wrapped,
        "local_ee_sample_regions",
        {"regions": _sampling_wkts(spec)},
    )


def _require_cube_schema(cube, spec: dict) -> list[str]:
    metadata = cube.metadata
    if not metadata.has_band_dimension():
        raise ValueError("SampleRegions requires an explicitly named raster band dimension")
    band_names = metadata.band_names
    if (type(band_names) not in (list, tuple) or not 1 <= len(band_names) <= 64
            or any(type(name) is not str or not name for name in band_names)
            or len(set(band_names)) != len(band_names)):
        raise ValueError("SampleRegions requires 1..64 unique source band names")
    if list(band_names) != spec["bands"]:
        raise ValueError("SampleRegions bands must match the actual cube band names and order")
    return list(band_names)


def _check_actual_grid(spec: dict, level) -> None:
    from pyproj import CRS

    grid = spec["grid"]
    try:
        actual = CRS.from_user_input(level.layer_metadata.crs)
    except Exception as exc:
        raise ValueError("SampleRegions requires a valid actual raster CRS") from exc
    if grid["crs"] is not None:
        try:
            requested = CRS.from_user_input(grid["crs"])
        except Exception as exc:
            raise ValueError("SampleRegions declared an invalid CRS") from exc
        if not actual.equals(requested):
            raise ValueError("SampleRegions input grid CRS does not match its declared CRS")
    scale = grid["scale"]
    if scale is None:
        return
    if actual.is_geographic:
        raise ValueError("SampleRegions cannot interpret a meter scale on a geographic grid")
    axes = actual.axis_info[:2]
    unit_factors = [getattr(axis, "unit_conversion_factor", None) for axis in axes]
    if (not actual.is_projected or len(unit_factors) != 2
            or any(type(factor) not in (int, float) or not math.isfinite(factor)
                   or not math.isclose(factor, 1.0, rel_tol=0.0, abs_tol=1e-12)
                   for factor in unit_factors)):
        raise ValueError("SampleRegions meter scale requires a projected meter CRS")

    try:
        layout = level.layer_metadata.layout_definition
        extent = layout.extent
        tile_layout = layout.tileLayout
        width = extent.xmax - extent.xmin
        height = extent.ymax - extent.ymin
        cell_columns = tile_layout.layoutCols * tile_layout.tileCols
        cell_rows = tile_layout.layoutRows * tile_layout.tileRows
        if (any(type(value) not in (int, float) or not math.isfinite(value)
                for value in (width, height))
                or width <= 0 or height <= 0
                or any(type(value) is not int or value <= 0 for value in (
                    tile_layout.layoutCols, tile_layout.tileCols,
                    tile_layout.layoutRows, tile_layout.tileRows,
                ))):
            raise ValueError
        cell_width = width / cell_columns
        cell_height = height / cell_rows
        if (not math.isfinite(cell_width) or not math.isfinite(cell_height)
                or cell_width <= 0 or cell_height <= 0):
            raise ValueError
    except (AttributeError, TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
        raise ValueError("SampleRegions requires actual raster layout metadata to validate meter scale") from exc
    if (not math.isclose(cell_width, scale, rel_tol=SCALE_RELATIVE_TOLERANCE, abs_tol=0.0)
            or not math.isclose(cell_height, scale, rel_tol=SCALE_RELATIVE_TOLERANCE, abs_tol=0.0)):
        raise ValueError("SampleRegions declared meter scale does not match actual raster cell size")


def _sample_actual(cube, spec: dict) -> SampledFeatureTable:
    import geopyspark as gps
    from gee.sampling_spec import sampling_columns
    from gee.sampling_values import assemble_sample_features

    if cube.metadata.has_temporal_dimension():
        raise ValueError("SampleRegions requires a single spatial image with no time dimension")
    band_names = _require_cube_schema(cube, spec)
    # One max-resolution level is the actual source grid. Lower pyramid levels
    # would duplicate samples and change their training weights.
    level = cube.get_max_level()
    if level.layer_type != gps.LayerType.SPATIAL:
        raise ValueError("SampleRegions requires a spatial raster cube")
    _check_actual_grid(spec, level)
    native_json = _invoke_native_sampler(cube, level, band_names, spec)
    columns = sampling_columns(spec)
    rows = _parse_native_rows(native_json)
    data = assemble_sample_features(spec, rows)
    return SampledFeatureTable(data=data, columns=columns)


def local_ee_sample_regions(args, env):
    """Sample actual native grid cells or return a trace-preserving dry-run schema."""
    from openeo_driver.dry_run import DryRunDataCube
    from .ee_process_adapters import _checked_args, _driver_cube
    from gee.sampling_spec import decode_sampling_spec, sampling_columns

    args = _checked_args(args, "local_ee_sample_regions", {"data", "spec"})
    cube = _driver_cube(args, "local_ee_sample_regions")
    text = args["spec"]
    if type(text) is not str:
        raise ValueError("local_ee_sample_regions spec must be canonical JSON text")
    spec = decode_sampling_spec(text)
    columns = sampling_columns(spec)
    _require_cube_schema(cube, spec)
    if isinstance(cube, DryRunDataCube):
        if cube.metadata.has_temporal_dimension():
            raise ValueError("SampleRegions requires a single spatial image with no time dimension")
        return PendingSampledTable(
            columns=tuple(columns),
            sample_spec=text,
            traces=tuple(cube._traces),
            data_tracer=cube._data_tracer,
        )
    return _sample_actual(cube, spec)
