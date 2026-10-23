"""Finite multi-column and grouped statistics with the official offline client.

Three synthetic observations exercise real local table computation. Full raster
reducers, Google-service parity and deployed native execution are separate work.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys


LEAVES = (
    "minMax", "product", "stdDev", "variance", "sampleVariance",
    "countEvery", "countDistinct", "countDistinctNonNull", "firstNonNull",
    "lastNonNull", "countRuns", "frequencyHistogram", "allNonZero",
    "anyNonZero", "and", "or", "bitwiseAnd", "bitwiseOr",
)


def build_workflow(ee):
    observations = ee.FeatureCollection([
        ee.Feature(None, {"zone": "north", "x": 1, "y": 10}),
        ee.Feature(None, {"zone": "north", "x": 3, "y": 30}),
        ee.Feature(None, {"zone": "south", "x": 5, "y": 50}),
    ])
    summary = (ee.Reducer.minMax()
               .combine(ee.Reducer.variance(), sharedInputs=True)
               .combine(ee.Reducer.countEvery(), sharedInputs=False))
    grouped = observations.reduceColumns(
        summary.group(groupField=1, groupName="zone"), ["x", "zone"],
    )
    rows = ee.FeatureCollection(ee.List(grouped.get("groups")).map(
        lambda group: ee.Feature(None, ee.Dictionary(group)),
    ))
    results = {
        name: ee.List([1, 3, 5]).reduce(ee.call("Reducer." + name))
        for name in LEAVES
    }
    results.update({
        "repeated": observations.reduceColumns(ee.Reducer.variance().repeat(2), ["x", "y"]),
        "named": observations.reduceColumns(ee.Reducer.minMax().forEach(["x", "y"]), ["x", "y"]),
        "grouped": grouped,
        "rows": rows,
        "outputs": summary.getOutputs(),
    })
    return results


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.offline import OfflineGuard

    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=root / "vendor/earthengine-js/algorithms.json")
        values = {key: compile_expression(ee.serializer.encode(value, for_cloud_api=False),
                                         [], {})["value"]
                  for key, value in build_workflow(ee).items()}
    print(json.dumps({"values": values, "network_attempts": guard.evidence()["attempt_count"],
                      "scope": "Finite static computation; no Google or raster acceptance"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
