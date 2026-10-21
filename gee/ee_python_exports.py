"""Local export configuration for the pinned Earth Engine Python SDK."""

from __future__ import annotations

import math
from typing import Any


_MAX_EXACT_INTEGER = 2**53 - 1


def _raise(ee: Any, message: str) -> None:
    raise ee.ee_exception.EEException(message)


def _max_pixels(ee: Any, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _raise(ee, "Invalid local maxPixels value")
    if isinstance(value, int):
        if 1 <= value <= _MAX_EXACT_INTEGER:
            return value
        _raise(ee, "Invalid local maxPixels value")
    if not math.isfinite(value) or not 1 <= value <= _MAX_EXACT_INTEGER:
        _raise(ee, "Invalid local maxPixels value")
    if not value.is_integer():
        _raise(ee, "Invalid local maxPixels value")
    return int(value)


def prepare_local_image_export(
    ee: Any, image: Any, config: dict[str, Any], destination: str
) -> dict[str, Any]:
    """Keep supported grid options explicit instead of generating cloud wrappers."""
    batch = ee.batch
    if destination != batch.Task.ExportDestination.DRIVE:
        _raise(ee, "Local EE supports only Export.image.toDrive")
    if "fileFormat" not in config:
        config["fileFormat"] = "GeoTIFF"
    batch._canonicalize_parameters(config, destination)
    allowed = {
        "description",
        "fileFormat",
        "driveFolder",
        "driveFileNamePrefix",
        "region",
        "scale",
        "crs",
        "maxPixels",
    }
    unsupported = set(config) - allowed
    if unsupported:
        _raise(
            ee,
            "Unsupported local image export fields: "
            + ", ".join(sorted(unsupported)),
        )
    if config.get("fileFormat") != "GeoTIFF":
        _raise(ee, "Local image exports support GeoTIFF only")
    if "maxPixels" in config:
        config["maxPixels"] = _max_pixels(ee, config["maxPixels"])
    result = {"expression": image}
    for source, target in (
        ("description", "description"),
        ("driveFolder", "folder"),
        ("driveFileNamePrefix", "fileNamePrefix"),
        ("fileFormat", "fileFormat"),
        ("region", "region"),
        ("scale", "scale"),
        ("crs", "crs"),
        ("maxPixels", "maxPixels"),
    ):
        if source in config:
            result[target] = config[source]
    return result


def local_options(
    ee: Any, task_type: str, params: dict[str, Any], encode: Any
) -> dict[str, Any]:
    """Validate Drive-only local export fields and preserve their meanings."""
    if not isinstance(params, dict):
        _raise(ee, "Local EE export configuration must be an object")
    if task_type == "export_image" and "fileExportOptions" in params:
        _raise(ee, "Local EE supports only Export.image.toDrive")
    allowed = {"expression", "description", "workloadTag"}
    if task_type == "export_image":
        allowed |= {
            "fileFormat",
            "folder",
            "fileNamePrefix",
            "region",
            "scale",
            "crs",
            "maxPixels",
        }
    elif task_type == "export_table":
        allowed |= {"fileExportOptions", "selectors"}
    unsupported = set(params) - allowed
    if unsupported:
        _raise(
            ee,
            "Unsupported local EE export fields: " + ", ".join(sorted(unsupported)),
        )
    if params.get("workloadTag") not in (None, ""):
        _raise(ee, "Local EE does not support workload tags")
    expression = params.get("expression")
    if expression is None:
        _raise(ee, "Local EE export is missing its expression")

    options: dict[str, Any] = {"description": params.get("description")}
    if task_type == "export_image":
        if params.get("fileFormat", "GeoTIFF") != "GeoTIFF":
            _raise(ee, "Local image exports support GeoTIFF only")
        options.update(
            folder=params.get("folder"),
            fileNamePrefix=params.get("fileNamePrefix"),
            fileFormat="GeoTIFF",
        )
        if params.get("region") is not None:
            try:
                options["region"] = encode(params["region"])
            except Exception as error:
                _raise(ee, f"Invalid local image export region: {error}")
        for key in ("scale", "crs"):
            if params.get(key) is not None:
                options[key] = params[key]
        if "maxPixels" in params:
            options["maxPixels"] = _max_pixels(ee, params["maxPixels"])
    else:
        file_options = params.get("fileExportOptions")
        if not isinstance(file_options, dict):
            _raise(ee, "Local exports require file options")
        if "cloudStorageDestination" in file_options:
            _raise(ee, "Local EE supports only Export.*.toDrive destinations")
        unsupported = set(file_options) - {"fileFormat", "driveDestination"}
        if unsupported:
            _raise(
                ee,
                "Unsupported local EE file options: "
                + ", ".join(sorted(unsupported)),
            )
        if "driveDestination" not in file_options:
            _raise(ee, "Local exports support only Export.*.toDrive destinations")
        drive = file_options["driveDestination"]
        if not isinstance(drive, dict) or set(drive) - {"folder", "filenamePrefix"}:
            _raise(ee, "Unsupported local Drive destination options")
        if file_options.get("fileFormat") != "CSV":
            _raise(ee, "Local table exports support CSV only")
        options.update(
            folder=drive.get("folder"),
            fileNamePrefix=drive.get("filenamePrefix"),
            fileFormat="CSV",
        )
        if "selectors" in params:
            options["selectors"] = params["selectors"]
    options = {key: value for key, value in options.items() if value is not None}
    return {"expression": expression, "options": options}
