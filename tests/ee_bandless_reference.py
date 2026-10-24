"""Independent finite-grid values and metadata for Wave68."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-bandless-wave68-v1.json"


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def expected_pixels(fixture):
    first, second = fixture["scenes"]
    result = {}
    for band in fixture["source_bands"]:
        left = first["values"][band]
        right = second["values"][band]
        result[band] = list(left)
        result[f"{band}_1"] = list(right)
        result[f"{band}_total"] = [
            None if a is None or b is None else a + b
            for a, b in zip(left, right)
        ]
    return result


def local_metadata(fixture):
    grid = fixture["grid"]
    xmin, ymin, xmax, ymax = grid["bbox"]
    transform = list(grid["transform"])
    asset = {"proj:shape": [grid["rows"], grid["columns"]],
             "proj:epsg": 4326, "proj:transform": transform}
    collection = {"id": fixture["source_id"], "cube:dimensions": {
        "bands": {"values": list(fixture["source_bands"])},
    }}
    items, arrays, geometries = [], {}, {}
    for scene in fixture["scenes"]:
        item = {
            "id": scene["id"], "bbox": [xmin, ymin, xmax, ymax],
            "geometry": fixture["region"], "properties": dict(scene["properties"]),
            "assets": {band: dict(asset) for band in fixture["source_bands"]},
        }
        items.append(item)
        arrays[scene["id"]] = {
            band: np.asarray([np.nan if value is None else value
                              for value in scene["values"][band]], dtype=np.float64)
            for band in fixture["source_bands"]
        }
        geometries[scene["id"]] = fixture["region"]
    centers = np.asarray([
        [xmin + col + 0.5, ymax - row - 0.5]
        for row in range(grid["rows"])
        for col in range(grid["columns"])
    ])
    return ([collection], {fixture["source_id"]: items}, arrays, centers, geometries)
