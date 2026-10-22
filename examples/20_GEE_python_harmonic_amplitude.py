"""Add amplitude to the preceding synthetic harmonic fit workflow."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SYNTHETIC_VERSION = "local-ee-synthetic-harmonic-amplitude/v1"


def _load_harmonic_builder():
    example_path = Path(__file__).with_name("19_GEE_python_harmonic_time_series.py")
    spec = importlib.util.spec_from_file_location("harmonic_time_series_example", example_path)
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load the shared harmonic time-series workflow")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_harmonic_amplitude(ee, collection, origin_millis, target_day=540):
    """Return fitted coefficients, the cosine/sine amplitude and prediction.

    Phase is intentionally omitted; this example verifies magnitude only.
    """
    harmonic = _load_harmonic_builder().build_harmonic_series(
        ee, collection, origin_millis, target_day,
    )
    coefficients = harmonic["coefficients"]
    cosine = coefficients.select(["cosine"])
    sine = coefficients.select(["sine"])
    amplitude = cosine.hypot(sine).rename(["amplitude"])
    return {
        "amplitude": amplitude,
        "coefficients": coefficients,
        "intercept": coefficients.select(["intercept"]),
        "target_prediction": harmonic["target_prediction"],
    }


def main():
    import json
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression

    fixture = json.loads(
        (root / "tests/fixtures/ee-harmonic-amplitude-v1.json").read_text()
    )
    if fixture["schema"] != SYNTHETIC_VERSION:
        raise ValueError("Unexpected synthetic harmonic-amplitude fixture version")
    catalog = [{
        "id": fixture["collection_id"],
        "cube:dimensions": {"bands": {"values": fixture["bands"]}},
    }]
    items = [{
        "id": scene_id,
        "bbox": fixture["bbox"],
        "geometry": fixture["scene_geometry"],
        "properties": {
            "system:index": scene_id,
            "system:time_start": fixture["origin_millis"]
                + fixture["frame_days"][scene_id] * 86_400_000,
        },
    } for scene_id in fixture["frame_order"]]
    ee = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=root / "vendor/earthengine-js/algorithms.json",
    )
    outputs = build_harmonic_amplitude(
        ee, ee.ImageCollection(fixture["collection_id"]),
        fixture["origin_millis"], fixture["target_day"],
    )
    for name, image in outputs.items():
        result = compile_expression(
            ee.serializer.encode(image, for_cloud_api=False), catalog,
            {fixture["collection_id"]: items},
        )
        print(json.dumps({
            "fixture": SYNTHETIC_VERSION,
            "output": name,
            "kind": result["kind"],
            "bands": result.get("bands"),
            "source_item_ids": result.get("source_item_ids"),
            "graph_nodes": len(result.get("process_graph", {})),
        }))


if __name__ == "__main__":
    main()
