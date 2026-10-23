"""Finite synthetic trend, covariance, distribution and collection workflow.

Uses the official client entirely offline. Explicit output names keep the
example independent of default labels that have not been checked on Google.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys


def build_workflow(ee):
    x = [1, 2, 3, 4, 5, 6]
    y = [2, 1, 4, 3, 6, 5]
    pairs = ee.List([[a, b] for a, b in zip(x, y)])
    observations = ee.FeatureCollection([
        ee.Feature(None, {"x": a, "y": b, "vector": ee.Array([a, b])})
        for a, b in zip(x, y)
    ])
    centered = ee.List([ee.Array([a - 3.5, b - 3.5]) for a, b in zip(x, y)])
    covariance = observations.reduceColumns(ee.Reducer.covariance(), ["vector"])
    pearson = ee.Reducer.pearsonsCorrelation().setOutputs(["r", "p"])
    sen = ee.Reducer.sensSlope().setOutputs(["slope", "intercept"])
    summary = observations.reduceColumns(pearson.combine(sen, sharedInputs=True), ["x", "y"])
    collected = observations.reduceColumns(
        ee.Reducer.toCollection(["time", "signal"]).setOutputs(["features"]), ["x", "y"])
    return {
        "pearson": pairs.reduce(pearson),
        "spearman": pairs.reduce(ee.Reducer.spearmansCorrelation()),
        "kendall": pairs.reduce(ee.Reducer.kendallsCorrelation(2)),
        "kendallOrdinal": ee.List(y).reduce(ee.Reducer.kendallsCorrelation()),
        "sen": pairs.reduce(sen),
        "covariance": covariance,
        "centeredCovariance": centered.reduce(ee.Reducer.centeredCovariance()),
        "eigen": ee.Array(covariance.get("array")).eigen(),
        "histogram": ee.List(y).reduce(ee.Reducer.fixedHistogram(0, 8, 4)),
        "cumulative": ee.List(y).reduce(ee.Reducer.fixedHistogram(0, 8, 4, True)),
        "histogram2D": pairs.reduce(ee.Reducer.fixed2DHistogram(0, 8, 2, 0, 8, 2)
                                    .setOutputs(["counts", "xEdges", "yEdges"])),
        "list": observations.reduceColumns(ee.Reducer.toList(2), ["x", "y"]),
        "collected": ee.FeatureCollection(collected.get("features")),
        "summary": summary,
        "rows": ee.FeatureCollection([ee.Feature(None, summary)]),
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
        values = {key: compile_expression(ee.serializer.encode(value, for_cloud_api=False),
                                         [], {})["value"]
                  for key, value in build_workflow(ee).items()}
    print(json.dumps({"values": values, "network_attempts": guard.evidence()["attempt_count"],
                      "scope": "Finite synthetic computation; no Google or production acceptance"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
