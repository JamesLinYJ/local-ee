"""Cumulative NDVI anomalies and per-pixel matrix norm on synthetic scenes."""

SYNTHETIC_VERSION = "local-ee-synthetic-cumulative-anomaly/v1"
FRAME_LABELS = ["day_000", "day_180_a", "day_180_b", "day_366"]


def build_cumulative_anomaly(ee, collection, baseline):
    """Return ordered anomalies, cumulative reducers and their Frobenius norm."""
    ordered = ee.ImageCollection(collection).sort("system:time_start")
    frames = ordered.map(lambda image: ee.Image(image).select(["ndvi"]).toFloat())
    packed = frames.toArrayPerBand(axis=0, dropMasked=False)
    observations = packed.select(["ndvi"]).arrayReshape(
        lengths=ee.Image(ee.Array([len(FRAME_LABELS), 1])), dimensions=2,
    ).toFloat()
    baseline_column = ee.Image(ee.Array([[value] for value in baseline])).toFloat()
    anomalies = observations.subtract(baseline_column).toFloat()

    cumulative = anomalies.arrayAccum(axis=0).toFloat()
    cumulative_sum = anomalies.arrayAccum(
        axis=0, reducer=ee.Reducer.sum(),
    ).toFloat()
    prefix_min = anomalies.arrayAccum(
        axis=0, reducer=ee.Reducer.min(),
    ).toFloat()
    prefix_max = anomalies.arrayAccum(
        axis=0, reducer=ee.Reducer.max(),
    ).toFloat()

    return {
        "source_ids": ordered.aggregate_array("system:index"),
        "anomalies": anomalies.arrayProject([0]).arrayFlatten([FRAME_LABELS]),
        "cumulative": cumulative.arrayProject([0]).arrayFlatten([FRAME_LABELS]),
        "cumulative_sum": cumulative_sum.arrayProject([0]).arrayFlatten([FRAME_LABELS]),
        "prefix_min": prefix_min.arrayProject([0]).arrayFlatten([FRAME_LABELS]),
        "prefix_max": prefix_max.arrayProject([0]).arrayFlatten([FRAME_LABELS]),
        "frobenius_norm": anomalies.matrixFnorm().rename("anomaly_frobenius_norm"),
    }


def main():
    import json
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression

    fixture = json.loads(
        (root / "tests/fixtures/ee-cumulative-anomaly-v1.json").read_text()
    )
    if fixture["schema"] != SYNTHETIC_VERSION:
        raise ValueError("Unexpected cumulative-anomaly fixture version")
    catalog = [{
        "id": fixture["collection_id"],
        "cube:dimensions": {"bands": {"values": fixture["bands"]}},
    }]
    items = [{
        "id": frame,
        "bbox": fixture["bbox"],
        "geometry": fixture["scene_geometry"],
        "properties": {
            "system:index": frame,
            "system:time_start": fixture["origin_millis"]
                + fixture["frame_days"][frame] * 86_400_000,
        },
    } for frame in fixture["frame_order"]]
    ee = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=root / "vendor/earthengine-js/algorithms.json",
    )
    outputs = build_cumulative_anomaly(
        ee, ee.ImageCollection(fixture["collection_id"]), fixture["baseline"],
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
