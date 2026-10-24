"""Compose color transforms and staged calibration on the Wave57 synthetic grid."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def scene_image(ee, fixture, item_id):
    return ee.ImageCollection(fixture["stac"]["collection"]["id"]).filter(
        ee.Filter.eq("system:index", item_id),
    ).first()


def build_workflow(ee, image, fixture):
    source = ee.Image(image).select(
        fixture["source_band_order"], fixture["prepared_band_order"],
    ).toDouble()
    rgb = source.select(["red", "green", "blue"])
    hsv = ee.Image(rgb.rgbToHsv())

    half_value = ee.Image(
        hsv.select("value").multiply(0.5).rename("value"),
    )
    half_hsv = ee.Image(
        hsv.select("hue")
        .addBands(hsv.select("saturation"))
        .addBands(half_value)
    )
    value_half_rgb = ee.Image(half_hsv.hsvToRgb())

    rgb_roundtrip = ee.Image(ee.Image(rgb.rgbToHsv()).hsvToRgb())
    calibrated = ee.Image(
        rgb_roundtrip.add(0.05)
        .toFloat()
        .toDouble()
        .max(0)
        .min(0.65)
    )
    return {
        "hsv_value_half_then_rgb": value_half_rgb,
        "rgb_roundtrip_offset_float_stage_clamp": calibrated,
    }


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.offline import OfflineGuard

    fixture = json.loads(
        (root / "tests/fixtures/ee-spectral-preparation-wave57-v1.json")
        .read_text(encoding="utf-8")
    )
    catalog = [fixture["stac"]["collection"]]
    items = {fixture["stac"]["collection"]["id"]: [
        scene["item"] for scene in fixture["scenes"]
    ]}
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=root / "vendor/earthengine-js/algorithms.json",
        )
        outputs = {}
        for scene in fixture["scenes"]:
            image = scene_image(ee, fixture, scene["id"])
            expressions = build_workflow(ee, image, fixture)
            outputs[scene["id"]] = {
                name: compile_expression(
                    ee.serializer.encode(value, for_cloud_api=False),
                    catalog, items,
                )
                for name, value in expressions.items()
            }
    assert guard.evidence()["attempt_count"] == 0
    print(json.dumps({
        "fixture": fixture["schema"],
        "outputs": {scene: {name: {
            "bands": value["bands"],
            "process_graph_nodes": len(value["process_graph"]),
        } for name, value in graphs.items()} for scene, graphs in outputs.items()},
        "network_attempts": 0,
        "backend_or_native_runtime_used": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
