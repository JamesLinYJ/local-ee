"""Finite nested collections, grouped summaries and date intervals.

The four synthetic observations are computed locally through the pinned
official EE client. No dataset downloads or business services are needed.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys


def build_workflow(ee):
    stations = ee.FeatureCollection([
        ee.Feature(None, {"zone": 1, "value": 10}),
        ee.Feature(None, {"zone": 2, "value": 20}),
    ])
    observations = stations.map(lambda station: ee.FeatureCollection([
        station,
        station.set("value", ee.Number(station.get("value")).add(2)),
    ])).flatten()
    statistics = (ee.Reducer.mean().combine(ee.Reducer.sum(), sharedInputs=True)
                  .combine(ee.Reducer.count(), sharedInputs=True)
                  .setOutputs(["average", "total", "n"]))
    grouped = observations.reduceColumns(
        statistics.group(groupField=1, groupName="zone"), ["value", "zone"],
    )
    rows = ee.FeatureCollection(ee.List(grouped.get("groups")).map(
        lambda group: ee.Feature(None, ee.Dictionary(group)),
    ))
    first = ee.DateRange("2020-02-28", "2020-03-02")
    second = ee.DateRange("2020-03-01", "2020-03-05")
    overlap = first.intersection(second)
    return {
        "values": observations.aggregate_array("value"),
        "count": observations.aggregate_count("value"),
        "mean": observations.aggregate_mean("value"),
        "sample_variance": observations.aggregate_sample_var("value"),
        "population_variance": observations.aggregate_total_var("value"),
        "histogram": observations.aggregate_histogram("zone"),
        "distinct_zones": observations.aggregate_count_distinct("zone"),
        "groups": grouped,
        "output_names": statistics.getOutputs(),
        "overlap_start": overlap.start().format("yyyy-MM-dd"),
        "overlap_end": overlap.end().format("yyyy-MM-dd"),
        "union": first.union(second),
        "contains_leap_day": first.contains(ee.Date("2020-02-29")),
        "rows": rows,
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
                      "scope": "Finite static computation; no Google or raster acceptance"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
