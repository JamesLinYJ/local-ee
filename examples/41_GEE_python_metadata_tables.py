"""Offline synthetic metadata preparation through the official EE Python API.

No downloads, Google credentials or business services are used by this example.
Calendar, regex and table policies are documented in docs/gee-python/.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys


def build_workflow(ee):
    scene = ee.String("S2_20200229_tile")
    parts = scene.split("_")
    date = ee.Date.parse("yyyyMMdd", ee.String(parts.get(1)))
    columns = ee.FeatureCollection.fromColumns(
        [["forest", "water", "forest", "other"], [0.2, 0.6, 0.2, 0.9]],
        ["label", "score"],
    )
    distinct = columns.distinct(["label", "score"])
    rows = distinct.remap(["forest", "water"], [1, 2], "label").map(
        lambda feature: feature.set("scaled", ee.Number.expression(
            "score * 100", {"score": feature.get("score")},
        ).toInt()),
    )
    return {
        "parts": parts,
        "matched_date": scene.match("[0-9]{8}"),
        "renamed_scene": scene.replace("_", "-", "g"),
        "parsed_date": date.millis(),
        "next_year": date.update(year=2021).format("yyyy-MM-dd"),
        "month_range": date.getRange("month"),
        "minutes_per_day": ee.Date.unitRatio("day", "minute"),
        "bits": ee.Array.bitsToArray(13),
        "cut": ee.Array([[1, 2], [3, 4]]).cut([1, -1]),
        "masked": ee.Array([10, 20, 30]).mask(ee.Array([1, 0, 1])),
        "index": ee.Number.expression("(v.nir-v.red)/(v.nir+v.red)",
                                      {"v": {"nir": 0.8, "red": 0.2}}),
        "selected": ee.Dictionary({"B2": 2, "B3": 3, "cloud": 90}).select(["B[23]"]),
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
