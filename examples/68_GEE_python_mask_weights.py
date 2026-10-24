"""Read fractional image masks with the official SDK, without Google requests."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def build_workflow(ee, image):
    source = ee.Image(image).select(["red", "nir"]).toDouble()
    weighted = source.updateMask(ee.Image.constant([0.25, 0.75]))
    return {
        "weights_by_band": weighted.mask(),
        "weights_after_update": weighted.updateMask(0.5).mask(),
        "selected_weight": weighted.select("nir").mask().rename("nir_weight"),
        "source_validity": source.mask(),
    }


def synthetic_catalog():
    collection = {"id": "sentinel-2-l2a", "cube:dimensions": {
        "bands": {"values": ["red", "nir"]},
    }}
    item = {
        "id": "mask-demo", "bbox": [0, 0, 2, 2],
        "geometry": {"type": "Polygon", "coordinates": [
            [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
        ]},
        "properties": {
            "system:index": "mask-demo", "system:time_start": 1000,
            "proj:code": "EPSG:4326", "proj:transform": [0.01, 0, 0, 0, -0.01, 2],
        },
    }
    return [collection], {collection["id"]: [item]}


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from gee.graph import validate
    from scripts.ee_python_api.offline import OfflineGuard

    catalog, items = synthetic_catalog()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=root / "vendor/earthengine-js/algorithms.json",
        )
        image = ee.Image(ee.ImageCollection("sentinel-2-l2a").first())
        results = {}
        for name, value in build_workflow(ee, image).items():
            compiled = compile_expression(
                ee.serializer.encode(value, for_cloud_api=False), catalog, items,
            )
            validate(compiled["process_graph"])
            results[name] = {"bands": compiled["bands"], "nodes": len(compiled["process_graph"])}
    print(json.dumps({"scope": "offline SDK and compiler only", "results": results,
                      "network_attempts": guard.evidence()["attempt_count"]}, indent=2))


if __name__ == "__main__":
    main()
