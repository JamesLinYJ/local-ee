"""Bounded literal sampling/training specifications, never executable graph data."""
from __future__ import annotations

import json
import math
import re

from .table_values import columns


MAX_ROWS = 1000
MAX_BANDS = 64
MAX_COLUMNS = 256
MAX_CELLS = 50_000
MAX_BYTES = 1_000_000
MAX_COORDINATES = 10_000
SAMPLE_KEYS = {"version", "regions", "bands", "properties", "geometries", "grid"}
TRAIN_KEYS = {"version", "metric", "class_property", "schema"}
KINDS = {"Point", "MultiPoint", "Polygon", "MultiPolygon"}


def _flat(name):
    return type(name) is str and bool(name) and "." not in name and len(name) <= 256


def _names(value, minimum, maximum, label):
    if (type(value) is not list or not minimum <= len(value) <= maximum
            or any(not _flat(x) for x in value) or len(set(value)) != len(value)):
        raise ValueError(f"{label} requires {minimum}..{maximum} unique flat names, each <=256 characters")
    return value


def _grid(value):
    if type(value) is not dict or set(value) != {"scale", "crs"}:
        raise ValueError("Sampling grid requires exactly scale and crs")
    scale, crs = value["scale"], value["crs"]
    if scale is not None:
        try:
            valid = type(scale) in (int, float) and math.isfinite(scale) and scale > 0
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("Sampling scale must be positive finite meters")
    if crs is not None:
        if type(crs) is not str or not re.fullmatch(r"EPSG:[1-9][0-9]{0,5}", crs):
            raise ValueError("Sampling projection must be a supported EPSG code")
        if scale is None:
            raise ValueError("Sampling projection requires an explicit meter scale")
        if crs == "EPSG:4326":
            raise ValueError("Sampling meter scale in geographic EPSG:4326 is unsupported")


def _coordinate_count(coordinates):
    if type(coordinates) is list:
        if len(coordinates) == 2 and all(type(x) in (int, float) for x in coordinates):
            return 1
        return sum(_coordinate_count(x) for x in coordinates)
    return 0


def _validate_regions(regions):
    if type(regions) is not dict or set(regions) != {"type", "features"}:
        raise ValueError("Sampling regions must be a literal FeatureCollection")
    columns(regions)  # finite JSON, geometry/CRS/bbox, topology, bytes and row budgets
    count = 0
    for feature in regions["features"]:
        if set(feature) - {"type", "geometry", "properties", "id"}:
            raise ValueError("Unsupported sampling feature field")
        geometry = feature["geometry"]
        if geometry is None or geometry.get("type") not in KINDS:
            raise ValueError("Sampling requires nonempty Point/MultiPoint/Polygon/MultiPolygon regions")
        from shapely.geometry import shape

        if shape(geometry).is_empty:
            raise ValueError("Sampling regions must be nonempty")
        count += _coordinate_count(geometry.get("coordinates"))
        if count > MAX_COORDINATES:
            raise ValueError("Sampling exceeds 10000 coordinate positions")


def encode_spec(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Sampling/training specification exceeds 1 MB")
    return text


def _parse(text):
    if type(text) is not str or len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Expected a bounded sampling/training JSON string")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate specification key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Specification values must be finite JSON")

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        if encode_spec(value) != text:
            raise ValueError("Specification must use canonical JSON")
    except (RecursionError, OverflowError) as exc:
        raise ValueError("Specification exceeds bounded JSON limits") from exc
    return value


def sampling_columns(spec):
    return ["system:index", *spec["properties"], *spec["bands"], ".geo"]


def decode_sampling_spec(text):
    spec = _parse(text)
    if type(spec) is dict and type(spec.get("version")) is int and spec["version"] == 2:
        from .image_sampling_spec import validate_image_sample_spec

        return validate_image_sample_spec(spec)
    return _check_regions_spec(spec)


def _check_regions_spec(spec):
    """Shared v1 shape validation; callers must already enforce JSON bounds."""
    if type(spec) is not dict or set(spec) != SAMPLE_KEYS or type(spec["version"]) is not int or spec["version"] != 1:
        raise ValueError("Unsupported sampling specification fields or version")
    bands = _names(spec["bands"], 1, MAX_BANDS, "Sampling bands")
    copied = _names(spec["properties"], 0, MAX_COLUMNS - len(bands) - 2, "Copied properties")
    if set(copied) & ({"system:index", ".geo"} | set(bands)) or "system:index" in bands:
        raise ValueError("Sampling output columns collide with copied or reserved names")
    if type(spec["geometries"]) is not bool:
        raise ValueError("Sampling geometries must be a boolean")
    _grid(spec["grid"])
    _validate_regions(spec["regions"])
    for feature in spec["regions"]["features"]:
        if set(feature["properties"]) != set(copied):
            raise ValueError("Sampling features must contain exactly their declared copied properties")
    return spec


def prepare_sampling_spec(collection, bands, properties=None, geometries=False, grid=None):
    columns(collection)
    features = collection["features"]
    _names(bands, 1, MAX_BANDS, "Sampling bands")
    if properties is None:
        properties = list(dict.fromkeys(
            key for feature in features for key in feature["properties"] if not key.startswith("system:")
        ))
    _names(properties, 0, MAX_COLUMNS - len(bands) - 2, "Copied properties")
    regions = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": feature["geometry"],
         "properties": {name: feature["properties"].get(name) for name in properties},
         **({"id": feature["id"]} if "id" in feature else {})}
        for feature in features
    ]}
    spec = {"version": 1, "regions": regions, "bands": bands.copy(),
            "properties": properties.copy(), "geometries": geometries,
            "grid": {"scale": None, "crs": None} if grid is None else grid}
    text = encode_spec(spec)
    decode_sampling_spec(text)
    return text


def decode_training_spec(text):
    spec = _parse(text)
    if type(spec) is not dict or set(spec) != TRAIN_KEYS or type(spec["version"]) is not int or spec["version"] != 1:
        raise ValueError("Unsupported sampled training specification fields or version")
    if type(spec["metric"]) is not str or spec["metric"] not in {"euclidean", "manhattan", "cosine"}:
        raise ValueError("Unsupported sampled minimum-distance metric")
    _names(spec["schema"], 1, 8, "Training schema")
    if not _flat(spec["class_property"]):
        raise ValueError("Training class_property must be a bounded flat name")
    return spec
