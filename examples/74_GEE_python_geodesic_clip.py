"""Compile the pinned SDK's default geodesic clip without contacting Google.

This example demonstrates supported weight/sample consumers, not a deployed
pixel job. Independent actual-tile and physical-CSV evidence is in Wave70.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys


def build_workflow(ee, fixture):
    parameters = fixture["workflow"]
    image = ee.ImageCollection(parameters["collection_alias"]).first().select(
        parameters["real_band"],
    )
    roi = ee.Geometry.Polygon(parameters["roi"]["coordinates"])
    scan = ee.Geometry.Rectangle([100, 30, 101, 31], geodesic=False)
    clipped = image.clip(roi)
    return {
        "weights": clipped.mask(),
        "default_science_sample": clipped.sample(geometries=True),
        "calibrated_science_sample": clipped.multiply(2).sample(geometries=True),
        "explicit_weight_sample": clipped.mask().sample(
            region=scan, dropNulls=False, geometries=True,
        ),
    }


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.offline import OfflineGuard

    fixture = json.loads((root / "tests/fixtures/ee-geodesic-clip-wave70-v1.json").read_text())
    source = fixture["synthetic_local_input"]
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:1/openeo/1.2", "a" * 48,
            signatures_path=root / "vendor/earthengine-js/algorithms.json",
        )
        results = {}
        for name, expression in build_workflow(ee, fixture).items():
            result = compile_expression(
                ee.serializer.encode(expression, for_cloud_api=False),
                [source["catalog"]], source["items"],
            )
            results[name] = {"kind": result["kind"], "nodes": len(result["process_graph"])}
    print(json.dumps({"compiled": results, "offline": guard.evidence(), "engine_run": False}, indent=2))


if __name__ == "__main__":
    main()
