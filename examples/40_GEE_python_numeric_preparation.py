"""Finite EE metadata preparation; synthetic values, no data download or task.

Run with the project's Python for a local static result. Array integer rounding
and Number integer truncation are distinct contracts; neither casts raster data.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys


def build_workflow(ee):
    positive = ee.List([-0.1, 0.25, 0.8, 1.1]).filter(ee.Filter.gt("item", 0))
    encoded = positive.map(lambda value: ee.Number(value).multiply(255).toByte())
    metadata = ee.Dictionary({"red": 2, "nir": 8, "cloud": 90, "unused": None})
    selected = metadata.select(["red", "nir"])
    rows = encoded.map(lambda value: ee.Feature(None, {"encoded": value}))
    return {
        "positive": positive,
        "encoded": encoded,
        "selected": selected,
        "removed": metadata.remove(["cloud", "unused"]),
        "number_integer": ee.Number(-12.75).toInt16(),
        "array_byte": ee.Array([-0.1, 0.1, 0.5, 127.1, 255.1, 255.9]).byte(),
        "float_roundtrip": ee.Array([16777217, 1.25]).toFloat().toDouble(),
        "inverse_erf": ee.Number(0.5).erf().erfInv(),
        "digamma_one": ee.Number(1).digamma(),
        "trigamma": ee.Array([1, 0.5]).trigamma(),
        "rows": ee.FeatureCollection(rows),
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
        values = {key: compile_expression(
            ee.serializer.encode(value, for_cloud_api=False), [], {},
        )["value"] for key, value in build_workflow(ee).items()}
    print(json.dumps({"values": values, "network_attempts": guard.evidence()["attempt_count"],
                      "scope": "Finite static computation; no raster engine or Google comparison"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
