"""Finite distribution summaries and directional statistics, entirely offline.

These reducers currently evaluate inline tables and lists, not raster pixels.
Interpolation, ties and moment normalization follow the documented local policy.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys


def build_workflow(ee):
    values = ee.List([0, 1, 1, 2, 4, 8])
    angles = ee.List([-math.pi / 4, 0, math.pi / 4])
    quantiles = ee.Reducer.percentile([0, 25, 50, 75, 100],
                                    ["lo", "q1", "median", "q3", "hi"], maxRaw=1000)
    summary = ee.Reducer.percentile([0, 50, 100], ["lo", "median", "hi"], maxRaw=1000)
    for reducer in (ee.Reducer.mode(maxRaw=1000), ee.Reducer.skew(),
                    ee.Reducer.kurtosis(),
                    ee.Reducer.intervalMean(0, 100, maxRaw=1000).setOutputs(["mean"])):
        summary = summary.combine(reducer, sharedInputs=True)
    observations = ee.FeatureCollection([
        ee.Feature(None, {"value": value, "group": index // 3})
        for index, value in enumerate([0, 1, 1, 2, 4, 8])
    ])
    groups = observations.reduceColumns(summary.group(1, "group"), ["value", "group"])
    rows = ee.FeatureCollection(ee.List(groups.get("groups")).map(
        lambda row: ee.Feature(None, ee.Dictionary(row))))
    return {
        "quantiles": values.reduce(quantiles),
        "intervalMean": values.reduce(ee.Reducer.intervalMean(0, 100, maxRaw=1000)),
        "mode": values.reduce(ee.Reducer.mode(maxRaw=1000)),
        "skew": values.reduce(ee.Reducer.skew()),
        "kurtosis": values.reduce(ee.Reducer.kurtosis()),
        "circularMean": angles.reduce(ee.Reducer.circularMean()),
        "circularStddev": angles.reduce(ee.Reducer.circularStddev()),
        "circularVariance": angles.reduce(ee.Reducer.circularVariance()),
        "summary": observations.reduceColumns(summary, ["value"]),
        "groups": groups,
        "rows": rows,
        "repeated": ee.List([[1, 10], [3, 30], [5, 50]]).reduce(
            ee.Reducer.percentile([50], ["middle"]).repeat(2)),
    }


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.offline import OfflineGuard

    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=root / "vendor/earthengine-js/algorithms.json")
        results = {key: compile_expression(ee.serializer.encode(value, for_cloud_api=False),
                                          [], {})["value"]
                   for key, value in build_workflow(ee).items()}
    print(json.dumps({"values": results, "network_attempts": guard.evidence()["attempt_count"],
                      "scope": "Finite static computation; no Google or deployment acceptance"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
