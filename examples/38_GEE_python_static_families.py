"""Offline EE data preparation using the batch static operator families.

No service, model training, data download or export is started by this example.
"""
from __future__ import annotations

import json
from pathlib import Path


def build_workflow(ee):
    scores = ee.Dictionary.fromLists(["red", "nir", "cloud"], [-2, 8, 15])
    scores = scores.map(lambda _key, value: ee.Number(value).clamp(0, 10))
    scores = scores.rename(["cloud"], ["quality"])
    scores = scores.combine(ee.Dictionary({"version": 1}), True)
    labels = ee.List(["water", "cloud", "land", "water"])
    clean = labels.removeAll(["cloud"]).replaceAll("water", "wet")
    return {
        "scores": scores,
        "score_vector": scores.toArray(["red", "nir", "quality"], 0),
        "normalized_nir": scores.getNumber("nir").unitScale(0, 10),
        "label_count": labels.frequency("water"),
        "label_path": clean.join("/"),
        "spliced": ee.List([1, 2, 3, 4]).splice(-2, 1, [8, 9]),
        "trig_identity": ee.Array([0, 0.5, 1]).asin().sin(),
        "signed_remainder": ee.Array([-7, 7]).mod(ee.Array([3, -3])),
        "name": ee.String("  SCENE_2024  ").trim().toLowerCase().slice(0, 5),
        "json_roundtrip": ee.String.encodeJSON(scores).decodeJSON(),
    }


def main():
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.offline import OfflineGuard

    root = Path(__file__).resolve().parents[1]
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=root / "vendor/earthengine-js/algorithms.json")
        values = {key: compile_expression(
            ee.serializer.encode(value, for_cloud_api=False), [], {},
        )["value"] for key, value in build_workflow(ee).items()}
    assert guard.evidence()["attempt_count"] == 0
    print(json.dumps({"values": values, "network_attempts": 0,
                      "scope": "finite static computation only; no raster or Google comparison"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
