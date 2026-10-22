"""Independent raw-grid and typed random-column references for wave29."""
from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path

from shapely.geometry import Point, shape


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "tests/fixtures/ee-random-split-v1.json"
HASH_PREFIX = b"local-ee/randomColumn/sha256-rowkeys-v1\0"


def load_fixtures():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    source = json.loads((CONFIG_PATH.parent / config["source_fixture"]).read_text(encoding="utf-8"))
    return config, source


def sample_rows(source, mode, config=None):
    """Enumerate fixture cell centers directly, independent of compiler code."""
    if mode not in {"image_sample_v2", "sample_regions_v1"}:
        raise ValueError("Unknown sample mode")
    rows, columns = source["grid"]["shape_rows_columns"]
    west, south, east, north = source["extent"]
    footprint = shape(source["items"][0]["geometry"])
    pixel_values = source["items"][0]["pixel_values"]
    allowed_cells = (set(config["sample_regions_cells"])
                     if mode == "sample_regions_v1" and config is not None else None)
    result = []
    for row in range(rows):
        for column in range(columns):
            x = west + (column + 0.5) * (east - west) / columns
            y = north - (row + 0.5) * (north - south) / rows
            if not footprint.covers(Point(x, y)):
                continue
            index = row * columns + column
            properties = {band: pixel_values[band][index] for band in source["sample_bands"]}
            cell_id = f"f0_r{row}_c{column}"
            if allowed_cells is not None and cell_id not in allowed_cells:
                continue
            if mode == "sample_regions_v1":
                if any(value is None for value in properties.values()):
                    continue
                properties["cell_id"] = cell_id
            result.append({
                "type": "Feature", "id": cell_id,
                "geometry": {"type": "Point", "coordinates": [x, y]},
                "properties": properties,
            })
    return result


def _row_value(feature, key):
    properties = feature["properties"]
    if key == "system:index":
        value = properties.get(key, feature.get("id"))
    else:
        value = properties.get(key)
    if value is None or type(value) in (list, dict):
        raise ValueError(f"Missing or unsupported randomColumn row key: {key}")
    return value


def _typed_frame(value):
    if isinstance(value, str):
        tag, payload = b"s", value.encode("utf-8", "strict")
    elif type(value) is bool:
        tag, payload = b"b", b"\1" if value else b"\0"
    elif type(value) in (int, float):
        number = float(value)
        if not math.isfinite(number) or abs(number) > 2**53:
            raise ValueError("Random row key must be a finite exact binary64 number")
        if number == 0.0:
            number = 0.0
        tag, payload = b"n", struct.pack(">d", number)
    else:
        raise ValueError("Random row keys support strings, booleans, and numbers")
    return tag + struct.pack(">I", len(payload)) + payload


def independent_draw(feature, seed, row_keys=None, distribution="uniform"):
    """Apply the contract's binary wire independently of production helpers."""
    keys = ["system:index"] if row_keys is None else list(row_keys)
    wire = HASH_PREFIX + struct.pack(">qI", seed, len(keys))
    wire += b"".join(_typed_frame(_row_value(feature, key)) for key in keys)
    digest = hashlib.sha256(wire).digest()
    first = int.from_bytes(digest[:8], "big")
    if distribution == "uniform":
        return (first >> 11) * 2**-53
    if distribution != "normal":
        raise ValueError("Unknown distribution")
    second = int.from_bytes(digest[8:16], "big")
    u1 = ((first >> 12) + 0.5) * 2**-52
    u2 = (second >> 11) * 2**-53
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def reference_split(config, source, mode):
    """Hash rows before notNull, then form exhaustive half-open split sides."""
    row_keys = ["cell_id"] if mode == "sample_regions_v1" else None
    candidates = sample_rows(source, mode, config)
    complete, training, validation = [], [], []
    for feature in candidates:
        draw = independent_draw(feature, config["seed"], row_keys, config["distribution"])
        if any(feature["properties"].get(key) is None for key in [
            config["class_property"], *config["input_properties"]
        ]):
            continue
        copied = {**feature, "properties": {**feature["properties"], config["random_column"]: draw}}
        complete.append(copied)
        target = training if draw < config["threshold"] else validation
        target.append(copied)
    return candidates, complete, training, validation


def class_counts(features, name):
    counts = {}
    for feature in features:
        value = feature["properties"][name]
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def local_metadata(source):
    catalog = [{
        "id": source["collection_id"],
        "cube:dimensions": {"bands": {"values": source["catalog_bands"]}},
    }]
    items = {source["collection_id"]: [{
        key: item[key] for key in ("id", "bbox", "geometry", "properties")
    } for item in source["items"]]}
    return catalog, items
