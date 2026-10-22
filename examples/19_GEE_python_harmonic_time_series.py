"""Fit a three-term harmonic model to bounded synthetic image time series."""

from __future__ import annotations

import math

SYNTHETIC_VERSION = "local-ee-synthetic-harmonic-time-series/v1"
DAY_MILLIS = 86_400_000
PERIOD_DAYS = 360
BANDS = ["ndvi", "quality"]
FRAME_LABELS = [
    "day_000", "day_090", "day_180_a", "day_180_b",
    "day_270", "day_360", "day_450",
]
COEFFICIENT_LABELS = ["intercept", "cosine", "sine"]


def build_harmonic_series(ee, collection, origin_millis, target_day=540):
    """Fit NDVI by sorted acquisition date; retain per-band series masks."""
    ordered = ee.ImageCollection(collection).sort("system:time_start")
    frames = ordered.map(lambda image: ee.Image(image).select(BANDS).toFloat())
    timestamps = ordered.aggregate_array("system:time_start")
    origin = ee.Date(origin_millis)
    sample_days = ee.List(timestamps).map(
        lambda timestamp: ee.Date(timestamp).difference(start=origin, unit="day")
    )

    def design_row(day):
        angle = ee.Number(day).multiply(2 * math.pi / PERIOD_DAYS)
        return ee.List([1, ee.Number(angle).cos(), ee.Number(angle).sin()])

    rows = ee.List(sample_days).map(design_row)
    design = ee.Image(ee.Array(rows)).toFloat()
    packed = frames.toArrayPerBand(axis=0, dropMasked=False)
    signal_series = packed.select(["ndvi"])
    quality_series = packed.select(["quality"])
    signal_vector = signal_series.arrayReshape(
        lengths=ee.Image(ee.Array([len(FRAME_LABELS), 1])), dimensions=2
    ).toFloat()

    coefficients = design.matrixSolve(signal_vector)
    fitted = design.matrixMultiply(coefficients).toFloat()
    residuals = signal_vector.subtract(fitted).toFloat()

    target_date = origin_millis + target_day * DAY_MILLIS
    target_offset = ee.Date(target_date).difference(start=origin, unit="day")
    target_angle = ee.Number(target_offset).multiply(2 * math.pi / PERIOD_DAYS)
    target_design = ee.Image(ee.Array([[
        1, ee.Number(target_angle).cos(), ee.Number(target_angle).sin(),
    ]])).toFloat()
    prediction = target_design.matrixMultiply(coefficients)

    return {
        "source_ids": ordered.aggregate_array("system:index"),
        "sample_days": sample_days,
        "design_matrix": ee.Array(rows),
        "ndvi_series": signal_series.arrayFlatten([FRAME_LABELS]),
        "quality_series": quality_series.arrayFlatten([FRAME_LABELS]),
        "coefficients": coefficients.arrayProject([0]).arrayFlatten([COEFFICIENT_LABELS]),
        "fitted": fitted.arrayProject([0]).arrayFlatten([FRAME_LABELS]),
        "residuals": residuals.arrayProject([0]).arrayFlatten([FRAME_LABELS]),
        "target_prediction": prediction.arrayProject([0]).arrayFlatten([["target_ndvi"]]),
    }


def main():
    import json
    from pathlib import Path
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression

    fixture = json.loads(
        (root / "tests/fixtures/ee-harmonic-time-series-v1.json").read_text()
    )
    if fixture["schema"] != SYNTHETIC_VERSION:
        raise ValueError("Unexpected synthetic harmonic fixture version")
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
                + fixture["frame_days"][scene_id] * DAY_MILLIS,
        },
    } for scene_id in fixture["frame_order"]]
    ee = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=root / "vendor/earthengine-js/algorithms.json",
    )
    outputs = build_harmonic_series(
        ee, ee.ImageCollection(fixture["collection_id"]),
        fixture["origin_millis"], fixture["target_day"],
    )
    for name, value in outputs.items():
        compiled = compile_expression(
            ee.serializer.encode(value, for_cloud_api=False), catalog,
            {fixture["collection_id"]: items},
        )
        print(json.dumps({
            "fixture": SYNTHETIC_VERSION,
            "output": name,
            "kind": compiled["kind"],
            "bands": compiled.get("bands"),
            "source_item_ids": compiled.get("source_item_ids"),
            "graph_nodes": len(compiled.get("process_graph", {})),
        }))


if __name__ == "__main__":
    main()
